"""H3 Ref2VA input binding, one editable master, per-attempt immutable API records."""
import argparse, copy, hashlib, json, math, re
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent
def quality_rules():
    import importlib.util
    source=ROOT.parent/'.agents/skills/short-drama-agent/scripts/quality_gates.py'
    if not source.is_file():raise RuntimeError('Quality rules skill script missing: '+str(source))
    spec=importlib.util.spec_from_file_location('series_quality_gates',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,d):
    t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def local(path):
    p=(ROOT/path).resolve()
    if not p.is_relative_to(ROOT.resolve()):raise ValueError('Path outside project')
    return p
def check_pair():
    pair=read(HERE/'main.pair.json')
    for kind,p in [('ui',HERE.parent/'main.ui.json'),('api',HERE/'main.api.json')]:
        if hashlib.sha256(p.read_bytes()).hexdigest()!=pair[kind+'_sha256']:
            raise RuntimeError('Master edited: reconcile UI/API before running.')
    return pair
def find_group(manifest,key):
    return next(g for s in manifest['scenes'] for g in s['groups'] if s['id']+'_'+g['id']==key)

def reject_invalidated_content(manifest,key):
    """Do not reactivate invalidated inputs while content revisions are pending."""
    review=manifest.get('content_review',{})
    if review.get('status') in ('blocked','stale','failed'):
        raise RuntimeError('Content review blocks generation: '+review.get('reason','Revise and review inputs first'))
    scene=next(s for s in manifest['scenes'] if any(s['id']+'_'+g['id']==key for g in s['groups']))
    group=find_group(manifest,key)
    if any(x.get('status')=='stale' for x in (scene,scene.get('environment',{}),group)):
        raise RuntimeError('Scene, environment or segment is stale; revise and review before generation')

def digest(data):
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()

def input_snapshot(manifest,key,graph,config,guide):
    group=find_group(manifest,key)
    paths=[manifest['selected_outline'],manifest['script'],config['prompt'],
           'iworkflow/main/segments.json','iworkflow/main/profile.json',
           'iworkflow/main.ui.json','iworkflow/main/main.api.json']
    paths.extend(r['source_path'] for r in config['references'])
    if guide:paths.append(guide['file'])
    return {'revision':manifest['content_revision'],'requirements_sha256':digest(manifest['content_review']['requirements']),
            'files':{str(Path(p)):hashlib.sha256(local(p).read_bytes()).hexdigest() for p in paths},
            'quality_plan_sha256':digest({'policy':quality_rules().VERSION,'dialogue':group.get('dialogue_plan'),'staging':group.get('action_plan',{}).get('staging'),'guard_sha256':hashlib.sha256((ROOT.parent/'.agents/skills/short-drama-agent/scripts/quality_gates.py').read_bytes()).hexdigest()}),
            'api_sha256':digest(graph)}

def require_input_review(manifest,key,graph,config,guide):
    review=manifest.get('content_review',{}).get('input_reviews',{}).get(key,{})
    quality_rules().require_input_quality(manifest,key,graph['16']['inputs']['prompt'],review)
    if review.get('status')!='passed' or any(review.get('checks',{}).get(k)!='passed' for k in ('script','references','prompt','api')):
        raise RuntimeError('Input content review is missing or incomplete')
    current=input_snapshot(manifest,key,graph,config,guide)
    if review.get('snapshot')!=current:raise RuntimeError('Reviewed inputs changed; review and prepare again')
    return current

def require_output_review(manifest,key):
    quality_rules().require_output_quality(manifest,key,manifest.get('content_review',{}).get('output_reviews',{}).get(key,{}))
    group=find_group(manifest,key)
    review=manifest.get('content_review',{}).get('output_reviews',{}).get(key,{})
    if group.get('status')!='complete' or review.get('status')!='passed' or review.get('revision')!=manifest['content_revision']:
        raise RuntimeError('Previous segment has not passed current content review')
    if any(review.get('checks',{}).get(k)!='passed' for k in ('technical','visual','audio','continuity')):
        raise RuntimeError('Necessary output checks are incomplete')
    for field in ('output','continuity_guide'):
        p=local(group[field])
        if review.get('files',{}).get(group[field])!=hashlib.sha256(p.read_bytes()).hexdigest():
            raise RuntimeError('Reviewed output or guide changed')

