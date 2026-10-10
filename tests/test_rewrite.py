"""프롬프트 다듬기(rewrite.py)와 서버의 조립(_prepare_prompt). 모델 없이 — 생성 함수는 가짜로 바꿔 끼운다."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from h3video import dserver, prompt as P, rewrite as RW  # noqa: E402

GOOD_BASE = ("Sure! Here is the prompt:\n```\nintegrated_multimodal_description: [Shot 1] A fox runs. [Shot 2] At 00:04.000, "
             "the camera cuts to a close-up.\n\noverall_soundscape: Snow crunching.\n\nnon_diegetic_music: Soft piano.\n```")
GOOD_REF = "\n\n".join(f"{f}: text for {f}" for f in RW.REF_FIELDS)


class RewriteHelpers(unittest.TestCase):
    def test_instruction_lines_match_official_guide(self):
        # VIDEO_PROMPT_WRITING_GUIDE_base_en.md 2.1 의 문구
        self.assertEqual(RW.instruction(["image"], 8.0, 2),
                         "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.")
        self.assertEqual(RW.instruction(["image", "last_image"], 6.58, 3),
                         "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second "
                         "mark of the target video; Picture 2 (from Shot 3) aligns with the 6.58-second mark of the target video.")
        self.assertEqual(RW.instruction(["last_image"], 8, 1),
                         "How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the "
                         "8.00-second mark of the target video.")
        self.assertIsNone(RW.instruction([], 8, 1))

    def test_modes(self):
        self.assertEqual([RW.mode_name("fl2va", s) for s in ([], ["image"], ["last_image"], ["image", "last_image"])],
                         ["T2VA", "I2VA", "L2VA", "FL2VA"])
        self.assertEqual(RW.mode_name("ref2va", []), "Ref2VA")

    def test_extract(self):
        body = RW.extract(GOOD_BASE, "fl2va")
        self.assertTrue(body.startswith("integrated_multimodal_description: [Shot 1]"))
        self.assertTrue(body.rstrip().endswith("Soft piano."))
        self.assertNotIn("```", body)
        self.assertEqual(RW.max_shot(body), 2)
        self.assertIsNone(RW.extract("integrated_multimodal_description: x\n\noverall_soundscape: y", "fl2va"))   # 음악 없음
        self.assertIsNone(RW.extract("non_diegetic_music: a\noverall_soundscape: b\nintegrated_multimodal_description: c", "fl2va"))  # 순서
        self.assertIsNone(RW.extract(GOOD_BASE.replace("Soft piano.", ""), "fl2va"))   # 마지막 칸이 비었다
        self.assertTrue(RW.extract(GOOD_REF, "ref2va").startswith("subject_definitions:"))
        self.assertIsNone(RW.extract(GOOD_BASE, "ref2va"))

    def test_strip_and_already_written(self):
        p = P.keyframe_note(True, True, 6) + "\n\n비 오는 밤"
        self.assertEqual(RW.strip_instruction(p), "비 오는 밤")
        self.assertEqual(RW.strip_instruction("At the final frame of the target video, <Picture 2> is fully referenced.\n\nx"), "x")  # 옛 형식
        self.assertFalse(RW.already_written("비 오는 밤", "fl2va"))
        self.assertTrue(RW.already_written(P.keyframe_note(True) + "\n\n" + RW.extract(GOOD_BASE, "fl2va"), "fl2va"))
        self.assertTrue(RW.already_written(GOOD_REF, "ref2va"))
        self.assertFalse(RW.already_written(GOOD_BASE, "ref2va"))

    def test_keyframe_note_official(self):
        self.assertTrue(P.keyframe_note(False, True, 5).startswith("How the reference pictures align"))
        self.assertIn("5.00-second", P.keyframe_note(False, True, 5))


def fake_engine(guides=True):
    e = dserver.Engine.__new__(dserver.Engine)
    e.guides = {"base": "BASE GUIDE", "ref": "REF GUIDE"} if guides else {}
    e._te_pipe = SimpleNamespace(text_encoder="TE", processor="PROC", _execution_device="cpu")
    e._visuals = lambda plan, inputs: ([], [])
    return e


def plan(task="fl2va", prompt="눈 속을 달리는 여우", slots=(), rewrite=True, frames=158):
    return {"task": task, "prompt": prompt, "keyframes": [(s, {}) for s in slots], "num_frames": frames, "seed": 3, "rewrite": rewrite}


class PreparePrompt(unittest.TestCase):
    def test_rewrites_and_adds_alignment(self):
        e = fake_engine()
        with mock.patch.object(RW, "rewrite_with_model", return_value=GOOD_BASE) as m:
            out = e._prepare_prompt(plan(slots=("image", "last_image")), {})
        self.assertEqual(m.call_args.args[3], "BASE GUIDE")
        self.assertEqual(m.call_args.args[4], "FL2VA")
        self.assertEqual(m.call_args.args[6], "눈 속을 달리는 여우")
        first, rest = out.split("\n\n", 1)
        self.assertIn("Picture 2 (from Shot 2) aligns with the 6.58-second mark", first)
        self.assertTrue(rest.startswith("integrated_multimodal_description:"))

    def test_bad_output_twice_falls_back(self):
        e = fake_engine()
        with mock.patch.object(RW, "rewrite_with_model", return_value="I cannot do that") as m:
            out = e._prepare_prompt(plan(slots=("image",)), {})
        self.assertEqual(m.call_count, 2)
        self.assertTrue(out.startswith("For the target video, at 0.00 seconds"))
        self.assertTrue(out.endswith("눈 속을 달리는 여우"))

    def test_skips(self):
        for e, p in ((fake_engine(), plan(rewrite=False)), (fake_engine(guides=False), plan()),
                     (fake_engine(), plan(prompt=RW.extract(GOOD_BASE, "fl2va")))):
            with mock.patch.object(RW, "rewrite_with_model") as m:
                out = e._prepare_prompt(p, {})
            m.assert_not_called()
            self.assertEqual(out, RW.strip_instruction(p["prompt"]))

    def test_old_client_note_replaced(self):
        e = fake_engine()
        old = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n" \
              "At the final frame of the target video, <Picture 2> is fully referenced.\n\n눈 속을 달리는 여우"
        with mock.patch.object(RW, "rewrite_with_model", return_value=GOOD_BASE) as m:
            out = e._prepare_prompt(plan(prompt=old, slots=("image", "last_image")), {})
        self.assertEqual(m.call_args.args[6], "눈 속을 달리는 여우")
        self.assertEqual(out.count("aligns with"), 2)
        self.assertNotIn("At the final frame", out)

    def test_ref_uses_ref_guide_no_alignment(self):
        e = fake_engine()
        with mock.patch.object(RW, "rewrite_with_model", return_value=GOOD_REF) as m:
            out = e._prepare_prompt(plan(task="ref2va"), {})
        self.assertEqual(m.call_args.args[3], "REF GUIDE")
        self.assertTrue(out.startswith("subject_definitions:"))


if __name__ == "__main__":
    unittest.main()
