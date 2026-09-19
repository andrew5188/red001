"""Behavioral regressions for portable production quality gates; no rendering."""
import copy
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from quality_gates import require_input_quality, require_output_quality, STAGING_FIELDS


def fixture():
    line = dict(id="L1", speaker_character_id="A", voice_id="S1", text="你好.",
                start_seconds=1, end_seconds=4, framing="speaker_closeup",
                visible_mouth_characters=["A"], listener_behavior="B offscreen, listening")
    g = dict(id="G1", duration_seconds=10, output="clips/one.mp4",
             dialogue_plan=dict(status="ready", lines=[line]))
    m = dict(content_revision=3, characters=[dict(id="A"),dict(id="B")],
             scenes=[dict(id="S1", scene_type="drama", groups=[g])], video_issues=[],
             content_review=dict(input_reviews={"S1_G1":dict(quality_policy_version=1)},
                 audio_review_policy=dict(semantic_review_required=False,content_revision=3,user_instruction="first clip only")))
    inp=dict(quality_policy_version=1, checks=dict(dialogue="passed",action_staging="passed"))
    out=dict(quality_policy_version=1,checks=dict(dialogue_visual="passed",action_staging="passed"),
             line_reviews=[dict(line_id="L1",visual_status="passed",audio_status="waived",evidence="actual timed inspection")],
             staging_evidence="actual timed movement inspection")
    return m,g,inp,out


class QualityGates(unittest.TestCase):
    def test_single_speaker_with_honest_audio_waiver(self):
        m,g,i,o=fixture()
        require_input_quality(m,"S1_G1","<d>[Chinese] 你好.</d>",i)
        require_output_quality(m,"S1_G1",o)

    def test_prompt_and_plan_must_match(self):
        m,g,i,o=fixture()
        with self.assertRaisesRegex(RuntimeError,"differs"):
            require_input_quality(m,"S1_G1","<d>[Chinese] 再见.</d>",i)

    def test_isolated_shot_cannot_expose_second_mouth(self):
        m,g,i,o=fixture();g["dialogue_plan"]["lines"][0]["visible_mouth_characters"].append("B")
        with self.assertRaisesRegex(RuntimeError,"another mouth"):
            require_input_quality(m,"S1_G1","<d>[Chinese] 你好.</d>",i)

    def test_overlap_is_not_accidentally_permitted(self):
        m,g,i,o=fixture();second=copy.deepcopy(g["dialogue_plan"]["lines"][0]);second.update(id="L2",speaker_character_id="B",voice_id="S2",visible_mouth_characters=["B"],text="好.",start_seconds=3,end_seconds=5);g["dialogue_plan"]["lines"].append(second)
        with self.assertRaisesRegex(RuntimeError,"simultaneous"):
            require_input_quality(m,"S1_G1","<d>[Chinese] 你好.</d><d>[Chinese] 好.</d>",i)
        second.update(intentional_overlap=True,overlap_reason="Story explicitly calls for the interruption")
        require_input_quality(m,"S1_G1","<d>[Chinese] 你好.</d><d>[Chinese] 好.</d>",i)

    def test_offscreen_dialogue_can_show_listener(self):
        m,g,i,o=fixture();g["dialogue_plan"]["lines"][0].update(framing="offscreen",visible_mouth_characters=["B"])
        require_input_quality(m,"S1_G1","<d>[Chinese] 你好.</d>",i)

    def test_known_issue_survives_waiver_and_merge_request(self):
        m,g,i,o=fixture();m["video_issues"]=[dict(issue_id="D1",status="open",candidate_segments=["S1_G1"])];o["delivery_acceptance"]="merge it"
        with self.assertRaisesRegex(RuntimeError,"Unresolved user issue"):
            require_output_quality(m,"S1_G1",o)

    def test_visual_error_cannot_be_waived(self):
        m,g,i,o=fixture();o["line_reviews"][0]["visual_status"]="failed"
        with self.assertRaisesRegex(RuntimeError,"cannot be waived"):
            require_output_quality(m,"S1_G1",o)

    def test_new_output_cannot_fall_back_to_legacy(self):
        m,g,i,o=fixture();o.pop("quality_policy_version")
        with self.assertRaisesRegex(RuntimeError,"current quality"):
            require_output_quality(m,"S1_G1",o)

    def test_unchanged_legacy_review_remains_legacy(self):
        m,g,i,o=fixture();m["content_review"]["input_reviews"]={}
        require_output_quality(m,"S1_G1",{})

    def test_action_needs_staging_and_actual_evidence(self):
        m,g,i,o=fixture();m["scenes"][0]["scene_type"]="action";g["dialogue_plan"]["lines"]=[]
        with self.assertRaisesRegex(RuntimeError,"staging plan"):
            require_input_quality(m,"S1_G1","no speech",i)
        g["action_plan"]={"staging":{k:"Scene-specific reviewed choice" for k in STAGING_FIELDS}}
        require_input_quality(m,"S1_G1","no speech",i)
        o["staging_evidence"]=""
        with self.assertRaisesRegex(RuntimeError,"evidence missing"):
            require_output_quality(m,"S1_G1",o)


if __name__ == "__main__":
    unittest.main()
