"""Project bootstrap and status reading for short-drama-agent.
This helper does not submit renders or call image generation services.
"""
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def initialize(root, title):
    root = Path(root).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("Project directory is not empty; use status/resume or a new path.")
    root.mkdir(parents=True, exist_ok=True)
    for name in ("00_故事大纲", "01_完整剧本", "02_角色库", "02_场景库", "03_分场制作", "04_全片输出", "iworkflow"):
        (root / name).mkdir(exist_ok=True)
    style_source = Path(__file__).resolve().parents[1] / "assets/character_style_semi_realistic_guofeng.png"
    style_relative = "00_故事大纲/风格参考/半写实国风_人物参考.png"
    style_target = root / style_relative
    style_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(style_source, style_target)
    manifest = {
        "schema_version": 1, "title": title, "root": str(root),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "phase": "outline_discussion", "production_authorized": False,
        "selected_outline": None, "script": None,
        "content_review": {
            "status": "pending", "requirements": [], "shot_plan": None,
            "input_reviews": {}, "output_reviews": {},
            "first_video_human_review": {"status": "pending", "segment": None,
                                         "output": None, "sha256": None, "user_answer": None},
            "first_action_human_review": {"status": "pending", "segment": None,
                                          "output": None, "sha256": None, "user_answer": None},
            "reason": "Awaiting project-specific requirements and actual content review"
        },
        "settings": {"group_seconds": 10, "max_group_seconds": 10,
                     "aspect_ratio": "16:9", "max_retries_per_group": 2,
                     "review": {"human_confirmation": "first_video_only",
                                "action_confirmation": "first_action_video",
                                "subsequent_review": "automatic",
                                "scene_performance_planning": True,
                                "performance_review_required": True,
                                "final_confirmation_required": False,
                                "unavailable_audio_semantics": "record_unverified_and_continue_after_first_approval"},
                     "audio": {"enabled": True, "dialogue": True,
                               "ambience": True, "sound_effects": True,
                               "background_music": True, "music_style": "story_adaptive",
                               "music_strategy": {"scene_music_plan_required": True, "theme_continuity": True, "dialogue_ducking": True, "key_effects_space": True, "intentional_silence_allowed": True, "post_mix_source_required": True},
                               "instrumental_by_default": True, "dialogue_priority": True},
                     "scene_assets": {"directory_pattern": "02_场景库/{location_id}_{location_name}", "shared_across_scenes": True, "derive_views_from_master": True, "required_views": "shot_dependent", "empty_background": True},
                     "character_assets": {"directory_pattern": "02_角色库/{character_id}_{character_name}", "required_views": ["three_view", "full_body", "half_body"], "background": "white", "derive_from_same_identity": True, "video_reference_policy": "one_suitable_single_person_image_per_visible_character"},
                     "visual_style": {"status": "selected",
                                      "selected_style": "semi_realistic_guofeng",
                                      "display_name": "半写实国风",
                                      "description": "适度理想化五官、略大自然眼睛、细腻柔和皮肤、真实发丝与衣料、自然比例和柔和立体明暗",
                                      "reference_paths": [style_relative],
                                      "reference_scope": "character_rendering_only; not identity, costume, background or layout",
                                      "selection_source": "user_skill_default"},
                     "scene_strategy": {"default_scene_type": "drama",
                                        "action_prompt_required_for_action": True,
                                        "action_lora": {"enabled": False, "model": None, "strength": None},
                                        "appearance_lora": {"enabled": True, "model": None, "strength": 0.6, "trigger": "r34l1sm", "source": "https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA", "validation": "model_selection_pending"},
                                        "override_order": ["segment", "scene", "project"]},
                     "comfy_base_url": None,
                     "generation": {"seconds_per_video": 10, "sequential": True,
                                    "prompt_skill": "h3-prompt-writing",
                                    "auto_merge": True, "final_output_directory": "04_全片输出"},
                     "rendering": {
                         "target_resolution": None, "target_width": None,
                         "target_height": None, "hardware_snapshot": None,
                         "default_route": "selflift_h3_latent_upscale",
                         "configured_plan": None,
                         "selection_source": "user_skill_default",
                         "selection_status": "awaiting_requirements",
                         "workflow_strategy": "agent_built_reusable_master",
                         "workflow_layout": "single_master_with_segment_parameters_and_run_records",
                         "editable_workflow": None, "editable_api": None,
                         "workflow_support_directory": "iworkflow/main",
                         "segment_parameters": None, "profile": None,
                         "execution_records": "iworkflow/main/runs",
                         "workflow_directory": "iworkflow",
                         "preferred_methods": ["selflift", "h3_latent_upscale"],
                         "research_sources": [],
                         "workflow_paths": [], "benchmark_results": []}},
        "characters": [], "locations": [], "scenes": [], "jobs": [],
        "final_output": None, "unresolved_issues": []
    }
    target = root / "project.json"
    with target.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return {"manifest": str(target), "phase": manifest["phase"]}

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--root", required=True)
    init.add_argument("--title", required=True)
    status = commands.add_parser("status")
    status.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize(args.root, args.title)
        elif args.command == "status":
            result = read_json(Path(args.root) / "project.json")
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
