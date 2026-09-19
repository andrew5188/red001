"""Portable structural gates. They never infer audiovisual quality from metadata."""
import math
import re

VERSION = 1
STAGING_FIELDS = ("composition", "depth", "footwork", "camera_axis", "camera_follow",
                  "end_change", "keyframe_alignment", "dramatic_result")


def group_for(manifest, key):
    return next((s, g) for s in manifest["scenes"] for g in s["groups"]
                if s["id"] + "_" + g["id"] == key)


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def norm(path):
    return str(path or "").replace("\\", "/")


def words(text):
    return re.sub(r"\s+", " ", re.sub(r"^\[[^]]+\]\s*", "", text.strip())).strip()


def is_action(scene, group):
    return group.get("scene_type", scene.get("scene_type")) in ("action", "mixed")


def require_input_quality(manifest, key, prompt, review):
    scene, group = group_for(manifest, key)
    need(review.get("quality_policy_version") == VERSION, "Fresh quality-policy input review required")
    plan = group.get("dialogue_plan", {})
    need(plan.get("status") == "ready" and isinstance(plan.get("lines"), list), "Ready dialogue_plan required, including explicit empty lines for no speech")
    lines = plan["lines"]
    utterances = [words(x) for x in re.findall(r"<d>(.*?)</d>", prompt, flags=re.S)]
    need([words(x.get("text", "")) for x in lines] == utterances, "Dialogue plan differs from actual submitted prompt")
    ids = set(); voices = {}; previous_lines = []
    characters = {c["id"] for c in manifest["characters"]}
    duration = group["duration_seconds"]
    for line in lines:
        lid = line.get("id"); speaker = line.get("speaker_character_id")
        need(isinstance(lid, str) and lid and lid not in ids, "Distinct line IDs required")
        ids.add(lid)
        need(speaker in characters and re.fullmatch(r"S[1-9][0-9]*", str(line.get("voice_id", ""))), "Valid speaker and voice ID required")
        need(speaker not in voices or voices[speaker] == line["voice_id"], "One speaker changes voice ID within segment")
        need(speaker in voices or line["voice_id"] not in voices.values(), "Distinct speakers share a voice ID")
        voices[speaker] = line["voice_id"]
        start = line.get("start_seconds"); end = line.get("end_seconds")
        need(all(type(v) in (int, float) and math.isfinite(v) for v in (start, end)), "Finite dialogue times required")
        need(0 <= start < end <= duration, "Dialogue time outside segment")
        if previous_lines:
            need(start >= previous_lines[-1]["start_seconds"], "Dialogue plan must follow timeline order")
            if any(start < old["end_seconds"] for old in previous_lines):
                need(line.get("intentional_overlap") is True and bool(line.get("overlap_reason")), "Unplanned simultaneous dialogue")
        previous_lines.append(line)
        framing = line.get("framing"); mouths = line.get("visible_mouth_characters")
        need(isinstance(mouths, list) and len(mouths) == len(set(mouths)) and set(mouths) <= characters, "Valid visible mouth identities required")
        need(framing in ("speaker_closeup", "over_shoulder", "offscreen", "two_shot", "ensemble"), "Explicit dialogue framing required")
        if framing == "offscreen":
            need(speaker not in mouths, "Offscreen speaker cannot claim visible lip-sync")
        elif framing in ("speaker_closeup", "over_shoulder"):
            need(mouths == [speaker], "Speaker-isolated framing still exposes another mouth")
        else:
            need(speaker in mouths and bool(line.get("framing_reason")), "Multi-mouth dialogue needs reviewed framing rationale")
        need(bool(line.get("listener_behavior")), "Listener behavior required")
    if lines:
        need(review.get("checks", {}).get("dialogue") == "passed", "Dialogue input semantics not reviewed")
    if is_action(scene, group):
        staging = group.get("action_plan", {}).get("staging", {})
        need(all(isinstance(staging.get(k), str) and staging[k].strip() for k in STAGING_FIELDS), "Action staging plan incomplete")
        need(review.get("checks", {}).get("action_staging") == "passed", "Action staging input not reviewed")


def require_output_quality(manifest, key, review):
    scene, group = group_for(manifest, key)
    output = norm(group.get("output"))
    for issue in manifest.get("video_issues", []):
        if issue.get("status") in ("resolved", "dismissed", "resolved_by_replacement"):
            continue
        keys = issue.get("affected_segments", []) + issue.get("candidate_segments", [])
        paths = issue.get("affected_outputs", []) + issue.get("candidate_outputs", [])
        related = key in keys or (output and (output == norm(issue.get("output")) or output in [norm(p) for p in paths]))
        need(not related, "Unresolved user issue blocks output: " + issue.get("issue_id", "unknown"))
    prior_input = manifest.get("content_review", {}).get("input_reviews", {}).get(key, {})
    versions = (group.get("quality_policy_version", 0), prior_input.get("quality_policy_version", 0), review.get("quality_policy_version", 0))
    if max(versions) < VERSION:
        return  # Unaffected historic review is retained, never rewritten as a new check.
    need(review.get("quality_policy_version") == VERSION, "New output lacks current quality review")
    plan = group.get("dialogue_plan", {})
    need(plan.get("status") == "ready" and isinstance(plan.get("lines"), list), "Output lacks reviewed dialogue plan")
    lines = plan["lines"]
    if lines:
        need(review.get("checks", {}).get("dialogue_visual") == "passed", "Dialogue mouth ownership not reviewed")
        rows = review.get("line_reviews", [])
        need(len(rows) == len(lines) and {x.get("line_id") for x in rows} == {x["id"] for x in lines}, "Per-line review coverage incomplete")
        policy = manifest.get("content_review", {}).get("audio_review_policy", {})
        waiver = policy.get("semantic_review_required") is False and policy.get("content_revision") == manifest.get("content_revision") and bool(policy.get("user_instruction"))
        for row in rows:
            need(row.get("visual_status") == "passed" and bool(row.get("evidence")), "Visible dialogue defect or missing evidence cannot be waived")
            need(row.get("audio_status") == "passed" or (row.get("audio_status") == "waived" and waiver), "Per-line audio neither checked nor validly waived")
    if is_action(scene, group):
        need(review.get("checks", {}).get("action_staging") == "passed", "Cinematic action staging not reviewed")
        need(bool(review.get("staging_evidence")), "Action staging evidence missing")
