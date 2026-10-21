import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from h3video.web import make_handler, parse_origins


class HostMigrationTest(unittest.TestCase):
    def test_existing_launch_settings_allow_the_new_host_without_opening_other_origins(self):
        origins = parse_origins('https://33modeling.pages.dev')
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(None, origins))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close()))
        url = f'http://127.0.0.1:{server.server_port}/api/feed'
        for origin in ['https://33modeling.pages.dev', 'https://7modeling-92i.pages.dev']:
            request = urllib.request.Request(url, method='OPTIONS', headers={'Origin': origin, 'Access-Control-Request-Private-Network': 'true'})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 204)
                self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), origin)
                self.assertEqual(response.headers.get('Access-Control-Allow-Private-Network'), 'true')
        with urllib.request.urlopen(urllib.request.Request(url, method='OPTIONS', headers={'Origin': 'https://unrelated.example'})) as response:
            self.assertIsNone(response.headers.get('Access-Control-Allow-Origin'))
        self.assertEqual(parse_origins(None), [])
        self.assertEqual(parse_origins('http://localhost:4173'), ['http://localhost:4173'])
