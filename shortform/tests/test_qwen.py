import json,os,unittest
from unittest.mock import patch
from shorts import claude as C

class QwenPlanTest(unittest.TestCase):
 def test_qwen_uses_chat_endpoint_own_credentials_and_full_json(self):
  spec={"scenes":[{"prompt":"A rabbit walks","duration":6}],"captions":["안녕"]}
  seen=[]
  def transport(url,body,key,timeout):
   seen.append((url,key,body));return {"content":[{"type":"text","text":json.dumps(spec)}],"stop_reason":"end_turn"}
  with patch.dict(os.environ,{"ANTHROPIC_API_KEY":"must-not-be-used","QWEN_LLM_API_KEY":"test-qwen","QWEN_LLM_BASE_URL":"http://127.0.0.1:8000/v1"}):
   result=C.plan("Plan a story",[],model=C.QWEN_MODEL,post=transport)
  self.assertEqual(seen[0][0],"http://127.0.0.1:8000/v1/chat/completions");self.assertEqual(seen[0][1],"test-qwen");self.assertEqual(result["spec"]["scenes"],spec["scenes"])
 def test_qwen_length_failure_does_not_accept_truncated_content(self):
  with self.assertRaises(C.PlanError):C.plan("story",[],model=C.QWEN_MODEL,post=lambda *args:{"content":[{"type":"text","text":"{}"}],"stop_reason":"max_tokens"})
