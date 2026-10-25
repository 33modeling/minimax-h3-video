"""2026-10-26 영상 편집실 점검에서 찾은 버그의 회귀 테스트(자막 파일·권한 없는 공유 폴더)."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from h3video.web import App
from h3video.studio import caption_file


class CaptionFileTest(unittest.TestCase):
    def test_blank_lines_are_not_written_as_cues(self):
        srt = caption_file([dict(start=0, end=1, text=''), dict(start=1, end=2, text='첫 줄\n\n둘째 줄\r\n'),
                            dict(start=2, end=3, text='   '), dict(start=3, end=4, text='끝 --> 화살표')])
        self.assertEqual(srt, '1\n00:00:01,000 --> 00:00:02,000\n첫 줄\n둘째 줄\n\n2\n00:00:03,000 --> 00:00:04,000\n끝 → 화살표\n\n')
        vtt = caption_file([dict(start=0, end=1.5, text='')], True)
        self.assertEqual(vtt, 'WEBVTT\n\n')


@unittest.skipIf(os.geteuid() == 0, 'root 는 권한 없는 폴더도 읽는다')
class CapabilitiesPermissionTest(unittest.TestCase):
    def test_unreadable_shared_studio_does_not_break_the_editor(self):
        with tempfile.TemporaryDirectory() as temporary:
            locked = Path(temporary) / 'locked'
            (locked / '.venv-studio/bin').mkdir(parents=True)
            (locked / '.venv-studio/bin/python').write_text('')
            app = App('http://127.0.0.1:9', 'http://127.0.0.1:9', Path(temporary) / 'outputs', None)
            os.chmod(locked, 0)
            try:
                with mock.patch.dict(os.environ, {'H3_SHARED_STUDIO': str(locked), 'H3_STUDIO_TOOLS': str(locked / 'tools'),
                                                  'STUDIO_UPSCALER_DIR': str(locked / 'upscaler')}):
                    caps = app.studio.capabilities()
            finally:
                os.chmod(locked, 0o755)
                app.studio.close()
                app.motion.close()
            self.assertIs(caps['faceInspection'], False)
            self.assertIs(caps['transcription'], False)
            self.assertIs(caps['aiUpscale'], False)


if __name__ == '__main__':
    unittest.main()