def bind(key,attempt,manifest=None):
    manifest=manifest or read(ROOT/'project.json');config=read(HERE/'segments.json')[key];profile=read(HERE/'profile.json')
    reject_invalidated_content(manifest,key)
    for runtime in profile.get('runtime_fixes',[]):
        if hashlib.sha256(Path(runtime['target']).read_bytes()).hexdigest()!=runtime['sha256']:
            raise RuntimeError('Reviewed runtime fix changed; verify compatibility before generation')
    g=copy.deepcopy(read(HERE/'main.api.json'));o=profile['output'];seconds=config['duration_seconds']
    width,height,fps=o['width'],o['height'],o['fps']
    if fps!=24:raise ValueError('Installed H3 engine uses native 24fps; other fps require a separately validated conversion.')
    if any(not isinstance(x,int) or x<64 or x%2 for x in [width,height]):raise ValueError('Dimensions must be even integers >=64')
    if not profile['limits']['min_seconds']<=seconds<=profile['limits']['max_seconds']:raise ValueError('H3 supported duration is 4-15s')
    frames=round(seconds*fps)
    if abs(frames/fps-seconds)>1e-6:raise ValueError('Duration must align with output frames')
    refs=config['references']
    if not 1<=len(refs)<=len(profile['reference_slots']):raise ValueError('Ref2VA requires 1-9 reference images')
    prompt=local(config['prompt']).read_text(encoding='utf-8-sig')
    fields=['subject_definitions','summary','retention_analysis','detailed_description','overall_soundscape','non_diegetic_music']
    if re.findall(r'^(\w+):\s*$',prompt,re.M)!=fields:raise ValueError('Invalid official Ref2VA sections')
    labels={int(x) for x in re.findall(r'<Picture (\d+)>',prompt)}
    if labels!=set(range(1,len(refs)+1)):raise ValueError('Prompt picture labels do not match configured references')
    inputs=g['16']['inputs']
    for name in list(inputs):
        if name.startswith('ref_images.'):del inputs[name]
    for i,slot in enumerate(profile['reference_slots']):
        a,b=slot['load'],slot['resize']
        if i>=len(refs):del g[a];del g[b];continue
        if not refs[i]['image']:raise ValueError('Empty reference')
        g[a]['inputs']['image']=refs[i]['image'];g[b]['inputs'].update(width=refs[i].get('resize_width',768),height=0)
        inputs[f'ref_images.ref_image_{i}']=[b,0]
    provenance=None;continuity=config['continuity']
    if continuity['mode']=='previous':
        previous=find_group(manifest,continuity['predecessor'])
        require_output_review(manifest,continuity['predecessor'])
        guide=previous.get('guide_input_name');p=local(previous.get('continuity_guide',''))
        if not guide or not p.is_file():raise ValueError('Missing actual preceding guide and upload name')
        provenance={'predecessor':continuity['predecessor'],'file':previous['continuity_guide'],'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'input_name':guide}
        g['17']['inputs']['image']=guide;positive=['18',0]
        prompt=prompt.replace('detailed_description:\n','detailed_description:\nThe supplied opening guide anchors the actual previous end frame at time zero. Continue without repeating completed actions or dialogue.\n',1)
    elif continuity['mode']=='cut':
        del g['17'];del g['18'];positive=['16',0]
    else:raise ValueError('Continuity mode must be cut or previous')
    g['19']['inputs']['conditioning']=positive;g['22']['inputs']['positive']=positive
    inputs.update(prompt=prompt,width=math.ceil(width/32)*32,height=math.ceil(height/32)*32,length=5+17*math.ceil((frames-5)/17))
    sam=profile['sampler'];g['21']['inputs']['steps']=sam['steps']
    if not 1<=sam['transition_step']<sam['steps']:raise ValueError('SelfLift requires low and high resolution steps')
    g['22']['inputs'].update({k:v for k,v in sam.items() if k!='steps'});g['22']['inputs']['seed']=config['seed']
    g['26']['inputs']['length']=frames;g['27']['inputs'].update(width=width,height=height)
    g['28']['inputs']['duration']=seconds;g['29']['inputs']['fps']=fps;g['31']['inputs']['batch_index']=frames-1
    prefix=profile['comfy_output_prefix'].strip('/')
    if not prefix or '..' in prefix or ':' in prefix:raise ValueError('Invalid output prefix')
    g['30']['inputs']['filename_prefix']=f'{prefix}/{key}/attempt_{attempt:02d}'
    g['32']['inputs']['filename_prefix']=f'{prefix}/guides/{key}_attempt_{attempt:02d}_end'
    return g,config,profile,provenance

def prepare(scene,group,attempt=None):
    if not scene.isalnum() or not group.isalnum():raise ValueError('Invalid scene/group')
    pair=check_pair();manifest=read(ROOT/'project.json');key=scene+'_'+group
    revision=manifest['content_revision']
    existing=[j for j in manifest['jobs'] if j.get('group')==group and j.get('scene',scene)==scene and j.get('content_revision',2)==revision]
    if any(j['status'] not in ('interrupted','error','success','failed','rejected') for j in existing):raise RuntimeError('Existing job unresolved; do not resubmit')
    used=len(existing);limit=1+manifest['settings'].get('max_retries_per_group',2)
    attempt=attempt or used+1
    if attempt<=used or attempt>limit:raise ValueError('Attempt already used or retry budget exhausted')
    g,c,p,guide=bind(key,attempt,manifest)
    snapshot=require_input_review(manifest,key,g,c,guide)
    dest=HERE/'runs'/scene/group/f'revision_{revision:02d}'/f'attempt_{attempt:02d}';dest.mkdir(parents=True,exist_ok=False)
    save(dest/'request.api.json',g)
    save(dest/'record.json',{'status':'prepared_not_submitted','content_revision':revision,'content_snapshot':snapshot,'scene':scene,'group':group,'attempt':attempt,'template':pair,'inputs':c,'profile':p,'guide':guide,'prompt_id':None,'outputs':[]})
    return dest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--scene',required=True);p.add_argument('--group',required=True);p.add_argument('--attempt',type=int);a=p.parse_args()
    print(prepare(a.scene,a.group,a.attempt))
