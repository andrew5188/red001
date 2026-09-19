"""Display one configured segment in the same master UI; never submits rendering."""
import argparse,hashlib,json,urllib.request
from prepare_job import HERE,ROOT,read,save,check_pair,bind

def sync(key,attempt=1):
    check_pair()
    active,config,_,_=bind(key,attempt)
    template=read(HERE/'main.api.json');template.update(active)
    schema=json.load(urllib.request.urlopen(read(ROOT/'project.json')['settings']['comfy_base_url']+'/object_info',timeout=20))
    groups=[('模型、加速与文武戏开关',[1,2,70,71,60,61,3,4,5,6,7,8]),('参考图（按参数启用1—9张）',[10,13,11,14,12,15,*sum(([40+i,50+i] for i in range(6)),[])]),('条件与可选末帧引导',[16,17,18]),('SelfLift采样',[19,20,21,22]),('解码与输出',[23,24,25,26,27,28,29,30,31,32])]
    nodes=[];links=[];lookup={};ui_groups=[]
    for col,(title,ids) in enumerate(groups):
        y=80;x=col*680
        for nid in ids:
            keyid=str(nid);item=template[keyid];spec=schema[item['class_type']];fields={**spec['input'].get('required',{}),**spec['input'].get('optional',{})}
            names=[]
            for name in fields:
                if name in item['inputs']:names.append(name)
                names.extend(k for k in item['inputs'] if k.startswith(name+'.'))
            names.extend(k for k in item['inputs'] if k not in names)
            enabled=keyid in active;height=850 if nid==16 else 450 if nid==22 else 340 if item['class_type']=='LoadImage' else 240
            n={'id':nid,'type':item['class_type'],'title':item.get('_meta',{}).get('title',item['class_type']),'pos':[x,y],'size':[600,height],'flags':{'collapsed':not enabled},'order':len(nodes),'mode':0 if enabled else 2,'inputs':[],'outputs':[],'properties':{'Node name for S&R':item['class_type']},'widgets_values':[],'widgets_values_named':{}}
            for name in names:
                v=item['inputs'][name];f=fields.get(name,['IMAGE' if name.startswith('ref_images.') else 'COMBO',{}]);t='COMBO' if isinstance(f[0],list) else f[0]
                inp={'name':name,'type':t,'link':None}
                if not isinstance(v,list):
                    inp['widget']={'name':name};n['widgets_values'].append(v);n['widgets_values_named'][name]=v
                    if len(f)>1 and f[1].get('control_after_generate'):
                        n['widgets_values'].append('fixed');n['widgets_values_named']['control_after_generate']='fixed'
                n['inputs'].append(inp)
            if item['class_type']=='LoadImage':n['widgets_values'].append('image')
            for i,t in enumerate(spec['output']):n['outputs'].append({'name':spec.get('output_name',spec['output'])[i],'type':t,'links':[],'slot_index':i})
            nodes.append(n);lookup[keyid]=n;y+=(height+70 if enabled else 70)
        ui_groups.append({'title':title,'bounding':[x-20,10,640,y+20],'color':'#3f6278','font_size':24,'flags':{}})
    for keyid,item in template.items():
        for slot,inp in enumerate(lookup[keyid]['inputs']):
            v=item['inputs'][inp['name']]
            if isinstance(v,list):
                lid=len(links)+1;inp['link']=lid;lookup[v[0]]['outputs'][v[1]]['links'].append(lid);links.append([lid,int(v[0]),v[1],int(keyid),slot,inp['type']])
    ui={'last_node_id':max(map(int,template)),'last_link_id':len(links),'nodes':nodes,'links':links,'groups':ui_groups,'config':{},'extra':{'ds':{'scale':.23,'offset':[60,80]},'preview_segment':key},'version':.4}
    strategy=config.get('scene_strategy',{})
    note='当前预览：'+key+'\n场景类型：'+strategy.get('scene_type','drama')+'\n主情绪：'+strategy.get('main_emotion','未配置')+'\n武戏LoRA：'+('开启' if strategy.get('action_lora',{}).get('enabled') else '关闭')+'\n公共自然肤质LoRA：'+('开启' if strategy.get('appearance_lora',{}).get('enabled') else '关闭')+'\n已完成片段保留原配置；后续文戏和武戏默认启用自然肤质分支。\n场景配置在project.json，片段覆盖在main/segments.json。LoRA模型/强度及开关可在本主图编辑，执行前同步配置。'
    ui['nodes'].append({'id':62,'type':'Note','pos':[0,-360],'size':[600,300],'flags':{},'order':len(nodes),'mode':0,'inputs':[],'outputs':[],'properties':{},'widgets_values':[note],'color':'#432','bgcolor':'#653'})
    ui['last_node_id']=max(ui['last_node_id'],62)
    ui['extra']['scene_strategy']=strategy
    save(HERE/'main.api.json',template);save(HERE.parent/'main.ui.json',ui)
    save(HERE/'main.pair.json',{'api_sha256':hashlib.sha256((HERE/'main.api.json').read_bytes()).hexdigest(),'ui_sha256':hashlib.sha256((HERE.parent/'main.ui.json').read_bytes()).hexdigest(),'preview_segment':key,'template_version':5,'submitted':False,'frontend':'pending'})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('segment');p.add_argument('--attempt',type=int,default=1);a=p.parse_args();sync(a.segment,a.attempt)
