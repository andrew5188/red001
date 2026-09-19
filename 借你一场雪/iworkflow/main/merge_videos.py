"""Merge all reviewed project clips in manifest order using the current output profile."""
import json
import subprocess
from pathlib import Path
import av
import imageio_ffmpeg
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare_job import require_output_review

ROOT=Path(__file__).resolve().parents[2]

def validate(path,seconds,width,height,fps):
    with av.open(str(path)) as c:
        v=c.streams.video[0]
        assert (v.width,v.height)==(width,height), 'Unexpected dimensions'
        assert abs(float(v.average_rate)-fps)<.01, 'Unexpected fps'
        assert c.streams.audio, 'Missing audio'
        assert sum(1 for _ in c.decode(video=0))==round(seconds*fps), 'Wrong frame count'
    with av.open(str(path)) as c:
        a=c.streams.audio[0]
        duration=sum(frame.samples for frame in c.decode(audio=0))/a.rate
        assert abs(duration-seconds)<.12, 'Audio duration mismatch'

def main(batch=False):
    manifest=ROOT/'project.json';d=json.loads(manifest.read_text(encoding='utf-8'))
    ordered=[(s['id']+'_'+g['id'],g) for s in d['scenes'] for g in s['groups']]
    if batch:
        scope=d.get('production_batch',{})
        keys=scope.get('merge_keys',[])
        if scope.get('status')!='active' or not scope.get('user_instruction') or not keys:
            raise RuntimeError('An active explicitly requested batch is required')
        if keys!=[k for k,g in ordered[:len(keys)]]:
            raise RuntimeError('Batch must preserve the contiguous story prefix')
        ordered=ordered[:len(keys)]
    groups=[g for k,g in ordered]
    if not groups or any(g.get('status')!='complete' or not g.get('output') for g in groups):
        raise RuntimeError('All project clips must pass review before merging.')
    for key,group in ordered:require_output_review(d,key)
    profile=json.loads((Path(__file__).parent/'profile.json').read_text(encoding='utf-8'))['output']
    width,height,fps=profile['width'],profile['height'],profile['fps']
    seconds=[g['duration_seconds'] for g in groups]
    paths=[(ROOT/g['output']).resolve() for g in groups]
    for p,duration in zip(paths,seconds):
        if not p.is_relative_to(ROOT.resolve()):raise ValueError('Clip outside project directory')
        validate(p,duration,width,height,fps)
    directory=(ROOT/profile['directory']).resolve()
    if not directory.is_relative_to(ROOT.resolve()):raise ValueError('Output outside project')
    stem=f'batch_{len(groups):02d}clips_{width}x{height}' if batch else f'final_{width}x{height}'
    version=1
    while (directory/f'{stem}_v{version}.mp4').exists():version+=1
    out=directory/f'{stem}_v{version}.mp4'
    out.parent.mkdir(exist_ok=True)
    command=[imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-n']
    for p in paths:command+=['-i',str(p)]
    filters=[]
    for i,duration in enumerate(seconds):
        filters.append(f'[{i}:v]fps={fps},setsar=1,trim=duration={duration},setpts=PTS-STARTPTS[v{i}]')
        filters.append(f'[{i}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=duration={duration},asetpts=PTS-STARTPTS,afade=t=in:d=0.015,afade=t=out:st={duration-.015}:d=0.015[a{i}]')
    filters.append(''.join(f'[v{i}][a{i}]' for i in range(len(groups)))+f'concat=n={len(groups)}:v=1:a=1[v][a]')
    audio_map='[a]'
    if batch:
        # Keep relative dialogue/music mix; reserve peak headroom and close this requested edition.
        filters.append(f'[a]volume=0.89125094,afade=t=out:st={sum(seconds)-0.6}:d=0.6[a_batch]')
        audio_map='[a_batch]'
    command+=['-filter_complex',';'.join(filters),'-map','[v]','-map',audio_map,
              '-c:v','libx264','-crf','18','-preset','medium','-pix_fmt','yuv420p',
              '-r',str(fps),'-fps_mode','cfr','-c:a','aac','-b:a','192k','-movflags','+faststart',str(out)]
    subprocess.run(command,check=True)
    validate(out,sum(seconds),width,height,fps)
    if batch:
        d['candidate_batch_output']=str(out.relative_to(ROOT))
        d['production_batch'].update(status='merged_pending_review',output=str(out.relative_to(ROOT)),duration_seconds=sum(seconds),source_keys=[k for k,g in ordered])
        d['phase']='batch_content_review'
    else:
        d['candidate_final_output']=str(out.relative_to(ROOT))
        d['phase']='final_content_review'
    temp=manifest.with_suffix('.tmp');temp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(manifest)
    from prepare_job import refresh_registry
    refresh_registry()
    print(out)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--batch',action='store_true');args=parser.parse_args();main(batch=args.batch)
