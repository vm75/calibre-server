"""Optional remembered browser sessions for the Calibre Content server.

Enable with CALIBRE_REMEMBER_ORIGIN=https://your-canonical-host.
Basic/Digest clients continue to use the original authentication controller.
"""
import hashlib
import hmac
import html
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from calibre.constants import config_dir
from calibre.srv.errors import HTTPBadRequest, HTTPForbidden, HTTPNotFound, HTTPTempRedirect
from calibre.srv.routes import endpoint
from calibre.utils.resources import get_path as P

SESSION_COOKIE = '__Host-calibre-session'
CSRF_COOKIE = '__Host-calibre-csrf'
LOGIN_COOKIE = '__Host-calibre-login'
COOKIE_LIFETIME = 400 * 24 * 60 * 60
DURATIONS = {'session': 24 * 60 * 60, '30days': 30 * 24 * 60 * 60, 'permanent': None}
HEX_TOKEN = re.compile(r'^[a-f0-9]{64}$')


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def credential_stamp(token, password):
    return hmac.new(token.encode('ascii'), password.encode('utf-8'), hashlib.sha256).hexdigest()


def database_path(users):
    override = os.environ.get('CALIBRE_REMEMBER_DB')
    if override:
        return override
    path = getattr(users, 'path', None)
    return path + '.sessions' if path and path != ':memory:' else os.path.join(config_dir, 'remember-sessions.sqlite')


@contextmanager
def connection(path):
    # The database contains bearer-token hashes, never raw bearer tokens.
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    os.close(fd)
    os.chmod(path, 0o600)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        with db:
            db.execute('''CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
                username TEXT NOT NULL, credential_stamp TEXT NOT NULL,
                csrf_hash TEXT NOT NULL, mode TEXT NOT NULL,
                created INTEGER NOT NULL, last_seen INTEGER NOT NULL,
                expires INTEGER)''')
            yield db
    finally:
        db.close()


def revoke_user(users, username):
    path = database_path(users)
    if Path(path).exists():
        with connection(path) as db:
            db.execute('DELETE FROM sessions WHERE username=?', (username,))


def cookie(rd, name, value, *, max_age=None, http_only=True):
    rd.outcookie[name] = value
    item = rd.outcookie[name]
    item['path'] = '/'
    item['secure'] = True
    item['httponly'] = http_only
    item['samesite'] = 'Lax'
    if max_age is not None:
        item['max-age'] = max_age


def clear_cookies(rd):
    cookie(rd, SESSION_COOKIE, '', max_age=0)
    cookie(rd, CSRF_COOKIE, '', max_age=0, http_only=False)


def read_form(rd):
    if rd.inheaders.get('Content-Type', '').split(';')[0].strip().lower() != 'application/x-www-form-urlencoded':
        raise HTTPBadRequest('Expected a URL-encoded form')
    stream = rd.request_body_file
    position = stream.tell()
    try:
        raw = stream.read(8193)
    finally:
        stream.seek(position)
    if len(raw) > 8192:
        raise HTTPBadRequest('Form is too large')
    try:
        form = parse_qs(raw.decode('utf-8'), keep_blank_values=True, max_num_fields=10)
    except (UnicodeError, ValueError):
        raise HTTPBadRequest('Invalid form')
    if any(len(values) != 1 for values in form.values()):
        raise HTTPBadRequest('Repeated form field')
    return {key: values[0] for key, values in form.items()}


def no_store(rd):
    rd.outheaders['Cache-Control'] = 'no-store'
    rd.outheaders['Referrer-Policy'] = 'same-origin'
    rd.outheaders['X-Frame-Options'] = 'DENY'


