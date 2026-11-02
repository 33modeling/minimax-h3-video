import email.message
import hashlib
import unittest
from unittest.mock import patch
from pathlib import Path
from h3video.web import make_handler

class HelpStaticTest(unittest.TestCase):
    def test_existing_static_handler_serves_packaged_guide_without_server(self):
        with patch('socket.socket', side_effect=AssertionError('No listeners permitted')):
            handler = make_handler(None, []).__new__(make_handler(None, []))
            handler.path = '/studio/h3-cli.html'
            handler.headers = email.message.Message()
            served = []
            handler._send_file = lambda file, *a, **k: served.append(Path(file))
            handler._do_get()
            self.assertEqual(len(served), 1)
            text = served[0].read_text()
            self.assertIn('H100 4장', text)
            self.assertIn('scripts/provision.sh', text)
            self.assertIn('scripts/up.sh --ref --gpus 0,1 --ref-gpus 2,3', text)
            self.assertEqual(text.count('class="h3-section"'), 38)
            self.assertEqual(text.count('data-guide-feature='), 22)
            self.assertIn('../?feature=retouch', text)
            self.assertIn('프레임 보정 후 AI 2배·4배 확대', text)

    def test_guide_assets_and_package_metadata_are_complete(self):
        root = Path(__file__).resolve().parents[1]
        source = root / 'src/h3video'
        for name in ['h3-cli.html','h3-guide.css','h3-guide.js','features.js','feature-hub.js','feature-hub.css']:
            self.assertTrue((source / 'studio' / name).is_file())
        self.assertIn('studio/*.html', (root / 'pyproject.toml').read_text())
        self.assertIn('class="h3-guide-menu"', (source / 'ui.html').read_text())
        self.assertIn('./studio/h3-cli.html', (source / 'ui.html').read_text())

if __name__ == '__main__':
    unittest.main()
