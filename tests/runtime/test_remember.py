"""HTTP integration tests; all accounts, libraries, and session stores are temporary."""
import base64
import json
import os
import re
import secrets
import tempfile
import time
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from calibre.db.legacy import create_backend
from calibre.srv.tests.base import LibraryServer

ORIGIN = 'https://remember.test'
SESSION = '__Host-calibre-session'
CSRF = '__Host-calibre-csrf'


class RememberTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.library = str(root / 'library')
        create_backend(self.library).close()
        self.secret_library = str(root / 'secret-library')
        create_backend(self.secret_library).close()
        self.userdb = str(root / 'users.sqlite')
        env = patch.dict(os.environ, {'CALIBRE_REMEMBER_ORIGIN': ORIGIN,
                                     'CALIBRE_REMEMBER_DB': str(root / 'sessions.sqlite')})
        env.start()
        self.addCleanup(env.stop)

    def server(self):
        server = LibraryServer(self.library, libraries=(self.library, self.secret_library), userdb=self.userdb, auth=True,
                               auth_mode='basic', ban_after=100, shutdown_timeout=1)
        users = server.handler.router.ctx.user_manager
        for name in ('alice', 'bob'):
            if not users.has_user(name):
                users.add_user(name, 'test-password')
        return server

    def request(self, server, path, cookies=None, method='GET', form=None, body=None, headers=None):
        headers = {'Host': 'remember.test', **(headers or {})}
        if cookies:
            headers['Cookie'] = '; '.join(f'{name}={value}' for name, value in cookies.items())
        if form is not None:
            body = urlencode(form).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        conn = server.connect()
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            response_headers = response.getheaders()
            content = response.read()
            attributes = {}
            for key, value in response_headers:
                if key.lower() == 'set-cookie':
                    for name, morsel in SimpleCookie(value).items():
                        attributes[name] = morsel
                        if cookies is not None:
                            if morsel['max-age'] == '0':
                                cookies.pop(name, None)
                            else:
                                cookies[name] = morsel.value
            return response.status, dict(response_headers), content, attributes
        finally:
            conn.close()

    def login(self, server, mode='30days', username='alice', password='test-password'):
        cookies = {}
        status, headers, body, _ = self.request(server, '/auth/login', cookies)
        self.assertEqual(status, 200)
        self.assertIn(b'Until I sign out', body)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        csrf = re.search(rb'name="_csrf" value="([a-f0-9]+)"', body).group(1).decode()
        status, headers, body, attributes = self.request(server, '/auth/login', cookies, 'POST', form={
            '_csrf': csrf, 'username': username, 'password': password, 'duration': mode,
        }, headers={'Origin': ORIGIN})
        self.assertEqual(status, 303, body)
        self.assertEqual(headers['Location'], '/')
        self.assertIn(SESSION, cookies)
        self.assertIn(CSRF, cookies)
        return cookies, attributes

    def test_login_modes_and_identity(self):
        with self.server() as server:
            status, headers, body, _ = self.request(server, '/', headers={'Accept': 'text/html'})
            self.assertEqual(status, 303)
            self.assertEqual(headers['Location'], ORIGIN + '/auth/login')
            for mode in ('session', '30days', 'permanent'):
                with self.subTest(mode=mode):
                    cookies, attributes = self.login(server, mode)
                    session = attributes[SESSION]
                    self.assertTrue(session['secure'])
                    self.assertTrue(session['httponly'])
                    self.assertEqual(session['samesite'], 'Lax')
                    self.assertEqual(session['path'], '/')
                    self.assertFalse(session['domain'])
                    age = session['max-age']
                    if mode == 'session':
                        self.assertEqual(age, '')
                    elif mode == '30days':
                        self.assertGreater(int(age), 2591900)
                        self.assertLessEqual(int(age), 2592000)
                    else:
                        self.assertEqual(int(age), 34560000)
                    self.assertFalse(attributes[CSRF]['httponly'])
                    for path in ('/', '/interface-data/init', '/opds'):
                        status, headers, body, _ = self.request(server, path, cookies)
                        self.assertEqual(status, 200, body[:100])
                        if path == '/':
                            self.assertEqual(headers.get('Content-Type'), 'text/html; charset=UTF-8')
                        if path == '/interface-data/init':
                            self.assertEqual(json.loads(body)['username'], 'alice')

    def test_sessions_survive_server_restart(self):
        clients = []
        with self.server() as server:
            for mode in ('30days', 'permanent'):
                clients.append(self.login(server, mode)[0])
        with self.server() as server:
            for cookies in clients:
                self.assertEqual(self.request(server, '/interface-data/init', cookies)[0], 200)

    def test_expiry_and_permanent_renewal(self):
        with self.server() as server:
            clients = {mode: self.login(server, mode)[0] for mode in ('session', '30days', 'permanent')}
            future = time.time() + 31 * 86400
            with patch('calibre.srv.remember.time.time', return_value=future):
                for mode in ('session', '30days'):
                    self.assertEqual(self.request(server, '/opds', clients[mode])[0], 401)
                status, _, _, attributes = self.request(server, '/opds', clients['permanent'])
                self.assertEqual(status, 200)
                self.assertEqual(int(attributes[SESSION]['max-age']), 34560000)
            # The browser lifetime is renewed, but the permanent server session
            # itself must not have an implicit 30-day or 400-day expiry.
            with patch('calibre.srv.remember.time.time', return_value=time.time() + 5 * 365 * 86400):
                self.assertEqual(self.request(server, '/opds', clients['permanent'])[0], 200)

    def test_only_token_hashes_are_persisted(self):
        with self.server() as server:
            cookies, _ = self.login(server, 'permanent')
            path = Path(os.environ['CALIBRE_REMEMBER_DB'])
            content = path.read_bytes()
            self.assertNotIn(cookies[SESSION].encode(), content)
            self.assertNotIn(cookies[CSRF].encode(), content)
            self.assertNotIn(b'test-password', content)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_forged_cookies_and_login_csrf_rejected(self):
        with self.server() as server:
            self.assertEqual(self.request(server, '/opds', {SESSION: secrets.token_hex(32)})[0], 401)
            self.assertEqual(self.request(server, '/opds', {SESSION: 'not-a-token'})[0], 401)
            form = {'username': 'alice', 'password': 'test-password', 'duration': 'permanent', '_csrf': '0' * 64}
            self.assertEqual(self.request(server, '/auth/login', {}, 'POST', form=form)[0], 403)
            cookies = {}
            _, _, body, _ = self.request(server, '/auth/login', cookies)
            form['_csrf'] = re.search(rb'name="_csrf" value="([a-f0-9]+)"', body).group(1).decode()
            self.assertEqual(self.request(server, '/auth/login', cookies, 'POST', form=form,
                                          headers={'Origin': 'https://attacker.test'})[0], 403)
            form['password'] = 'wrong-password'
            status, headers, body, _ = self.request(server, '/auth/login', cookies, 'POST', form=form,
                                                   headers={'Origin': ORIGIN})
            self.assertEqual(status, 401)
            self.assertNotIn('WWW-Authenticate', headers)
            self.assertNotIn(SESSION, cookies)
            self.assertIn(b'Invalid username or password', body)

    def test_cookie_writes_require_csrf_and_password_change_revokes(self):
        with self.server() as server:
            first, _ = self.login(server, 'permanent')
            second, _ = self.login(server, 'permanent')
            body = json.dumps({'oldpw': 'test-password', 'newpw': 'new-test-password'}).encode()
            headers = {'Content-Type': 'application/json', 'Origin': ORIGIN}
            self.assertEqual(self.request(server, '/users/change-pw', first, 'POST', body=body, headers=headers)[0], 403)
            self.assertEqual(self.request(server, '/users/change-pw', first, 'POST', body=body,
                                         headers={**headers, 'X-Calibre-CSRF': first[CSRF], 'Origin': 'https://attacker.test'})[0], 403)
            result = self.request(server, '/users/change-pw', first, 'POST', body=body,
                                  headers={**headers, 'X-Calibre-CSRF': first[CSRF]})
            self.assertEqual(result[0], 200, result[2])
            self.assertEqual(self.request(server, '/opds', first)[0], 401)
            self.assertEqual(self.request(server, '/opds', second)[0], 401)
            # Restoring the old password must not resurrect a revoked session.
            basic = 'Basic ' + base64.b64encode(b'alice:new-test-password').decode()
            body = json.dumps({'oldpw': 'new-test-password', 'newpw': 'test-password'}).encode()
            self.assertEqual(self.request(server, '/users/change-pw', method='POST', body=body,
                                         headers={**headers, 'Authorization': basic})[0], 200)
            self.assertEqual(self.request(server, '/opds', second)[0], 401)

    def test_logout_revokes_copied_token_and_logout_all(self):
        with self.server() as server:
            first, _ = self.login(server, 'permanent')
            copied = first.copy()
            second, _ = self.login(server, 'permanent')
            self.assertEqual(self.request(server, '/auth/logout', first, 'POST', form={'_csrf': first[CSRF]})[0], 303)
            self.assertNotIn(SESSION, first)
            self.assertEqual(self.request(server, '/opds', copied)[0], 401)
            self.assertEqual(self.request(server, '/opds', second)[0], 200)
            third, _ = self.login(server, '30days')
            self.assertEqual(self.request(server, '/auth/logout-all', second, 'POST', form={'_csrf': second[CSRF]})[0], 303)
            self.assertEqual(self.request(server, '/opds', third)[0], 401)

    def test_session_management_respects_ownership(self):
        with self.server() as server:
            alice, _ = self.login(server, 'permanent')
            bob, _ = self.login(server, 'permanent', username='bob')
            status, _, body, _ = self.request(server, '/auth/sessions', alice)
            self.assertEqual(status, 200)
            self.assertNotIn(alice[SESSION].encode(), body)
            alice_id = re.search(rb'name="session_id" value="([a-f0-9]{24})"', body).group(1).decode()
            self.assertEqual(self.request(server, '/auth/revoke', bob, 'POST', form={'_csrf': bob[CSRF], 'session_id': alice_id})[0], 303)
            self.assertEqual(self.request(server, '/opds', alice)[0], 200)
            self.assertEqual(self.request(server, '/auth/revoke', alice, 'POST', form={'_csrf': alice[CSRF], 'session_id': alice_id})[0], 303)
            self.assertEqual(self.request(server, '/opds', alice)[0], 401)

    def test_basic_auth_remains_independent(self):
        with self.server() as server:
            basic = 'Basic ' + base64.b64encode(b'alice:test-password').decode()
            status, _, _, attributes = self.request(server, '/opds', headers={'Authorization': basic})
            self.assertEqual(status, 200)
            self.assertNotIn(SESSION, attributes)
            alice, _ = self.login(server)
            wrong = 'Basic ' + base64.b64encode(b'alice:wrong-password').decode()
            self.assertEqual(self.request(server, '/opds', alice, headers={'Authorization': wrong})[0], 401)

    def test_library_and_write_permissions_are_preserved(self):
        with self.server() as server:
            users = server.handler.router.ctx.user_manager
            users.update_user_restrictions('bob', {'allowed_library_names': ['library']})
            users.set_readonly('bob', True)
            cookies, _ = self.login(server, username='bob')
            status, _, body, _ = self.request(server, '/interface-data/init', cookies)
            self.assertEqual(status, 200)
            self.assertEqual(set(json.loads(body)['library_map']), {'library'})
            self.assertEqual(self.request(server, '/cdb/delete-books/999/library', cookies, method='POST',
                                         headers={'X-Calibre-CSRF': cookies[CSRF]})[0], 403)
            # Dynamic command API, write endpoints, and GET-capable mutations also require CSRF.
            alice, _ = self.login(server)
            self.assertEqual(self.request(server, '/cdb/delete-books/999/library', alice, method='POST')[0], 403)
            self.assertEqual(self.request(server, '/cdb/cmd/remove/0', alice, method='POST')[0], 403)
            self.assertEqual(self.request(server, '/interface-data/set-session-data', alice)[0], 403)

    def test_gui_password_change_and_user_removal_revoke(self):
        with self.server() as server:
            users = server.handler.router.ctx.user_manager
            cookies, _ = self.login(server, 'permanent')
            data = users.user_data
            data['alice']['pw'] = 'changed-in-gui'
            users.user_data = data
            self.assertEqual(self.request(server, '/opds', cookies)[0], 401)
            cookies, _ = self.login(server, 'permanent', password='changed-in-gui')
            users.remove_user('alice')
            users.add_user('alice', 'changed-in-gui')
            self.assertEqual(self.request(server, '/opds', cookies)[0], 401)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RememberTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