class RememberSessions:
    def __init__(self, users):
        self.users = users
        self.path = database_path(users)
        self.origin = os.environ.get('CALIBRE_REMEMBER_ORIGIN', '').rstrip('/')
        self.enabled = bool(self.origin)
        if self.enabled:
            url = urlsplit(self.origin)
            local_http = url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1', '::1')
            if (url.scheme != 'https' and not local_http) or not url.hostname or url.path or url.query or url.fragment or url.username or url.password:
                raise ValueError('CALIBRE_REMEMBER_ORIGIN must be an HTTPS origin (HTTP is allowed only on loopback for tests)')
            self.authority = url.netloc.lower()

    def check_origin(self, rd):
        if rd.inheaders.get('Host', '').lower() != self.authority:
            raise HTTPForbidden('Use the configured HTTPS address for browser login')
        origin = rd.inheaders.get('Origin')
        unsafe = rd.method not in ('GET', 'HEAD', 'OPTIONS')
        if (origin and origin != self.origin) or (unsafe and rd.inheaders.get('Sec-Fetch-Site') == 'cross-site'):
            raise HTTPForbidden('Cross-site authentication request rejected')

    def issue(self, rd, username, password, mode):
        now = int(time.time())
        token, csrf = secrets.token_hex(32), secrets.token_hex(32)
        lifetime = DURATIONS[mode]
        expires = now + lifetime if lifetime is not None else None
        # Rotate this browser's old session at every successful login.
        old = rd.cookies.get(SESSION_COOKIE, '')
        with connection(self.path) as db:
            db.execute('DELETE FROM sessions WHERE expires IS NOT NULL AND expires<=?', (now,))
            if HEX_TOKEN.fullmatch(old):
                db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(old),))
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)', (
                secrets.token_hex(12), digest(token), username, credential_stamp(token, password),
                digest(csrf), mode, now, now, expires,
            ))
        self.set_session_cookies(rd, token, csrf, mode, expires)

    def set_session_cookies(self, rd, token, csrf, mode, expires):
        age = None if mode == 'session' else COOKIE_LIFETIME if mode == 'permanent' else max(0, expires - int(time.time()))
        cookie(rd, SESSION_COOKIE, token, max_age=age)
        cookie(rd, CSRF_COOKIE, csrf, max_age=age, http_only=False)

    def authenticate(self, rd, endpoint_):
        token = rd.cookies.get(SESSION_COOKIE, '')
        if not self.enabled or not HEX_TOKEN.fullmatch(token):
            return False
        self.check_origin(rd)
        now = int(time.time())
        with connection(self.path) as db:
            row = db.execute('SELECT * FROM sessions WHERE token_hash=?', (digest(token),)).fetchone()
            if row is None:
                clear_cookies(rd)
                return False
            password = self.users.get(row['username'])
            if (row['expires'] is not None and row['expires'] <= now) or not password or not hmac.compare_digest(row['credential_stamp'], credential_stamp(token, password)):
                db.execute('DELETE FROM sessions WHERE id=?', (row['id'],))
                clear_cookies(rd)
                return False
            rd.remember_session = dict(row)
            rd.username = row['username']
            needs_csrf = (rd.method not in ('GET', 'HEAD', 'OPTIONS') or endpoint_.needs_db_write
                          or endpoint_.route.startswith('/cdb/') or endpoint_.route == '/interface-data/set-session-data')
            if needs_csrf:
                csrf = rd.inheaders.get('X-Calibre-Csrf', '')
                if not csrf and rd.inheaders.get('Content-Type', '').startswith('application/x-www-form-urlencoded'):
                    csrf = read_form(rd).get('_csrf', '')
                if not HEX_TOKEN.fullmatch(csrf) or not hmac.compare_digest(digest(csrf), row['csrf_hash']):
                    raise HTTPForbidden('Missing or invalid CSRF token')
            csrf = rd.cookies.get(CSRF_COOKIE, '')
            if not HEX_TOKEN.fullmatch(csrf) or not hmac.compare_digest(digest(csrf), row['csrf_hash']):
                csrf = secrets.token_hex(32)
                db.execute('UPDATE sessions SET csrf_hash=? WHERE id=?', (digest(csrf), row['id']))
                rd.remember_session['csrf_hash'] = digest(csrf)
            db.execute('UPDATE sessions SET last_seen=? WHERE id=? AND last_seen<?', (now, row['id'], now - 60))
        self.set_session_cookies(rd, token, csrf, row['mode'], row['expires'])
        no_store(rd)
        return True


