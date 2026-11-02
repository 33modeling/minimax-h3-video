"""Input UX, real media metadata and atomic bounded copies; no HTTP servers."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).parents[1]/'src'))
from h3video import cli
from h3video.client import H3Error, stage_input
from h3video.media_input import describe_input, inspect_input, normalize_input


def png():
    def chunk(kind, data):
        return struct.pack('!I', len(data))+kind+data+struct.pack('!I', zlib.crc32(kind+data))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('!IIBBBBB', 2, 2, 8, 2, 0, 0, 0))+chunk(b'IDAT', zlib.compress((b'\x00'+b'\x00\xff\x00'*2)*2))+chunk(b'IEND', b'')


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);self.photo = self.root/'인물 사진.png';self.photo.write_bytes(png())
        env = {k:v for k,v in os.environ.items() if not k.startswith('H3_')}
        env['XDG_CONFIG_HOME'] = str(self.root/'config')
        self.environment = patch.dict(os.environ, env, clear=True);self.environment.start();self.addCleanup(self.environment.stop)

    def run_cli(self, *args):
        output, errors = io.StringIO(), io.StringIO();code = 0
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), patch('socket.socket.listen', side_effect=AssertionError('server started')), patch.object(cli.H3Client, '_request', side_effect=AssertionError('unexpected network')):
            try:cli.main(list(args))
            except SystemExit as error:code=error.code if isinstance(error.code,int) else 1;errors.write(str(error.code))
        return code, output.getvalue(), errors.getvalue()

    def test_single_auto_input_is_a_reference_not_a_keyframe(self):
        code, out, err = self.run_cli('gen','인물이 걷는다','-i',str(self.photo),'--dry-run','--json')
        self.assertEqual(code,0,err);plan=json.loads(out)
        self.assertEqual(plan['task'],'ref2va');self.assertEqual(plan['requests'][0]['conditions'][0]['role'],'reference')
        self.assertEqual(plan['inputs'][0]['bytes'],self.photo.stat().st_size)

    def test_auto_and_explicit_inputs_keep_argument_order(self):
        a=cli.build_parser().parse_args(['gen','움직임','--input','https://example.test/a.PNG?x=1','--video','https://example.test/m.mp4','--image','https://example.test/b.jpg','--input','https://example.test/c.png'])
        self.assertEqual([(r['type'],r['path'].split('/')[-1]) for r in cli.refs_of(a)], [('image','a.PNG?x=1'),('video','m.mp4'),('image','b.jpg'),('image','c.png')])

    def test_keyframe_paths_with_quotes_and_spaces(self):
        code,out,err=self.run_cli('gen','고개 돌리기','--first',f'"{self.photo}"','--dry-run','--json')
        self.assertEqual(code,0,err);plan=json.loads(out);self.assertEqual(plan['task'],'fl2va')
        self.assertEqual(plan['requests'][0]['conditions'][0]['frame_index'],0)
        self.assertIn('%20',plan['requests'][0]['conditions'][0]['uri'])

    def test_shell_escaped_dragged_path_is_accepted_when_it_exists(self):
        self.assertEqual(normalize_input(str(self.photo).replace(' ',r'\ ')),str(self.photo))

    def test_missing_file_suggests_the_existing_name(self):
        code,out,err=self.run_cli('gen','움직임','--input',str(self.root/'인물 사잔.png'),'--dry-run')
        self.assertEqual(code,1);self.assertIn('비슷한 파일',err);self.assertIn(self.photo.name,err)

    def test_mixed_keyframe_and_reference_modes_fail_before_submission(self):
        code,_,err=self.run_cli('gen','움직임','--first',str(self.photo),'-i',str(self.photo),'--dry-run')
        self.assertEqual(code,1);self.assertIn('같이 쓸 수 없다',err)

    def test_typed_input_rejects_a_known_wrong_media_kind(self):
        with self.assertRaisesRegex(H3Error,'image 입력에 video'):
            describe_input('https://example.test/movie.mp4','image')

    def test_audio_only_reference_is_rejected_before_the_gpu(self):
        code,_,err=self.run_cli('gen','참고','-i','https://example.test/music.wav','--dry-run')
        self.assertEqual(code,1);self.assertIn('이미지 또는 영상',err)

    def test_auto_input_still_enforces_reference_count_limits(self):
        args=['gen','참고','--dry-run']
        for i in range(10):args+=['-i',f'https://example.test/{i}.png']
        code,_,err=self.run_cli(*args);self.assertEqual(code,1);self.assertIn('최대 9',err)

    def test_unknown_auto_type_explains_the_explicit_options(self):
        code,_,err=self.run_cli('ref','참고','--input','https://example.test/download','--dry-run')
        self.assertEqual(code,1);self.assertIn('--image / --video / --audio',err)

    def test_json_requires_dry_run_and_never_submits(self):
        code,out,err=self.run_cli('gen','만들기','--json')
        self.assertEqual(code,1);self.assertIn('--dry-run',err);self.assertEqual(out,'')

    def test_preview_records_shared_inbox_without_creating_it(self):
        inbox=self.root/'shared'
        code,out,err=self.run_cli('gen','참고','-i',str(self.photo),'--inbox-dir',str(inbox),'--dry-run','--json')
        self.assertEqual(code,0,err);plan=json.loads(out);self.assertEqual(plan['inbox_dir'],str(inbox));self.assertFalse(inbox.exists())

    def test_remote_inputs_are_explicitly_unverified_and_never_fetched(self):
        url='https://example.test/image.png?token='+'a'*5000
        code,out,err=self.run_cli('inspect',url,'file:///shared/server.png','--json')
        self.assertEqual(code,0,err);result=json.loads(out)
        self.assertTrue(all(r['verification']=='remote-unverified' and r['bytes'] is None for r in result['inputs']))

    def test_file_uri_with_remote_authority_is_rejected(self):
        with self.assertRaisesRegex(H3Error,'file:///'):
            describe_input('file://other-server/tmp/a.png')

    def test_empty_files_are_rejected(self):
        empty=self.root/'empty.png';empty.touch()
        with self.assertRaisesRegex(H3Error,'비어'):
            describe_input(str(empty))

    @unittest.skipUnless(shutil.which('ffprobe'),'ffprobe required for actual image metadata')
    def test_actual_png_metadata_and_mixed_inspection_results(self):
        code,out,err=self.run_cli('inspect',str(self.photo),str(self.root/'missing.mp4'),'--json')
        self.assertEqual(code,1,err);result=json.loads(out);self.assertFalse(result['ok'])
        self.assertEqual((result['inputs'][0]['width'],result['inputs'][0]['height']),(2,2))
        self.assertEqual(result['inputs'][0]['metadata_status'],'verified');self.assertFalse(result['inputs'][1]['ok'])

    @unittest.skipUnless(shutil.which('ffprobe'),'ffprobe required')
    def test_corrupt_media_is_reported_instead_of_claimed_valid(self):
        broken=self.root/'broken.mp4';broken.write_bytes(b'not a video')
        code,out,_=self.run_cli('inspect',str(broken),'--json');self.assertEqual(code,1);self.assertFalse(json.loads(out)['inputs'][0]['ok'])

    def test_missing_probe_keeps_metadata_explicitly_unmeasured(self):
        with patch('h3video.media_input.shutil.which',return_value=None):
            result=inspect_input(str(self.photo))
        self.assertEqual(result['metadata_status'],'unavailable');self.assertNotIn('width',result);self.assertNotIn('duration_seconds',result)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg tools required')
    def test_real_video_metadata_and_a_renamed_image_extension(self):
        video=self.root/'원본 영상.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=32x24:r=10','-t','2','-c:v','mpeg4',str(video)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        result=inspect_input(str(video));self.assertEqual((result['width'],result['height']),(32,24));self.assertAlmostEqual(result['duration_seconds'],2,places=2)
        renamed=self.root/'false.png';shutil.copyfile(video,renamed)
        with self.assertRaisesRegex(H3Error,'확장자와 실제'):
            inspect_input(str(renamed))

    def test_staging_streams_large_inputs_and_reuses_the_same_content_name(self):
        video=self.root/'large.mp4';video.write_bytes(b'12345678'*400000);inbox=self.root/'inbox'
        expected=hashlib.sha1(video.read_bytes()).hexdigest()[:12]+'-'+video.name
        with patch.object(Path,'read_bytes',side_effect=AssertionError('whole input read into memory')):
            first=stage_input(video,inbox);second=stage_input(video,inbox)
        self.assertEqual(first,second);self.assertEqual((inbox/expected).stat().st_size,video.stat().st_size)
        self.assertEqual((inbox/expected).read_bytes(),video.read_bytes());self.assertEqual(list(inbox.glob('.h3-input-*')),[])

    def test_failed_staging_never_publishes_a_partial_input(self):
        inbox=self.root/'inbox'
        def fail(source,destination,**kwargs):destination.write(b'partial');raise OSError('disk full')
        with patch('h3video.client.shutil.copyfileobj',side_effect=fail),self.assertRaises(OSError):
            stage_input(self.photo,inbox)
        self.assertEqual(list(inbox.iterdir()),[]);self.assertEqual(self.photo.read_bytes(),png())

    def test_input_modified_during_copy_is_not_published(self):
        inbox=self.root/'inbox';copy=shutil.copyfileobj
        def modified(source,destination,**kwargs):
            copy(source,destination,**kwargs)
            with self.photo.open('ab')as stream:stream.write(b'changed')
        with patch('h3video.client.shutil.copyfileobj',side_effect=modified),self.assertRaisesRegex(H3Error,'복사 중 바뀌'):
            stage_input(self.photo,inbox)
        self.assertEqual(list(inbox.iterdir()),[])

    def test_incomplete_cached_input_is_repaired(self):
        inbox=self.root/'inbox';inbox.mkdir();name=hashlib.sha1(self.photo.read_bytes()).hexdigest()[:12]+'-'+self.photo.name
        (inbox/name).write_bytes(b'partial')
        stage_input(self.photo,inbox)
        self.assertEqual((inbox/name).read_bytes(),self.photo.read_bytes())


if __name__=='__main__':unittest.main()
