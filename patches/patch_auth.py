"""Small, fail-closed patch against a matching Calibre source release."""
from pathlib import Path
import sys


def change(path: Path, old: str, new: str) -> None:
    source = path.read_text(encoding="utf-8")
    matches = source.count(old)
    if matches != 1:
        raise RuntimeError(
            f"Expected exactly one matching patch location in {path}; found {matches}. "
            "Check the Calibre version and review upstream changes."
        )
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}")


src = Path(sys.argv[1])

# Preserve other invalid-credential handling; an empty Basic credential now
# returns a standard 401 + WWW-Authenticate instead of a 400 response.
change(
    src / "calibre/srv/auth.py",
    """                if not un or not pw:
                    raise HTTPSimpleResponse(http.client.BAD_REQUEST, 'The username or password was empty')""",
    """                if not un or not pw:
                    raise HTTPAuthRequired(f'Basic realm="{self.realm}"')""",
)

# With users configured, challenge top-level navigation instead of waiting for
# the JavaScript /interface-data/init request to trigger authentication.
change(
    src / "calibre/srv/code.py",
    """@endpoint('', auth_required=False)
def index(""",
    """@endpoint('', auth_required=True)
def index(""",
)

# This image packages a release, not an interactive development checkout.
# Retain compiled web assets and precompiled forms instead of rebuilding them
# whenever the GUI's embedded server starts.
change(
    src / "calibre/constants.py",
    "is_running_from_develop = running_in_develop_mode()",
    "is_running_from_develop = False  # Packaged authentication patch",
)

change(
    src / 'calibre/srv/auth.py',
    '        self.user_credentials, self.prefer_basic_auth = user_credentials, prefer_basic_auth',
    '        from calibre.srv.remember import RememberSessions\n'
    '        self.remember_sessions = RememberSessions(user_credentials)\n'
    '        self.user_credentials, self.prefer_basic_auth = user_credentials, prefer_basic_auth',
)
change(
    src / 'calibre/srv/auth.py',
    '    def __call__(self, data, endpoint):\n        path = encode_path(*data.path)',
    '''    def __call__(self, data, endpoint):
        if not data.inheaders.get('Authorization'):
            if self.remember_sessions.authenticate(data, endpoint):
                return
            if self.remember_sessions.enabled and endpoint.route == '/' and 'text/html' in data.inheaders.get('Accept', ''):
                from calibre.srv.errors import HTTPTempRedirect
                prefix = (data.opts.url_prefix or '').rstrip('/')
                raise HTTPTempRedirect(self.remember_sessions.origin + prefix + '/auth/login', http_code=303)
        path = encode_path(*data.path)''',
)
change(
    src / 'calibre/srv/handler.py',
    "'opds', 'users_api', 'convert', 'fts')",
    "'opds', 'users_api', 'convert', 'fts', 'remember')",
)
change(
    src / 'calibre/srv/handler.py',
    '        self.router = Router(ctx=ctx, url_prefix=opts.url_prefix, auth_controller=self.auth_controller)',
    '        ctx.auth_controller = self.auth_controller\n'
    '        self.router = Router(ctx=ctx, url_prefix=opts.url_prefix, auth_controller=self.auth_controller)',
)
change(
    src / 'calibre/srv/code.py',
    "    return open(P('content-server/index-generated.html'), 'rb')",
    '    from calibre.srv.remember import index_page\n    return index_page(ctx, rd)',
)
change(
    src / 'calibre/srv/users.py',
    "            self.conn.cursor().execute('UPDATE users SET pw=? WHERE name=?', (pw, username))",
    "            self.conn.cursor().execute('UPDATE users SET pw=? WHERE name=?', (pw, username))\n"
    '            from calibre.srv.remember import revoke_user\n            revoke_user(self, username)',
)
change(
    src / 'calibre/srv/users.py',
    "            return self.conn.changes() > 0",
    "            removed = self.conn.changes() > 0\n"
    '            from calibre.srv.remember import revoke_user\n'
    '            revoke_user(self, username)\n            return removed',
)
change(
    src / 'calibre/srv/users.py',
    '            remove = self.all_user_names - set(users)',
    '            old_credentials = {name: self.get(name) for name in self.all_user_names}\n'
    '            remove = self.all_user_names - set(users)',
)
change(
    src / 'calibre/srv/users.py',
    '            self.refresh()\n',
    '            self.refresh()\n'
    '            from calibre.srv.remember import revoke_user\n'
    '            for name, password in old_credentials.items():\n'
    "                if name not in users or users[name]['pw'] != password:\n"
    '                    revoke_user(self, name)\n',
)
