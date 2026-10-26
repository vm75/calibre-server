"""Run with calibre-debug inside the candidate image; uses no production data."""
import base64
import tempfile
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch
from urllib.request import HTTPBasicAuthHandler, HTTPDigestAuthHandler, build_opener

from calibre.db.legacy import create_backend
from calibre.srv.tests.base import LibraryServer


class AuthenticationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = str(Path(self.temp.name) / 'library')
        create_backend(self.library).close()

    def server(self, **opts):
        server = LibraryServer(self.library, auth=True, auth_mode='basic',
                               ban_after=100, **opts)
        server.handler.router.ctx.user_manager.add_user('patch-test', 'test-password')
        return server

    def request(self, server, path, credentials=None, method='GET'):
        headers = {}
        if credentials is not None:
            headers['Authorization'] = 'Basic ' + base64.b64encode(credentials.encode()).decode()
        conn = server.connect()
        try:
            conn.request(method, path, headers=headers)
            response = conn.getresponse()
            return response.status, response.getheader('WWW-Authenticate'), response.read()
        finally:
            conn.close()

    def test_basic_challenges_and_success(self):
        with self.server() as server:
            for path in ('/', '/interface-data/init', '/opds'):
                for credentials in (None, ':', 'patch-test:', ':test-password', 'patch-test:wrong'):
                    with self.subTest(path=path, credentials=credentials):
                        status, challenge, body = self.request(server, path, credentials)
                        self.assertEqual(status, 401)
                        self.assertTrue(challenge.startswith('Basic realm='))
                status, challenge, body = self.request(server, path, 'patch-test:test-password')
                self.assertEqual(status, 200, body[:200])
                self.assertIsNone(challenge)
                self.assertTrue(body)
            self.assertEqual(self.request(server, '/', method='HEAD')[0], 401)
            # Browser-style retry after a native HTTP Basic challenge.
            url = f'http://localhost:{server.address[1]}/'
            handler = HTTPBasicAuthHandler()
            handler.add_password(server.handler.auth_controller.realm, url, 'patch-test', 'test-password')
            with build_opener(handler).open(url) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b'<html', response.read().lower())

    def test_auth_disabled(self):
        with LibraryServer(self.library, auth=False) as server:
            for path in ('/', '/interface-data/init', '/opds'):
                self.assertEqual(self.request(server, path)[0], 200)

    def test_digest_still_works(self):
        with LibraryServer(self.library, auth=True, auth_mode='digest') as server:
            server.handler.router.ctx.user_manager.add_user('patch-test', 'test-password')
            status, challenge, _ = self.request(server, '/')
            self.assertEqual(status, 401)
            self.assertTrue(challenge.startswith('Digest realm='))
            url = f'http://localhost:{server.address[1]}/'
            handler = HTTPDigestAuthHandler()
            handler.add_password(server.handler.auth_controller.realm, url, 'patch-test', 'test-password')
            with build_opener(handler).open(url) as response:
                self.assertEqual(response.status, 200)

    def test_embedded_server_starts(self):
        from calibre.constants import is_running_from_develop
        from calibre.srv.embedded import Server
        from calibre.srv.opts import Options

        self.assertFalse(is_running_from_develop, 'Packaged image must use compiled release assets')
        opts = Options(auth=True, auth_mode='basic', listen_on='127.0.0.1',
                       port=0, userdb=':memory:', use_bonjour=False,
                       shutdown_timeout=1)
        with patch('calibre.srv.embedded.server_config', return_value=opts):
            server = Server((self.library,), lambda *args: None)
        server.user_manager.add_user('patch-test', 'test-password')
        try:
            server.start()
            deadline = time.monotonic() + 10
            while not server.exception and not server.loop.ready and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIsNone(server.exception)
            self.assertTrue(server.loop.ready, 'Embedded server did not become ready')
            conn = HTTPConnection('127.0.0.1', server.loop.bound_address[1], timeout=5)
            try:
                conn.request('GET', '/')
                response = conn.getresponse()
                self.assertEqual(response.status, 401)
                self.assertTrue(response.getheader('WWW-Authenticate').startswith('Basic '))
                response.read()
                credentials = base64.b64encode(b'patch-test:test-password').decode()
                conn.request('GET', '/', headers={'Authorization': 'Basic ' + credentials})
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertIn(b'<html', response.read().lower())
            finally:
                conn.close()
        finally:
            server.exit()


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AuthenticationTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
