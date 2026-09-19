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
def refresh_registry():
    import importlib.util
    source=ROOT.parent/'.agents/skills/short-drama-agent/scripts/video_registry.py'
    if not source.is_file():
        raise RuntimeError('Video registry skill script missing: '+str(source))
    spec=importlib.util.spec_from_file_location('series_video_registry',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.refresh_workspace(ROOT.parent)

def save(p,d):
    t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
    if p.resolve()==(ROOT/'project.json').resolve():
        refresh_registry()

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
    visible=set(group.get('cast_plan',{}).get('allowed_characters',scene.get('characters',[])))
    for issue in manifest.get('character_distinction_reviews',[]):
        if issue.get('status') in ('failed','pending','stale') and visible & set(issue.get('affected_characters',issue.get('character_ids',[]))):
            raise RuntimeError('Character distinction review blocks generation: '+issue.get('reason','Review actual character references'))
    if any(x.get('status')=='stale' for x in (scene,scene.get('environment',{}),group)):
        raise RuntimeError('Scene, environment or segment is stale; revise and review before generation')

def digest(data):
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()

def resolve_scene_strategy(manifest,key,config,profile):
    scene=next(s for s in manifest['scenes'] if any(s['id']+'_'+g['id']==key for g in s['groups']))
    defaults=profile.get('scene_strategy',{})
    scene_type=config.get('scene_type',scene.get('scene_type',defaults.get('default_scene_type','drama')))
    if scene_type not in ('drama','action','mixed'):
        raise ValueError('Scene type must be drama, action or mixed')
    action={**defaults.get('action_lora',{}),**scene.get('action_lora',{}),**config.get('action_lora',{})}
    if type(action.get('enabled',False)) is not bool:
        raise ValueError('Action LoRA enabled must be an explicit boolean')
    if action.get('model') and (not isinstance(action.get('strength'),(int,float)) or not math.isfinite(action['strength']) or not 0<=action['strength']<=2):
        raise ValueError('Action LoRA strength must be finite and between 0 and 2 for this template')
    if action.get('enabled') and (not action.get('model') or action.get('strength',0)<=0):
        raise ValueError('Enabled action LoRA requires a model and positive strength')
    appearance_default={**defaults.get('appearance_lora',{}),**manifest.get('settings',{}).get('scene_strategy',{}).get('appearance_lora',{})}
    drama={**appearance_default,'enabled':appearance_default.get('enabled',False),**scene.get('appearance_lora',{}),**config.get('appearance_lora',{})}
    if type(drama.get('enabled',False)) is not bool:
        raise ValueError('Appearance LoRA enabled must be an explicit boolean')
    if drama.get('enabled') and (not drama.get('model') or type(drama.get('strength')) not in (int,float) or not math.isfinite(drama['strength']) or not 0<drama['strength']<=2):
        raise ValueError('Enabled appearance LoRA requires a model and finite positive strength <=2')
    return {'scene_type':scene_type,'main_emotion':scene.get('performance_plan',{}).get('main_emotion',''),'action_lora':action,'appearance_lora':drama}

def require_action_plan(manifest,key,strategy):
    if strategy['scene_type'] not in ('action','mixed'):
        return
    plan=find_group(manifest,key).get('action_plan',{})
    if any(not plan.get(k) for k in ('intent','initial_state','beats','final_state','camera','acceptance')):
        raise RuntimeError('Action scene requires explicit fight choreography, regardless of LoRA switch')

def require_cast_plan(group):
    plan=group.get('cast_plan')
    if plan is None:
        return  # Existing completed editions retain their original review contract.
    if plan.get('status')!='ready':
        raise RuntimeError('Cast plan requires reviewed shot-level visible people and counts')
    allowed=plan.get('allowed_characters',[])
    offscreen=plan.get('offscreen_characters',[])
    if len(allowed)!=len(set(allowed)) or set(allowed)&set(offscreen):
        raise ValueError('Cast IDs must be unique and on-screen/off-screen sets disjoint')
    for k in ('passersby_count','bit_players_count','max_simultaneous_people'):
        if type(plan.get(k)) is not int or plan[k]<0:
            raise ValueError('Explicit non-negative cast counts required')
    extras=plan['passersby_count']+plan['bit_players_count']
    if extras and not plan.get('background_roles'):
        raise ValueError('Background people require identities, placement and behavior')
    if plan['max_simultaneous_people']>len(allowed)+extras:
        raise ValueError('Visible count exceeds planned cast')
    shots=plan.get('shots',[]);end=0.0
    if not shots:
        raise ValueError('Cast time spans required')
    for shot in shots:
        a,b=shot.get('start_seconds'),shot.get('end_seconds')
        if type(a) not in (int,float) or type(b) not in (int,float) or not math.isfinite(a) or not math.isfinite(b) or abs(a-end)>1e-6 or b<=a:
            raise ValueError('Cast time spans must cover the clip without gaps or overlaps')
        visible=shot.get('allowed_characters',[]);required=shot.get('required_characters',[])
        lo,hi=shot.get('visible_count_min'),shot.get('visible_count_max')
        if len(visible)!=len(set(visible)) or len(required)!=len(set(required)) or not set(required)<=set(visible)<=set(allowed):
            raise ValueError('Shot cast must be unique and contained in allowed cast')
        if type(lo) is not int or type(hi) is not int or not len(required)<=lo<=hi<=min(plan['max_simultaneous_people'],len(visible)+extras):
            raise ValueError('Shot counts contradict required or allowed characters')
        if not shot.get('entry_exit'):
            raise ValueError('Explain cast entry, exit or unchanged presence')
        end=b
    if abs(end-group['duration_seconds'])>1e-6:
        raise ValueError('Cast time spans must cover the full duration')

def input_snapshot(manifest,key,graph,config,guide):
    group=find_group(manifest,key)
    paths=[group.get('production_outline',manifest['selected_outline']),group.get('production_script',manifest['script']),config['prompt'],
           'iworkflow/main/segments.json','iworkflow/main/profile.json',
           'iworkflow/main.ui.json','iworkflow/main/main.api.json']
    paths.extend(r['source_path'] for r in config['references'])
    if guide:paths.append(guide['file'])
    return {'revision':manifest['content_revision'],'requirements_sha256':digest(manifest['content_review']['requirements']),
            'files':{str(Path(p)):hashlib.sha256(local(p).read_bytes()).hexdigest() for p in paths},
            'performance_sha256':digest({'scene':next(s.get('performance_plan') for s in manifest['scenes'] if any(s['id']+'_'+g['id']==key for g in s['groups'])),'group':find_group(manifest,key).get('performance_plan'),'action_plan':find_group(manifest,key).get('action_plan')}),
            'music_sha256':digest(find_group(manifest,key).get('music_plan')),
            'cast_sha256':digest(find_group(manifest,key).get('cast_plan')),
            'scene_strategy_sha256':digest(config.get('scene_strategy',{})),
            'quality_plan_sha256':digest({'policy':quality_rules().VERSION,'dialogue':group.get('dialogue_plan'),'staging':group.get('action_plan',{}).get('staging'),'guard_sha256':hashlib.sha256((ROOT.parent/'.agents/skills/short-drama-agent/scripts/quality_gates.py').read_bytes()).hexdigest()}),
            'api_sha256':digest(graph)}

def require_input_review(manifest,key,graph,config,guide):
    review=manifest.get('content_review',{}).get('input_reviews',{}).get(key,{})
    quality_rules().require_input_quality(manifest,key,graph['16']['inputs']['prompt'],review)
    if review.get('status')!='passed' or any(review.get('checks',{}).get(k)!='passed' for k in ('script','references','prompt','api')):
        raise RuntimeError('Input content review is missing or incomplete')
    if find_group(manifest,key).get('performance_plan') and review.get('checks',{}).get('performance')!='passed':
        raise RuntimeError('Emotion and performance input review is incomplete')
    if config.get('scene_strategy',{}).get('scene_type') in ('action','mixed') and review.get('checks',{}).get('action')!='passed':
        raise RuntimeError('Fight choreography input review is incomplete')
    if config.get('scene_strategy',{}).get('appearance_lora',{}).get('enabled') and review.get('checks',{}).get('appearance')!='passed':
        raise RuntimeError('Appearance LoRA input review is incomplete')
    if find_group(manifest,key).get('music_plan') and review.get('checks',{}).get('music')!='passed':
        raise RuntimeError('Scene music plan input review is incomplete')
    require_cast_plan(find_group(manifest,key))
    if find_group(manifest,key).get('cast_plan') and review.get('checks',{}).get('cast')!='passed':
        raise RuntimeError('Cast identity and count input review is incomplete')
    current=input_snapshot(manifest,key,graph,config,guide)
    if review.get('snapshot')!=current:raise RuntimeError('Reviewed inputs changed; review and prepare again')
    return current

def require_first_video_approval(manifest,key,for_output=False):
    if manifest.get('settings',{}).get('review',{}).get('human_confirmation')!='first_video_only':
        return
    first_scene=next(s for s in manifest['scenes'] if s.get('groups'))
    first=first_scene['groups'][0];first_key=first_scene['id']+'_'+first['id']
    if key==first_key and not for_output:
        return
    approval=manifest.get('content_review',{}).get('first_video_human_review',{})
    if approval.get('status')!='passed' or approval.get('segment')!=first_key or not approval.get('user_answer'):
        raise RuntimeError('First project video requires human acceptance before continuing')
    if first.get('status')!='complete' or approval.get('output')!=first.get('output'):
        raise RuntimeError('First-video human acceptance no longer matches the active output')
    if approval.get('sha256')!=hashlib.sha256(local(first['output']).read_bytes()).hexdigest():
        raise RuntimeError('First-video output changed after human acceptance')

def require_first_action_approval(manifest,key,for_output=False):
    if manifest.get('settings',{}).get('review',{}).get('action_confirmation')!='first_action_video':
        return
    segments=read(HERE/'segments.json');profile=read(HERE/'profile.json')
    if resolve_scene_strategy(manifest,key,segments[key],profile)['scene_type'] not in ('action','mixed'):
        return
    ordered=[(s['id']+'_'+g['id'],g) for s in manifest['scenes'] for g in s['groups']]
    first_key,first=next((k,g) for k,g in ordered if resolve_scene_strategy(manifest,k,segments[k],profile)['scene_type'] in ('action','mixed'))
    if key==first_key and not for_output:
        return
    approval=manifest.get('content_review',{}).get('first_action_human_review',{})
    if first_key==ordered[0][0]:
        shared=manifest.get('content_review',{}).get('first_video_human_review',{})
        if shared.get('status')=='passed' and shared.get('segment')==first_key:
            approval=shared
    if approval.get('status')!='passed' or approval.get('segment')!=first_key or not approval.get('user_answer'):
        raise RuntimeError('First action-scene clip requires human acceptance before later action clips')
    if first.get('status')!='complete' or approval.get('output')!=first.get('output'):
        raise RuntimeError('First-action approval no longer matches the active clip')
    if approval.get('sha256')!=hashlib.sha256(local(first['output']).read_bytes()).hexdigest():
        raise RuntimeError('First action clip changed after human acceptance')

def require_output_review(manifest,key):
    quality_rules().require_output_quality(manifest,key,manifest.get('content_review',{}).get('output_reviews',{}).get(key,{}))
    require_first_video_approval(manifest,key,for_output=True)
    require_first_action_approval(manifest,key,for_output=True)
    group=find_group(manifest,key)
    review=manifest.get('content_review',{}).get('output_reviews',{}).get(key,{})
    if group.get('status')!='complete' or review.get('status')!='passed' or review.get('revision')!=manifest['content_revision']:
        raise RuntimeError('Previous segment has not passed current content review')
    checks=review.get('checks',{})
    if any(checks.get(k)!='passed' for k in ('technical','visual','continuity')):
        raise RuntimeError('Necessary output checks are incomplete')
    if group.get('performance_plan') and checks.get('performance')!='passed':
        raise RuntimeError('Emotion and performance output review is incomplete')
    strategy=resolve_scene_strategy(manifest,key,read(HERE/'segments.json')[key],read(HERE/'profile.json'))
    if strategy['scene_type'] in ('action','mixed') and checks.get('action')!='passed':
        raise RuntimeError('Fight choreography output review is incomplete')
    if strategy.get('appearance_lora',{}).get('enabled') and checks.get('appearance')!='passed':
        raise RuntimeError('Natural-skin, identity and fixed-style output review is incomplete')
    if group.get('cast_plan') and checks.get('cast')!='passed':
        raise RuntimeError('Cast identity and count output review is incomplete')
    policy=manifest.get('content_review',{}).get('audio_review_policy',{})
    audio_waived=(checks.get('audio')=='waived' and
                  policy.get('semantic_review_required') is False and
                  policy.get('content_revision')==manifest['content_revision'] and
                  bool(policy.get('user_instruction')))
    if checks.get('audio')!='passed' and not audio_waived:
        raise RuntimeError('Audio review is incomplete and has not been explicitly waived for this revision')
    for field in ('output','continuity_guide'):
        p=local(group[field])
        if review.get('files',{}).get(group[field])!=hashlib.sha256(p.read_bytes()).hexdigest():
            raise RuntimeError('Reviewed output or guide changed')

def bind(key,attempt,manifest=None):
    manifest=manifest or read(ROOT/'project.json');config=read(HERE/'segments.json')[key];profile=read(HERE/'profile.json')
    batch=manifest.get('production_batch',{})
    if batch and (batch.get('status')!='active' or key not in batch.get('allowed_render_keys',[])):
        raise RuntimeError('Current user batch scope does not authorize rendering this segment')
    reject_invalidated_content(manifest,key)
    require_first_video_approval(manifest,key)
    require_first_action_approval(manifest,key)
    group=find_group(manifest,key)
    if group.get('status')!='complete':require_cast_plan(group)
    if manifest.get('settings',{}).get('review',{}).get('scene_performance_planning') and group.get('status')!='complete':
        performance=group.get('performance_plan',{})
        if any(not performance.get(k) for k in ('entry','trigger','change','exit','actors','camera','acceptance')):
            raise RuntimeError('Scene emotion and segment performance plan required before generation')
    for runtime in profile.get('runtime_fixes',[]):
        if hashlib.sha256(Path(runtime['target']).read_bytes()).hexdigest()!=runtime['sha256']:
            raise RuntimeError('Reviewed runtime fix changed; verify compatibility before generation')
    g=copy.deepcopy(read(HERE/'main.api.json'));o=profile['output'];seconds=config['duration_seconds']
    strategy=resolve_scene_strategy(manifest,key,config,profile);require_action_plan(manifest,key,strategy)
    config=copy.deepcopy(config);config['scene_strategy']=strategy
    drama=strategy['appearance_lora']
    base_model=['2',0]
    if '70' in g and '71' in g:
        if drama.get('model'):
            g['70']['inputs'].update(lora_name=drama['model'],strength_model=drama['strength'])
        g['71']['inputs']['switch']=drama.get('enabled',False)
        base_model=['71',0]
    elif drama.get('enabled'):
        raise RuntimeError('Appearance LoRA branch has not been installed in this workflow')
    if drama.get('enabled'):
        directory=Path(profile['lora_directory']).resolve()
        model=(directory/drama['model']).resolve()
        if not model.is_relative_to(directory) or not model.is_file():
            raise RuntimeError('Configured appearance LoRA file is missing or outside model directory')
        if not drama.get('sha256') or hashlib.sha256(model.read_bytes()).hexdigest()!=drama['sha256']:
            raise RuntimeError('Appearance LoRA has not been verified or file changed')
    g['3']['inputs']['model']=base_model
    action=strategy['action_lora']
    if '60' in g and '61' in g:
        g['60']['inputs']['model']=base_model
        g['61']['inputs']['on_false']=base_model
        g['60']['inputs'].update(lora_name=action['model'],strength_model=action['strength'])
        g['61']['inputs']['switch']=action['enabled']
        g['3']['inputs']['model']=['61',0]
    elif action.get('enabled'):
        raise RuntimeError('Action LoRA branch has not been installed in this workflow')
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
    if drama.get('enabled') and drama.get('trigger'):
        detail=prompt.split('detailed_description:',1)[1].split('overall_soundscape:',1)[0]
        if drama['trigger'] not in detail:
            raise RuntimeError('Enabled appearance LoRA trigger must be present in the reviewed official detailed_description')
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
    elif continuity['mode']=='opening_frame':
        p=local(continuity.get('source_path',''))
        if continuity.get('review_status')!='passed' or not p.is_file() or not continuity.get('image'):
            raise ValueError('Opening frame requires an inspected actual image and upload name')
        sha=hashlib.sha256(p.read_bytes()).hexdigest()
        if sha!=continuity.get('source_sha256'):
            raise ValueError('Opening frame changed after review')
        if not any(r['source_path']==continuity['source_path'] and r['image']==continuity['image'] for r in refs):
            raise ValueError('Opening frame must match a declared Picture reference')
        provenance={'kind':'authored_opening_frame','file':continuity['source_path'],'sha256':sha,'input_name':continuity['image'],'frame_idx':0}
        g['17']['inputs']['image']=continuity['image'];g['18']['inputs']['frame_idx']=0;positive=['18',0]
        g['17']['_meta']['title']='首帧或连续性引导图（实际配置绑定）'
        g['18']['_meta']['title']='H3 画面引导（当前第0帧）'
    elif continuity['mode']=='cut':
        del g['17'];del g['18'];positive=['16',0]
    else:raise ValueError('Continuity mode must be cut, previous or opening_frame')
    ending=config.get('end_frame')
    if ending and ending.get('enabled'):
        ep=local(ending.get('source_path',''))
        if ending.get('review_status')!='passed' or not ep.is_file() or hashlib.sha256(ep.read_bytes()).hexdigest()!=ending.get('source_sha256'):
            raise ValueError('Ending guide requires an inspected unchanged actual image')
        if not any(ref['source_path']==ending['source_path'] and ref['image']==ending['image'] for ref in refs):
            raise ValueError('Ending guide must match declared Picture reference')
        frame_idx=frames-1
        g['72']['inputs']['image']=ending['image']
        g['73']['inputs'].update(positive=positive,frame_idx=frame_idx)
        positive=['73',0]
        provenance=provenance or {}
        provenance['end_frame']={'file':ending['source_path'],'sha256':ending['source_sha256'],'input_name':ending['image'],'frame_idx':frame_idx}
    else:
        g.pop('72',None);g.pop('73',None)
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
    authorization=find_group(manifest,key).get('additional_render_authorization',{})
    if authorization.get('content_revision')==revision and authorization.get('user_instruction') and authorization.get('scope'):
        extra=authorization.get('extra_attempts',0)
        if type(extra) is not int or not 0<=extra<=2:raise ValueError('Invalid bounded additional render authorization')
        limit+=extra
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