def controller(ctx):
    auth = ctx.auth_controller
    if auth is None or not auth.remember_sessions.enabled:
        raise HTTPNotFound('Remembered browser login is not enabled')
    return auth


def page(rd, title, body):
    no_store(rd)
    rd.outheaders['Content-Type'] = 'text/html; charset=UTF-8'
    rd.outheaders['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>' + html.escape(title) + '</title><style>'
            ':root{color-scheme:light dark;font:17px system-ui}body{max-width:38rem;margin:5vh auto;padding:1.2rem}'
            'h1{font-size:1.7rem}label{display:block;margin:1rem 0 .3rem}input,select,button{font:inherit;padding:.65rem;box-sizing:border-box}'
            'input:not([type=hidden]),select{width:100%}button{cursor:pointer;margin:.8rem .5rem .8rem 0}'
            '.error{color:light-dark(#a31818,#ffaaaa)}li{margin:1rem 0}small{opacity:.8}a{color:light-dark(#17449b,#9ac6ff)}'
            '</style><h1>' + html.escape(title) + '</h1>' + body + '</html>').encode('utf-8')


def login_page(ctx, rd, error='', username=''):
    nonce = secrets.token_hex(32)
    cookie(rd, LOGIN_COOKIE, nonce, max_age=600)
    body = '<p>Sign in with your Calibre account.</p>'
    if error:
        body += '<p class="error" role="alert">' + html.escape(error) + '</p>'
    body += ('<form method="post" action="' + html.escape(ctx.url_for('/auth/login'), quote=True) + '">'
             '<input type="hidden" name="_csrf" value="' + nonce + '">'
             '<label for="username">Username</label><input id="username" name="username" autocomplete="username" maxlength="255" required value="' + html.escape(username, quote=True) + '">'
             '<label for="password">Password</label><input id="password" type="password" name="password" autocomplete="current-password" required>'
             '<label for="duration">Keep me signed in</label><select id="duration" name="duration">'
             '<option value="session">This browser session (up to 24 hours)</option>'
             '<option value="30days" selected>30 days</option>'
             '<option value="permanent">Until I sign out</option></select>'
             '<p><small>“Until I sign out” has no server expiry. Signing out, revoking the device, changing your password, or clearing browser data ends access.</small></p>'
             '<button type="submit">Sign in</button></form>')
    return page(rd, 'Sign in to Calibre', body)


@endpoint('/auth/login', methods={'GET', 'POST'}, auth_required=False, cache_control='no-cache')
def login(ctx, rd):
    auth = controller(ctx)
    store = auth.remember_sessions
    store.check_origin(rd)
    if rd.method == 'GET':
        return login_page(ctx, rd)
    form = read_form(rd)
    nonce, supplied = rd.cookies.get(LOGIN_COOKIE, ''), form.get('_csrf', '')
    if not HEX_TOKEN.fullmatch(nonce) or not hmac.compare_digest(nonce, supplied):
        raise HTTPForbidden('Login form expired; reload the page and try again')
    username, password, mode = form.get('username', ''), form.get('password', ''), form.get('duration', '')
    if not username or len(username) > 255 or not password or len(password) > 4096 or mode not in DURATIONS:
        raise HTTPBadRequest('Invalid login form')
    if auth.ban_list.is_banned(rd.remote_addr):
        raise HTTPForbidden('Too many login attempts; try again later')
    if not auth.check(username, password):
        auth.ban_list.failed(rd.remote_addr)
        rd.status_code = 401
        return login_page(ctx, rd, 'Invalid username or password.', username)
    store.issue(rd, username, password, mode)
    cookie(rd, LOGIN_COOKIE, '', max_age=0)
    no_store(rd)
    rd.status_code = 303
    rd.outheaders['Location'] = ctx.url_for(None)
    return b''


