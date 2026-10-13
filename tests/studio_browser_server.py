"""Isolated real editor API with a mock generation endpoint for browser checks."""
import json
from pathlib import Path
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import mock_server
from h3video.web import App,make_handler

directory=Path(sys.argv[1]);directory.mkdir(exist_ok=True)
model,state,endpoint=mock_server.start(steps=2)
app=App(endpoint,endpoint,directory/'outputs',None,poll=.01)
file=directory/'small.mp4'
subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i','color=c=0x507b83:s=96x64:r=4',
 '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(file)],check=True)
image=directory/'scene.png'
subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i','color=c=0xdaaa66:s=96x64','-frames:v','1',str(image)],check=True)
project=app.studio.create({'title':'영상 작업실 검증','clips':[{'id':'first','label':'첫 장면','prompt':'a moving scene','seconds':1},{'id':'second','label':'둘째 장면','prompt':'a second scene','seconds':1}]})
for clip in project['clips']:
 app.studio.upload(project['id'],{'clip':clip['id'],'kind':'video'},file.name,file.read_bytes())
 app.studio.upload(project['id'],{'clip':clip['id'],'kind':'image'},image.name,image.read_bytes())
app.studio.update(project['id'],{'delivery':{'shortEdge':64}})
server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app,{'*'}))
print(json.dumps({'url':f'http://127.0.0.1:{server.server_address[1]}','project':project['id'],'video':str(file),'image':str(image)}),flush=True)
try:server.serve_forever()
finally:app.studio.close();server.server_close();model.shutdown();model.server_close()
