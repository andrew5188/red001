"""Collect successful native output and inspect media before the agent's content review."""
import json,math,urllib.request,urllib.parse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import av,numpy as np
from PIL import Image,ImageDraw
from prepare_job import HERE,ROOT,read,save,find_group,reject_invalidated_content

def descriptors(obj):
    if isinstance(obj,dict):
        if 'filename' in obj and 'type' in obj:yield obj
        else:
            for value in obj.values():yield from descriptors(value)
    elif isinstance(obj,list):
        for value in obj:yield from descriptors(value)

def main():
    d=read(ROOT/'project.json');j=d['jobs'][-1];folder=ROOT/j['record_directory'];base=d['settings']['comfy_base_url']
    reject_invalidated_content(d,j['scene']+'_'+j['group'])
    if j.get('content_revision',2)!=d.get('content_revision',2):raise RuntimeError('Historical output cannot replace current revision')
    h=json.load(urllib.request.urlopen(base+'/history/'+j['prompt_id'],timeout=20)).get(j['prompt_id'])
    if not h or h['status']['status_str']!='success':raise RuntimeError('Render has not succeeded')
    save(folder/'result.json',h);rec=read(folder/'record.json');profile=rec['profile']['output'];seconds=rec['inputs']['duration_seconds'];fps=profile['fps']
    dest=ROOT/'03_分场制作'/j['scene']/j['group']/f"revision_{j['content_revision']:02d}"/f"attempt_{j['attempt']:02d}";dest.mkdir(parents=True,exist_ok=True)
    files=[]
    for f in descriptors(h['outputs']):
        target=dest/Path(f['filename']).name
        if not target.exists():
            url=base+'/view?'+urllib.parse.urlencode({k:f.get(k,'') for k in ['filename','subfolder','type']})
            target.write_bytes(urllib.request.urlopen(url,timeout=30).read())
        files.append(target)
    videos=[p for p in files if p.suffix.lower()=='.mp4'];guides=[p for p in files if p.suffix.lower()=='.png']
    if len(videos)!=1 or len(guides)!=1:raise RuntimeError('Expected one video and one actual end frame')
    review=dest/'review';review.mkdir(exist_ok=True);video=videos[0]
    expected=round(fps*seconds);indices=set(range(0,expected,max(1,round(fps/2))))|{expected-1};thumbs=[]
    with av.open(str(video)) as c:
        s=c.streams.video[0];report={'width':s.width,'height':s.height,'fps':float(s.average_rate),'has_audio':bool(c.streams.audio)};count=0
        for frame in c.decode(video=0):
            if count in indices:
                im=frame.to_image();im.save(review/f'frame_{count:04d}.png');im.thumbnail((384,216));thumbs.append((count,im))
            count+=1
    report['frames']=count
    report['sampled_times_seconds']=[index/fps for index,_ in thumbs]
    if report['has_audio']:
        n=0;squares=0.;peak=0.;clipped=0;sample_frames=0
        with av.open(str(video)) as c:
            rate=c.streams.audio[0].rate
            for frame in c.decode(audio=0):
                x=frame.to_ndarray().astype(np.float64)
                if not frame.format.is_planar and not frame.format.name.startswith('flt'):raise ValueError('Unexpected audio format')
                n+=x.size;sample_frames+=frame.samples;squares+=float((x*x).sum());peak=max(peak,float(np.abs(x).max()));clipped+=int((np.abs(x)>=.999).sum())
        report.update(audio_seconds=sample_frames/rate,audio_peak=peak,audio_rms_db=20*math.log10(max(math.sqrt(squares/max(n,1)),1e-12)),clipped_fraction=clipped/max(n,1))
    report['technical_pass']=all([report['width']==profile['width'],report['height']==profile['height'],abs(report['fps']-fps)<.01,count==expected,report['has_audio'],abs(report.get('audio_seconds',0)-seconds)<.12,report.get('audio_rms_db',-120)>-65])
    report['visual_review']='pending';report['dialogue_and_music_review']='not_listened'
    columns=min(5,len(thumbs));rows=math.ceil(len(thumbs)/columns)
    canvas=Image.new('RGB',(384*columns,240*rows),'white');draw=ImageDraw.Draw(canvas)
    for i,(index,im) in enumerate(thumbs):
        x=(i%columns)*384;y=(i//columns)*240
        canvas.paste(im,(x,y+24));draw.text((x+5,y+5),f'{index/fps:.2f}s',fill='black')
    canvas.save(review/'contact_sheet.jpg');save(review/'check.json',report)
    g=find_group(d,j['scene']+'_'+j['group']);g.update(status='technical_checked' if report['technical_pass'] else 'technical_failed',output=str(video.relative_to(ROOT)),continuity_guide=str(guides[0].relative_to(ROOT)),review=str((review/'check.json').relative_to(ROOT)))
    j['status']='success';rec['status']='success';save(folder/'record.json',rec);save(ROOT/'project.json',d)
    print(json.dumps(report,ensure_ascii=False));print(review/'contact_sheet.jpg')

if __name__=='__main__':
    main()
