"""Reproduce mixed reference/guide row mismatch with native H3 packing, without weights."""
import sys
from pathlib import Path
import importlib.util
import json
from types import SimpleNamespace

sys.dont_write_bytecode = True
COMFY = Path(r'E:\ai\ComfyUI_windows_portable\ComfyUI')
sys.path.insert(0, str(COMFY))
sys.argv = ['check_guide_tiling', '--cpu']
import comfy.options
comfy.options.enable_args_parsing()
import torch
from comfy.ldm.minimax.model import MiniMaxH3Model, patchify_video

HERE = Path(__file__).resolve().parent

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

before = load('tiling_before', 'h3_tiling.before.py')
after = load('tiling_after', 'h3_tiling.guidefix.py')
context = torch.zeros(1, 16, 8)
audio = torch.zeros(1, 32, 2, 405)
owner = SimpleNamespace(patch_size=(1, 2, 2))

def payload(h, w, with_guide, with_refs):
    guides = [{'resolved_frame_index': 0, 'latent': torch.zeros(1, 24, 1, h, w)}] if with_guide else []
    refs = [{'kind': 'image', 'latent_h': rh, 'latent_w': rw,
             'latent': torch.zeros(1, 24, 1, rh, rw)} for rh, rw in [(32, 48), (32, 48), (30, 54)]] if with_refs else []
    return {'keyframes': guides, 'refs': refs,
            'cond_video_latents': [item['latent'] for item in guides + refs],
            'visual_cond_noise_aug': 1.0}

video = torch.zeros(1, 24, 72, 46, 80)
original = payload(46, 80, True, True)
start, end = before._regions(80, 8)[0]
broken = before._tile_payload(original, context, video, audio, 4, start, end)
rows = MiniMaxH3Model._cond_video_rows(owner, broken, 'cpu')
baseline = [rows.shape[0], int((~broken['layout'].img_update).sum())]
assert baseline == [2093, 1380], baseline

cases = 0
for h, w, axis in [(46, 80, 4), (80, 46, 3)]:
    video = torch.zeros(1, 24, 72, h, w)
    for guide, refs in [(True, True), (True, False), (False, True), (False, False)]:
        original = payload(h, w, guide, refs)
        for start, end in after._regions(video.shape[axis], 8):
            tiled = after._tile_payload(original, context, video, audio, axis, start, end)
            rows = MiniMaxH3Model._cond_video_rows(owner, tiled, 'cpu')
            update = tiled['layout'].img_update
            target_rows = patchify_video(video.narrow(axis, start, end-start), (1, 2, 2))
            all_rows = torch.empty(update.shape[0], 96)
            if rows is not None:
                all_rows[~update] = rows
            else:
                assert not (~update).any()
            all_rows[update] = target_rows
            for original_ref, tiled_ref in zip(original['refs'], tiled['refs']):
                assert original_ref['latent'] is tiled_ref['latent']
            if guide:
                assert original['keyframes'][0]['latent'].shape[-2:] == (h, w)
            cases += 1
result = {'baseline_cond_rows_vs_mask': baseline, 'fixed_cases': cases,
          'passed': True, 'scope': 'Native H3 layout and row assignments on CPU; full render still pending'}
(HERE / 'regression_result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
