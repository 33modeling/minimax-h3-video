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


class ScenePrompts(unittest.TestCase):
    IR = ("integrated_multimodal_description: [Shot 1] A fox runs. The camera tracks it. [Shot 2] At 00:06.000, the camera cuts to "
          "a wide shot as the fox jumps. [Shot 3] At 00:12.500, the camera cuts to a close-up of the fox. [Shot 4] At 00:16.000, "
          "the shot cuts to the fox walking away.\n\noverall_soundscape: Snow crunching.\n\nnon_diegetic_music: Soft piano.")

    def test_ir_split_by_time_keeps_sound_fields(self):
        a, b = P.scene_prompts(self.IR, [10, 10])
        for s in (a, b):
            f = P.split_fields(s)
            self.assertEqual((f["overall_soundscape"], f["non_diegetic_music"]), ("Snow crunching.", "Soft piano."))
        self.assertIn("[Shot 2] At 00:06.000, the camera cuts to a wide shot", a)
        self.assertNotIn("close-up", a)
        # 10초에 이어지던 넓은 샷이 2장면 첫 샷, 이후 샷은 장면 기준 시각으로
        self.assertTrue(P.split_fields(b)["integrated_multimodal_description"].startswith("[Shot 1] A wide shot as the fox jumps."))
        self.assertIn("[Shot 2] At 00:02.500, the camera cuts to a close-up", b)
        self.assertIn("[Shot 3] At 00:06.000, the shot cuts to the fox walking away", b)

    def test_ir_without_cuts_in_later_scene(self):
        ir = "integrated_multimodal_description: [Shot 1] A fox sleeps.\n\noverall_soundscape: Wind.\n\nnon_diegetic_music: None."
        a, b = P.scene_prompts(ir, [8, 8])
        self.assertEqual(a, b)
        self.assertIn("[Shot 1] A fox sleeps.", b)

    def test_plain_text(self):
        a, b = P.scene_prompts("여우가 달린다", [10, 10])
        self.assertTrue(a.startswith("여우가 달린다") and "1번째 장면, 전체의 0~10초" in a)
        self.assertIn("2번째 장면, 전체의 10~20초", b)
        self.assertEqual(P.scene_prompts("여우가 달린다", [10, 10], rewrite=False), ["여우가 달린다"] * 2)

    def test_alignment_line_dropped_from_fields(self):
        f = P.split_fields(P.keyframe_note(True, False, 8) + "\n\n" + self.IR)
        self.assertTrue(f["integrated_multimodal_description"].startswith("[Shot 1] A fox runs."))


class NeedsRewrite(unittest.TestCase):
    def test_rules(self):
        en = RW.extract(GOOD_BASE, "fl2va")
        self.assertFalse(RW.needs_rewrite(en, "fl2va"))                                    # 완성된 영어 공식 형식만 그대로
        self.assertFalse(RW.needs_rewrite(P.keyframe_note(True, False, 8) + "\n\n" + en, "fl2va"))
        self.assertTrue(RW.needs_rewrite("눈 속을 달리는 여우", "fl2va"))                       # 한국어
        ko_fields = en.replace("A fox runs.", "여우가 달린다.")
        self.assertTrue(RW.needs_rewrite(ko_fields, "fl2va"))                              # 필드는 있는데 설명이 한국어
        self.assertTrue(RW.needs_rewrite("integrated_multimodal_description: [Shot 1] A fox runs.", "fl2va"))   # 필드가 빠짐
        self.assertTrue(RW.needs_rewrite("장면1: 여우\n장면2: 클로즈업", "fl2va"))           # 자기 형식
        dialog = en.replace("A fox runs.", 'A girl (S1) says: <d>[Korean] 안녕하세요</d> and waves.')
        self.assertFalse(RW.needs_rewrite(dialog, "fl2va"))                                # 대사 속 한국어는 괜찮다
        self.assertFalse(RW.needs_rewrite(en.replace("A fox runs.", 'A sign reads "서울역".'), "fl2va"))   # 화면 글자


class ExtractLayouts(unittest.TestCase):
    def test_values_on_next_line_like_guide(self):
        ref = "\n\n".join(f"{f}:\nline for {f}" for f in RW.REF_FIELDS)   # 가이드 7절 예시처럼 값이 다음 줄
        out = RW.extract(ref, "ref2va")
        self.assertIsNotNone(out)
        self.assertTrue(out.rstrip().endswith("line for non_diegetic_music"))
        base = "integrated_multimodal_description:\n[Shot 1] A fox.\n\noverall_soundscape:\nWind.\n\nnon_diegetic_music:\nPiano."
        self.assertTrue(RW.extract(base, "fl2va").endswith("Piano."))

    def test_trailing_chatter_and_backticks_dropped(self):
        text = ("`integrated_multimodal_description:` [Shot 1] A fox.\n\n`overall_soundscape:` Wind.\n\n"
                "`non_diegetic_music:` Piano.\n\nNote: I kept the dialogue in Korean.\n```")
        out = RW.extract(text, "fl2va")
        self.assertTrue(out.endswith("Piano."))
        self.assertNotIn("Note:", out)
        self.assertNotIn("`", out)


class GenWithReferences(unittest.TestCase):
    def run_cli(self, *args):
        import io, contextlib
        from h3video import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(list(args))
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_gen_image_goes_to_ref2va(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            img = os.path.join(d, "me.png"); open(img, "wb").write(b"\x89PNG")
            code, out, err = self.run_cli("gen", "<Subject 1> waves", "--image", img, "-s", "6", "--dry-run")
            self.assertEqual(code, 0, err)
            self.assertIn('"task": "ref2va"', out + err)
            code, out, err = self.run_cli("gen", "x", "--image", img, "--first", img, "-s", "6", "--dry-run")
            self.assertNotEqual(code, 0)
            self.assertIn("같이 쓸 수 없다", out + err + str(code))
