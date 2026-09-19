"""Build a read-only-derived video ledger; never submits, deletes, or approves media."""
import argparse, hashlib, json, re
from datetime import datetime
from pathlib import Path

VIDEO_SUFFIXES={".mp4",".mov",".mkv",".webm"}

def read(path, default=None):
    if not path.is_file(): return default
    return json.loads(path.read_text(encoding="utf-8-sig"))

def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    temp.replace(path)

def local(root, name):
    path=(root/name).resolve()
    if not path.is_relative_to(root.resolve()): raise ValueError("Registry path outside project")
    return path

def norm(name):
    return str(name or "").replace("\\","/")

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()

def media(path):
    result={"bytes":path.stat().st_size,"sha256":sha(path)}
    try:
        import av
        with av.open(str(path)) as c:
            v=c.streams.video[0]
            result.update(width=v.width,height=v.height,fps=float(v.average_rate),
                duration_seconds=float(v.duration*v.time_base) if v.duration is not None else None,
                has_audio=bool(c.streams.audio))
    except ImportError: result["metadata_status"]="decoder_unavailable"
    except Exception as exc: result["metadata_error"]=str(exc)
    return result

def build_project(root):
    m=read(root/"project.json")
    previous=read(root/"iworkflow/main/video_registry.json",{})
    prefix=previous.get("project_id") or "P"+hashlib.sha256((m.get("created_at","")+"|"+m["title"]).encode()).hexdigest()[:6].upper()
    groups={s["id"]+"_"+g["id"]:(s,g) for s in m["scenes"] for g in s["groups"]}
    failures={norm(f["output"]):f for _,g in groups.values() for f in g.get("failed_outputs",[]) if f.get("output")}
    files=sorted(x for x in root.rglob("*") if x.is_file() and x.suffix.lower() in VIDEO_SUFFIXES and ".git" not in x.parts)
    assigned=set(); records=[]
    for index,job in enumerate(m.get("jobs",[]),1):
        folder=local(root,job["record_directory"]) if job.get("record_directory") else None
        rec=read(folder/"record.json",{}) if folder else {}
        scene=job.get("scene") or job.get("stem","").split("_")[0] or "unknown"
        group=job.get("group","unknown")
        revision=job.get("content_revision",rec.get("content_revision"))
        rev=f"R{revision:02d}" if isinstance(revision,int) else "legacy"
        attempt=job.get("attempt",index)
        rid=f"{prefix}-{scene}-{group}-{rev}-A{attempt:02d}"
        relative_run=norm(job.get("record_directory"))
        relative_out=relative_run.replace("iworkflow/main/runs/","03_分场制作/",1)
        matched=[f for f in files if relative_out and norm(f.parent.relative_to(root))==relative_out]
        candidates=matched or [None]
        for vi,path in enumerate(candidates,1):
            key=scene+"_"+group; scene_data,g=groups.get(key,({},{}))
            review=m.get("content_review",{}).get("output_reviews",{}).get(key,{})
            rel=norm(path.relative_to(root)) if path else None
            failure=failures.get(rel,{})
            state="无视频文件";issue=job.get("status_note","")
            if path:
                assigned.add(path)
                state="历史版本（非当前有效）"
                if failure: state="失败";issue=failure.get("reason","内容验收失败")
                elif rel==norm(g.get("output")):
                    state={"complete":"已验收","technical_checked":"待画面验收","technical_failed":"技术失败","stale":"已失效","failed":"失败"}.get(g.get("status"),"待验收")
                    if state=="已验收" and review.get("status")!="passed":state="待验收"
                    issue=review.get("failure",g.get("failure_reason","")) if state in ("失败","技术失败","已失效") else ""
                rp=failure.get("review") or (g.get("review") if rel==norm(g.get("output")) else None)
                if not rp and (path.parent/"review/check.json").is_file():rp=norm((path.parent/"review/check.json").relative_to(root))
            else:
                rp=None
                if job.get("status") in ("queued","submission_pending","submission_unconfirmed"):state="生成中／待核实"
                elif job.get("status") in ("error","failed","rejected"):state="执行失败（无视频）"
                elif job.get("status") in ("interrupted","stopped_unverified"):state="已中断（无视频）"
                elif job.get("status")=="success":state="未归档或文件缺失"
            item={"id":rid+(f"-{vi}" if len(candidates)>1 else ""),"project":m["title"],"kind":"segment",
                "scene":scene,"group":group,"scene_title":scene_data.get("title",""),"revision":revision,
                "attempt":attempt,"prompt_id":job.get("prompt_id"),"execution_status":job.get("status"),
                "status":state,"issue":issue,"output":rel,"review":rp,
                "prompt":rec.get("inputs",{}).get("prompt"),
                "execution_api":norm((folder/"request.api.json").relative_to(root)) if folder and (folder/"request.api.json").is_file() else None,
                "audio_review":review.get("checks",{}).get("audio") if rel==norm(g.get("output")) else None,
                "replaces":[]}
            if path:
                item.update(media(path))
                if item["status"]=="已验收":
                    expected={norm(k):v for k,v in review.get("files",{}).items()}.get(rel)
                    if expected!=item["sha256"]:
                        item["status"]="已失效（验收指纹不匹配）"
                        item["issue"]="当前视频没有匹配的验收指纹，需复核"
                related=[x for x in m.get("video_issues",[]) if x.get("status") not in ("resolved","dismissed") and
                    (x.get("record_id")==item["id"] or (x.get("output") and norm(x["output"])==rel) or rel in [norm(a) for a in x.get("affected_outputs",[])] or
                     set(x.get("affected_characters",[])) & set(scene_data.get("characters",[])))]
                if related:
                    item["reported_issues"]=[x["issue_id"] for x in related]
                    item["status"]="失败／另有用户反馈" if failure else "待修复（用户反馈）"
                    prior=item.get("issue","")
                    item["issue"]=(prior+"；" if prior else "")+"；".join(x.get("feedback","") for x in related)
                cp=path.parent/"review/contact_sheet.jpg"
                item["contact_sheet"]=norm(cp.relative_to(root)) if cp.is_file() else None
            records.append(item)
    editions={norm(x["output"]):x for x in m.get("completed_editions",[]) if x.get("output")}
    for path in files:
        if path in assigned:continue
        rel=norm(path.relative_to(root));facts=media(path)
        edition=editions.get(rel);is_final=rel.startswith("04_全片输出/")
        state="待核对归属";issue="文件存在，但未匹配到执行记录"
        review_path=None
        if is_final:
            state="候选成片／待验收";issue=""
            if edition:
                er=edition.get("review",{})
                state="已验收成片" if er.get("status")=="passed" and er.get("sha256")==facts["sha256"] else "成片需复核"
                review_path=er.get("evidence")
        item={"id":prefix+("-FINAL-" if is_final else "-FILE-")+facts["sha256"][:10].upper(),
            "project":m["title"],"kind":"final" if is_final else "unmatched","scene":"全片" if is_final else "",
            "group":"","scene_title":edition.get("name","") if edition else "","revision":None,"attempt":None,
            "status":state,"issue":issue,"output":rel,"review":review_path,"prompt":None,"execution_api":None,
            "audio_review":edition.get("review",{}).get("checks",{}).get("audio") if edition else None,**facts}
        related=[x for x in m.get("video_issues",[]) if x.get("status") not in ("resolved","dismissed","resolved_by_replacement") and
            (x.get("record_id")==item["id"] or (x.get("output") and norm(x["output"])==rel) or
             rel in [norm(a) for a in x.get("affected_outputs",[])])]
        if related:
            item["reported_issues"]=[x["issue_id"] for x in related]
            item["status"]="待修复成片（用户反馈）" if is_final else "待修复（用户反馈）"
            item["issue"]="；".join(x.get("feedback","") for x in related)
        records.append(item)
    # Explicit attempt history; do not claim a new version replaces an old one until reviewed.
    for row in records:
        if row["kind"]=="segment" and row["output"]:
            row["earlier_attempt_ids"]=[x["id"] for x in records if x["kind"]=="segment" and
                (x["scene"],x["group"],x["revision"])==(row["scene"],row["group"],row["revision"]) and
                x["attempt"]<row["attempt"]]
    data={"schema_version":1,"generated_at":datetime.now().astimezone().isoformat(),
        "project":m["title"],"project_id":prefix,"source":"project.json + immutable runs + actual media files",
        "records":records,"planned_segments":[{"key":k,"status":g.get("status")} for k,(_,g) in groups.items() if not g.get("output")]}
    write(root/"iworkflow/main/video_registry.json",data)
    return data

