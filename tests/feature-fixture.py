"""Generate real project/view schemas and media for a listener-free UI regression."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from h3video.studio import VideoStudio

out=Path(sys.argv[1]);out.mkdir(exist_ok=True)
root=out/'storage';root.mkdir(exist_ok=True)
video=root/'test-video.mp4'
subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=96x64:rate=4',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','1','-c:v','libx264',
                '-pix_fmt','yuv420p','-c:a','aac',str(video)],check=True)
app=SimpleNamespace(store=SimpleNamespace(root=root,get=lambda name:None),endpoint='http://generation.invalid',
                    file_url=lambda name:'/fixture/test-video.mp4')
studio=VideoStudio(app)
try:
    empty=studio.create({'title':'새 교정 프로젝트'})
    uploaded=studio.create({'title':'보존할 기존 프로젝트','clips':[{'output':str(video)}]})
    (out/'fixture.json').write_text(json.dumps(dict(empty=empty,uploaded=uploaded,video=str(video)),ensure_ascii=False))
finally:
    studio.executor.shutdown(wait=True)
