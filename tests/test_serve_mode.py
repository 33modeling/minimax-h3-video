"""Actual shell argument forwarding, with fake interpreters and no port bind."""
import json,os,subprocess,sys,tempfile,textwrap,unittest
from pathlib import Path
ROOT=Path(__file__).parents[1]
class ServeModeTest(unittest.TestCase):
 def test_speed_and_memory_reach_diffusers_and_invalid_mode_is_rejected(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);(root/'scripts').mkdir();(root/'venv/bin').mkdir(parents=True);(root/'logs').mkdir();(root/'scripts/serve.sh').write_bytes((ROOT/'scripts/serve.sh').read_bytes())
   cfg=dict(H3_ENGINE='diffusers',VENV=root/'venv',H3_DIFFUSERS_DIR=root/'model',H3_PORT_FL2VA=30010,H3_PORT_REF2VA=30011,H3_LOG_DIR=root/'logs',H3_HOST='127.0.0.1',STORAGE_ROOT=root/'storage',H3_NUM_GPUS=4)
   (root/'scripts/cluster_env.sh').write_text('\n'.join(f'export {k}="{v}"'for k,v in cfg.items())+'\n')
   fake=root/'venv/bin/python';fake.write_text('#!'+sys.executable+'\n'+textwrap.dedent('''\
    import os,sys,json
    from pathlib import Path
    args=sys.argv[1:]
    if args and args[0]=='-':sys.stdin.read();sys.exit(1)
    if args and args[0].endswith('check_diffusers_model.py'):sys.exit(0)
    if args[:2]==['-m','h3video.dserver']:Path(os.environ['MODE_TRACE']).write_text(json.dumps(args));sys.exit(0)
    raise AssertionError(args)
    '''));fake.chmod(0o755);(root/'venv/bin/python3').symlink_to('python')
   for mode in ['speed','memory']:
    trace=root/(mode+'.json');env={**os.environ,'PATH':str(root/'venv/bin')+':'+os.environ['PATH'],'MODE_TRACE':str(trace)}
    result=subprocess.run(['bash',str(root/'scripts/serve.sh'),'ref2va','--gpus','0,1,2,3','--mode',mode],env=env,capture_output=True,text=True,timeout=10)
    self.assertEqual(result.returncode,0,result.stderr);args=json.loads(trace.read_text());self.assertEqual(args[args.index('--performance-mode')+1],mode)
   result=subprocess.run(['bash',str(root/'scripts/serve.sh'),'ref2va','--mode','invalid'],env=env,capture_output=True,text=True,timeout=10)
   self.assertEqual(result.returncode,2)
