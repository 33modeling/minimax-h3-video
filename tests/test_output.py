"""Inspect actual exported MP4 streams, duration, decoding and atomic failure behavior."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from h3video.jobs import concat_videos
from h3video.client import H3Error

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg + ffprobe required')
class OutputTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="영상 ' 출력-")
        self.root = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def make(self, name, size='320x180', sound=True, color='red', fps=24):
        p=self.root/name
        args=['ffmpeg','-y','-v','error','-f','lavfi','-i',f'color=c={color}:s={size}:r={fps}:d=1']
        if sound: args += ['-f','lavfi','-i','sine=frequency=440:sample_rate=44100:duration=1','-shortest','-c:a','aac']
        subprocess.run(args+['-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',str(p)],check=True)
        return p
    def info(self,p):
        return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)]))
    def check_output(self,p,w,h,duration):
        j=self.info(p);v=next(x for x in j['streams'] if x['codec_type']=='video')
        self.assertEqual((v['codec_name'],v['width'],v['height'],v['pix_fmt']),('h264',w,h,'yuv420p'))
        self.assertAlmostEqual(float(j['format']['duration']),duration,delta=.25)
        subprocess.run(['ffmpeg','-v','error','-i',str(p),'-f','null','-'],check=True,capture_output=True)
        data=p.read_bytes();self.assertLess(data.index(b'moov'),data.index(b'mdat'),'faststart for immediate browser playback')
        self.assertFalse(list(self.root.glob('*.concat.txt')))
    def test_korean_quotes_and_spaces_in_filenames(self):
        a=self.make("첫 장면 ' 하나.mp4");b=self.make('둘째 장면.mp4',color='blue');out=self.root/'한 편.mp4'
        concat_videos([a,b],out);self.check_output(out,320,180,2)
    def test_mixed_orientation_frame_rate_and_missing_audio(self):
        a=self.make('landscape.mp4');b=self.make('portrait.mp4','180x320',False,'blue',30)
        out=concat_videos([a,b],self.root/'mix.mp4');self.check_output(out,320,180,2)
        self.assertTrue(any(s['codec_type']=='audio' for s in self.info(out)['streams']))
        # The portrait is fitted, with side bars, rather than cropping away its top/bottom.
        frame=subprocess.check_output(['ffmpeg','-v','error','-ss','1.5','-i',str(out),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'])
        pixel=lambda x,y:frame[(y*320+x)*3:(y*320+x)*3+3]
        self.assertLess(max(pixel(5,90)),10);self.assertGreater(pixel(160,10)[2],200);self.assertGreater(pixel(160,170)[2],200)
    def test_all_silent_and_single_scene(self):
        a=self.make('silent.mp4',sound=False);out=concat_videos([a],self.root/'one.mp4');self.check_output(out,320,180,1)
        self.assertFalse(any(s['codec_type']=='audio' for s in self.info(out)['streams']))
    def test_bad_input_keeps_previous_output(self):
        out=self.root/'saved.mp4';out.write_bytes(b'previous-output');bad=self.root/'bad.mp4';bad.write_bytes(b'not-a-video')
        for parts in [[],[bad],[self.root/'missing.mp4']]:
            with self.assertRaises(H3Error):concat_videos(parts,out)
            self.assertEqual(out.read_bytes(),b'previous-output')
        self.assertFalse(list(self.root.glob('.*.mp4')))
