"""Submit one prepared request and resume the same recorded ComfyUI job."""
import argparse,json,uuid,urllib.request,urllib.error
from datetime import datetime
from prepare_job import HERE,ROOT,read,save,find_group,check_pair,reject_invalidated_content,bind,require_input_review
def request(path,data=None):
    base=read(ROOT/'project.json')['settings']['comfy_base_url']
    req=urllib.request.Request(base+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    try:return json.load(urllib.request.urlopen(req,timeout=20))
    except urllib.error.HTTPError as e:raise RuntimeError(e.read().decode(errors='replace')) from e
def submit(folder):
    folder=folder.resolve()
    if not folder.is_relative_to((HERE/'runs').resolve()):raise ValueError('Invalid run directory')
    record=read(folder/'record.json')
    d=read(ROOT/'project.json');key=record['scene']+'_'+record['group']
    reject_invalidated_content(d,key)
    if record.get('content_revision')!=d.get('content_revision'):raise RuntimeError('Prepared record belongs to an old content revision')
    if record['status']!='prepared_not_submitted':raise RuntimeError('Already attempted submission; inspect saved prompt_id')
    pair=check_pair()
    if record['template']['api_sha256']!=pair['api_sha256'] or record['template']['ui_sha256']!=pair['ui_sha256']:raise RuntimeError('Master changed since preparation')
    graph,config,profile,guide=bind(key,record['attempt'],d)
    snapshot=require_input_review(d,key,graph,config,guide)
    if record.get('content_snapshot')!=snapshot or read(folder/'request.api.json')!=graph:
        raise RuntimeError('Prepared request differs from reviewed current inputs')
    queue=request('/queue')
    if queue['queue_running'] or queue['queue_pending']:raise RuntimeError('ComfyUI busy')
    d=read(ROOT/'project.json');key=record['scene']+'_'+record['group'];group=find_group(d,key)
    pid=str(uuid.uuid4());record.update(prompt_id=pid,status='submission_pending',submitted_at=datetime.now().astimezone().isoformat())
    job={'content_revision':record['content_revision'],'scene':record['scene'],'group':record['group'],'attempt':record['attempt'],'prompt_id':pid,'status':'submission_pending','record_directory':str(folder.relative_to(ROOT))}
    d['jobs'].append(job);save(folder/'record.json',record);save(ROOT/'project.json',d)
    try:response=request('/prompt',{'prompt':read(folder/'request.api.json'),'prompt_id':pid,'client_id':'short-drama-agent','extra_data':{'project':d['title'],'segment':key}})
    except Exception as e:
        job['status']=record['status']='submission_unconfirmed';record['error']=str(e);save(folder/'record.json',record);save(ROOT/'project.json',d);raise
    save(folder/'submission.json',response)
    job['prompt_id']=record['prompt_id']=response['prompt_id'];job['status']=record['status']='queued'
    group.update(status='queued',prompt_id=response['prompt_id'],execution_record=str(folder.relative_to(ROOT)))
    d['phase']='rendering';save(folder/'record.json',record);save(ROOT/'project.json',d)
    print(json.dumps(response))
def status():
    d=read(ROOT/'project.json');j=d['jobs'][-1];history=request('/history/'+j['prompt_id']);h=history.get(j['prompt_id'])
    if h:
        folder=ROOT/j['record_directory'];save(folder/'result.json',h);j['status']=h['status']['status_str'];rec=read(folder/'record.json');rec['status']=j['status'];save(folder/'record.json',rec)
        group=find_group(d,j['scene']+'_'+j['group'])
        if group.get('status')!='stale' and j.get('content_revision',2)==d.get('content_revision',2):
            group['status']='rendered_pending_review' if j['status']=='success' else j['status']
        save(ROOT/'project.json',d)
        print(json.dumps({'status':h['status'],'outputs':h['outputs']},ensure_ascii=False))
    else:
        q=request('/queue');print(json.dumps({'prompt_id':j['prompt_id'],'running':any(x[1]==j['prompt_id'] for x in q['queue_running']),'pending':any(x[1]==j['prompt_id'] for x in q['queue_pending'])}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['submit','status']);p.add_argument('--run');a=p.parse_args()
    if a.action=='submit':
        if not a.run:p.error('--run required')
        submit(ROOT/a.run)
    else:status()