def cell(value):
    return str(value or "").replace("|","/").replace("\n"," ").replace("\r"," ")

def link(root,path,label):
    if not path:return "—"
    target=local(root,path)
    return f"[{label}](<{target.as_posix()}>)" if target.is_file() else "文件缺失"

def refresh_workspace(workspace):
    workspace=Path(workspace).resolve()
    manifests=([workspace/"project.json"] if (workspace/"project.json").is_file() else [])+sorted(workspace.glob("*/project.json"))
    text=["# 视频总登记","","登记由项目清单、执行记录和实际文件自动生成，不代表所有视频都已通过验收。",
        "反馈时可直接给出登记编号和问题时间，例如：重做某编号，2–4秒出现多余人物。",
        "重做生成新尝试并保留旧记录；受影响的衔接与合成需重新核对。音频 waived 表示未试听、按已批准策略继续。",""]
    total=0
    for mp in manifests:
        root=mp.parent;m=read(mp)
        if not isinstance(m,dict) or not all(k in m for k in ("title","scenes")):continue
        data=build_project(root);total+=len(data["records"])
        text += ["## "+m["title"],"", "| 编号 | 场次/版本 | 状态 | 时长/尺寸 | 问题或限制 | 视频与证据 |",
                 "| --- | --- | --- | --- | --- | --- |"]
        for row in data["records"]:
            duration=row.get("duration_seconds");spec=(f"{duration:.2f}s" if duration is not None else "—")
            if row.get("width"):spec+=f" / {row['width']}×{row['height']}"
            issue=row["issue"][:160]
            if row.get("audio_review")=="waived":issue=(issue+"；" if issue else "")+"声音主观质量未验证"
            evidence=" · ".join([link(root,row.get("output"),"播放"),link(root,row.get("contact_sheet"),"抽帧"),link(root,row.get("review"),"检查"),link(root,row.get("execution_api"),"实际工作流")])
            version=f"{row['scene']} {row['group']} "+(f"第{row['attempt']}次" if row.get("attempt") is not None else row.get("scene_title",""))
            text.append("| "+" | ".join([cell(row["id"]),cell(version),cell(row["status"]),spec,cell(issue),evidence])+" |")
        text += ["",f"本项目登记 {len(data['records'])} 条执行或视频记录；尚无有效输出的片段 {len(data['planned_segments'])} 个。",""]
    text.append("更新："+datetime.now().astimezone().isoformat())
    target=workspace/"视频登记.md";temp=target.with_suffix(".md.tmp")
    temp.write_text("\n".join(text)+"\n",encoding="utf-8");temp.replace(target)
    return {"path":str(target),"records":total}

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(refresh_workspace(args.workspace),ensure_ascii=False))
