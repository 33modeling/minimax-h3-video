"""Keep the published CLI recipes executable against the actual request builder."""
import contextlib
from html.parser import HTMLParser
import io
from pathlib import Path
import shlex
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from h3video import cli


class Recipes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current = None
        self.in_command = False
        self.rows = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'article' and 'data-cli-example' in attrs:
            self.current = attrs['id']
        if tag == 'pre' and 'data-cli-command' in attrs:
            self.in_command = True
            self.rows[self.current] = ''

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.in_command = False

    def handle_data(self, data):
        if self.in_command:
            self.rows[self.current] += data


class CLIExamples(unittest.TestCase):
    def test_published_commands_build_requests_without_submission(self):
        source = Path(__file__).parents[1] / 'src/h3video/studio/h3-cli.html'
        recipes = Recipes()
        recipes.feed(source.read_text())
        self.assertEqual(len(recipes.rows), 20)
        with tempfile.TemporaryDirectory(prefix='h3-cli-docs-') as folder:
            root = Path(folder)
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=blue:s=96x64:r=5:d=2', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p', str(root/'sample.mp4')], check=True)
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(root/'sample.mp4'),
                            '-frames:v', '1', str(root/'1.png')], check=True)
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'sine=frequency=440:duration=2', str(root/'voice.wav')], check=True)
            for name in ['start.png', 'end.png', '2.png', 'person.png', 'product.png', 'room.png', 'style.png']:
                (root/name).write_bytes((root/'1.png').read_bytes())
            for name in ['motion.mp4', 'camera.mp4']:
                (root/name).write_bytes((root/'sample.mp4').read_bytes())
            (root/'prompt.txt').write_text('자연광 아래 컵을 바라보며 카메라가 천천히 전진한다.')
            for name, command in recipes.rows.items():
                with self.subTest(recipe=name):
                    syntax = subprocess.run(['bash', '-n'], input=command, text=True, capture_output=True)
                    self.assertEqual(syntax.returncode, 0, syntax.stderr)
                    argv = shlex.split(command.replace('\\\n', ' '))
                    self.assertEqual(argv.pop(0), 'h3video')
                    args = cli.build_parser().parse_args(argv)
                    for key in ['first', 'last', 'prompt_file']:
                        value = getattr(args, key, None)
                        if value:
                            setattr(args, key, str(root/value))
                    for kind in ['image', 'video', 'audio']:
                        setattr(args, kind, [str(root/p) for p in getattr(args, kind)])
                    if hasattr(args, '_media_order'):
                        args._media_order = [(kind, str(root/path)) for kind, path in args._media_order]
                    args.dry_run = True
                    output = io.StringIO()
                    # An accidental real submission/network access must fail this check.
                    with patch.object(cli, 'run_jobs', side_effect=AssertionError('Submission forbidden')), \
                         patch.object(socket, 'create_connection', side_effect=AssertionError('Network forbidden')), \
                         contextlib.redirect_stdout(output):
                        args.fn(args)
                    self.assertIn('서버에 보내지 않았다', output.getvalue())
                    refs = cli.refs_of(args)
                    job = cli.job_from_args(args, cli.read_prompt(args), refs)
                    requests = cli.validate_job(job)
                    if refs:
                        self.assertTrue(all(r.task == 'ref2va' for r in requests))
                    if name == 'cli-first-last':
                        self.assertEqual(len(requests), 1)
                        self.assertEqual(requests[0].task, 'fl2va')
                        self.assertEqual(job.first_image, str(root/'start.png'))
                        self.assertEqual(job.last_image, str(root/'end.png'))
                    if name == 'cli-long':
                        self.assertEqual([r.duration_seconds for r in requests], [10, 10, 10])
                    if name == 'cli-face':
                        self.assertEqual([r['type'] for r in job.refs], ['image', 'video'])
                        self.assertEqual(args.out, 'face-change.mp4')
            mixed = cli.build_parser().parse_args(['gen', 'test', '--first', str(root/'start.png'),
                                                   '--image', str(root/'1.png'), '--dry-run'])
            with self.assertRaisesRegex(cli.H3Error, '같이 쓸 수 없다'):
                mixed.fn(mixed)


if __name__ == '__main__':
    unittest.main()