@endpoint('/auth/sessions', auth_required=True, cache_control='no-cache')
def sessions(ctx, rd):
    store = controller(ctx).remember_sessions
    current = getattr(rd, 'remember_session', None)
    if current is None:
        raise HTTPTempRedirect(ctx.url_for('/auth/login'), http_code=303)
    csrf = rd.outcookie[CSRF_COOKIE].value
    def form(action, label, session_id=''):
        return ('<form method="post" action="' + html.escape(ctx.url_for(action), quote=True) + '">'
                '<input type="hidden" name="_csrf" value="' + csrf + '">'
                '<input type="hidden" name="session_id" value="' + session_id + '">'
                '<button type="submit">' + label + '</button></form>')
    body = '<p>Signed in as <strong>' + html.escape(rd.username) + '</strong>.</p><p><a href="' + html.escape(ctx.url_for(None), quote=True) + '">Back to library</a></p>'
    body += form('/auth/logout', 'Sign out of this browser') + form('/auth/logout-all', 'Sign out of all remembered browsers')
    body += '<h2>Remembered browsers</h2><ul>'
    with connection(store.path) as db:
        rows = db.execute('SELECT id,mode,created,last_seen,expires FROM sessions WHERE username=? AND (expires IS NULL OR expires>?) ORDER BY created DESC', (rd.username, int(time.time()))).fetchall()
    for row in rows:
        label = {'session': 'Browser session', '30days': '30 days', 'permanent': 'Until signed out'}[row['mode']]
        body += '<li>' + label + (' — this browser' if row['id'] == current['id'] else '')
        body += '<br><small>Created ' + time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(row['created'])) + '; last used ' + time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(row['last_seen'])) + '</small>'
        body += form('/auth/revoke', 'Revoke this session', row['id']) + '</li>'
    return page(rd, 'Calibre account', body + '</ul>')


def revoke(ctx, rd, *, all_sessions=False, selected=False):
    store = controller(ctx).remember_sessions
    current = getattr(rd, 'remember_session', None)
    if current is None:
        raise HTTPForbidden('Sign in using the browser login page first')
    form = read_form(rd)
    target = form.get('session_id', '') if selected else current['id']
    with connection(store.path) as db:
        if all_sessions:
            db.execute('DELETE FROM sessions WHERE username=?', (rd.username,))
        else:
            db.execute('DELETE FROM sessions WHERE id=? AND username=?', (target, rd.username))
    if all_sessions or target == current['id']:
        clear_cookies(rd)
        destination = '/auth/login'
    else:
        destination = '/auth/sessions'
    no_store(rd)
    rd.status_code = 303
    rd.outheaders['Location'] = ctx.url_for(destination)
    return b''


@endpoint('/auth/logout', methods={'POST'}, cache_control='no-cache')
def logout(ctx, rd):
    return revoke(ctx, rd)


@endpoint('/auth/logout-all', methods={'POST'}, cache_control='no-cache')
def logout_all(ctx, rd):
    return revoke(ctx, rd, all_sessions=True)


@endpoint('/auth/revoke', methods={'POST'}, cache_control='no-cache')
def revoke_session(ctx, rd):
    return revoke(ctx, rd, selected=True)


@endpoint('/auth/client.js', auth_required=False, cache_control='no-cache')
def client(ctx, rd):
    controller(ctx)
    rd.outheaders['Content-Type'] = 'application/javascript; charset=UTF-8'
    return open(P('content-server/remember-client.js', allow_user_override=False), 'rb')


def index_page(ctx, rd):
    rd.outheaders.set('Content-Type', 'text/html; charset=UTF-8', replace_all=True)
    content = Path(P('content-server/index-generated.html')).read_bytes()
    if ctx.auth_controller is not None and ctx.auth_controller.remember_sessions.enabled:
        no_store(rd)
        script = ('<script src="' + html.escape(ctx.url_for('/auth/client.js'), quote=True) + '"></script>').encode()
        if b'<head>' not in content:
            raise RuntimeError('Expected the packaged Calibre HTML head')
        content = content.replace(b'<head>', b'<head>' + script, 1)
    return content
