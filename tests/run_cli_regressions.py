"""Existing CLI/client/web regression cases through real handlers, without servers."""
import importlib
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from inmemory_http import transport

EXCLUDE = {
 ('test_cli','CliTest','test_stdin_prompt'): 'Child process cannot share an in-memory parent transport; stdin dry-run is covered separately',
 ('test_cli','CliTest','test_ctrl_c_marks_job_and_prints_fetch_hint'): 'Requires an actual child HTTP endpoint; interrupted metadata is covered separately',
 ('test_cli_ux','UxLiveTest','test_ctrl_c_keeps_job_record'): 'Child process transport not shared',
}

def flatten(suite):
 for item in suite:
  if isinstance(item,unittest.TestSuite):yield from flatten(item)
  else:yield item

with transport():
 suite=unittest.TestSuite();excluded=[]
 for name in ['test_client','test_cli','test_cli_ux','test_qa_web_cli','test_stop','test_recovery','test_resume_edited_candidate','test_output','test_cli_inputs','test_cli_examples']:
  module=importlib.import_module(name)
  if hasattr(module,'dead_url'):module.dead_url=lambda:'http://127.0.0.1:1'
  for case in flatten(unittest.defaultTestLoader.loadTestsFromModule(module)):
   key=(name,type(case).__name__,case._testMethodName)
   if key in EXCLUDE or ('ctrl_c' in case._testMethodName.lower()):
    excluded.append({'test':'.'.join(key),'reason':EXCLUDE.get(key,'Child process does not share the in-memory HTTP registry')});continue
   suite.addTest(case)
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 if len(sys.argv)>1:Path(sys.argv[1]).write_text(json.dumps({'testsRun':result.testsRun,'successful':result.wasSuccessful(),'excluded':excluded,'realServersStarted':0,'GPUInferenceMeasured':False},indent=2)+'\n')
 sys.exit(0 if result.wasSuccessful()else 1)
