"""Edit a paused job/story while retaining every previous output and revision."""
from __future__ import annotations
import copy
import json
import shutil
import time
import re
from pathlib import Path
from dataclasses import asdict
from .client import H3Error
from . import story as ST, storyrun as SR

def _idle(state, store):
    if any((store.get(c.get('job_id')) and store.get(c['job_id']).status in ('pending','running')) for c in state['clips'] if c.get('job_id')):
        raise H3Error('현재 장면을 저장하고 일시중지가 끝난 뒤 수정해 주세요.')

@SR.locked_story
def edit_story(directory: Path, store, patch: dict):
    state=SR.refresh(directory,SR.load_state(directory),store);_idle(state,store)
    if not isinstance(patch,dict):raise H3Error('수정 내용을 JSON 객체로 보내 주세요.')
    clip=next((c for c in state['clips'] if c['id']==patch.get('clip')),None)
    if not clip:raise H3Error('수정할 장면을 확인해 주세요.')
    prompt=patch.get('prompt',clip['prompt'])
    text=patch.get('text',clip.get('text',''))
    if not isinstance(prompt,str) or not prompt.strip() or not isinstance(text,str):raise H3Error('장면 설명과 글을 확인해 주세요.')
    seconds=ST.auto_seconds(text,patch.get('seconds',clip['seconds']))[0]
    if text != clip.get('text','') and ('prompt' not in patch or prompt==clip['prompt']) and state.get('params',{}).get('narration'):
        prompt=re.sub(r' Voice-over: an off-screen storyteller.*$', '', prompt)+ST.narration_line(text)
    revision=copy.deepcopy({k:v for k,v in state.items() if k!='revisions'})
    state.setdefault('revisions',[]).append({'at':time.time(),'state':revision})
    if clip.get('job_id'):clip.setdefault('past_jobs',[]).append(clip['job_id'])
    clip.update(prompt=prompt.strip(),text=text,seconds=seconds,job_id=None,output=None,error=None,status='pending',progress=0)
    state.update(output=None,paused=True)
    SR.save_state(directory,state)
    return {'id':directory.name,'saved':True,**SR.summary(state)}

@SR.locked_story
def restore_story(directory: Path,store):
    state=SR.load_state(directory);_idle(state,store)
    revisions=state.get('revisions') or []
    if not revisions:raise H3Error('수정 전 저장본이 없습니다.')
    restored=copy.deepcopy(revisions[-1]['state'])
    current={k:v for k,v in state.items() if k!='revisions'}
    restored['revisions']=[*revisions[:-1],{'at':time.time(),'state':current}]
    restored['paused']=True
    SR.save_state(directory,restored)
    return {'id':directory.name,'restored':True,**SR.summary(restored)}

def edit_job(store,job_id:str,patch:dict):
    job=store.get(job_id)
    if not job:raise KeyError(job_id)
    if job.status in ('pending','running'):raise H3Error('일시중지가 끝난 뒤 수정해 주세요.')
    if not isinstance(patch,dict):raise H3Error('수정 내용을 확인해 주세요.')
    index=patch.get('scene')
    if not isinstance(index,int) or isinstance(index,bool) or not 0<=index<len(job.scenes):raise H3Error('수정할 장면을 확인해 주세요.')
    prompt=patch.get('prompt')
    if not isinstance(prompt,str) or not prompt.strip():raise H3Error('장면 설명을 입력해 주세요.')
    # Later chained scenes depend on the selected scene's last frame.
    directory=store.root/job.id;history=directory/'history'/str(time.time_ns());history.mkdir(parents=True)
    (history/'job.json').write_text(json.dumps(job.to_json(),ensure_ascii=False,indent=2),encoding='utf-8')
    for scene in job.scenes[index:]:
        if scene.output and Path(scene.output).is_file():shutil.copy2(scene.output,history/Path(scene.output).name)
        scene.output,scene.video_id,scene.status,scene.progress,scene.error=None,None,'pending',0,None
    if job.output and Path(job.output).is_file():shutil.copy2(job.output,history/Path(job.output).name)
    job.scenes[index].prompt=prompt.strip()
    job.output,job.error,job.status,job.pause_requested,job.finished=None,None,'paused',True,None
    store.save(job)
    return job

def restore_job(store,job_id:str):
    from .jobs import Scene
    job=store.get(job_id)
    if not job:raise KeyError(job_id)
    if job.status in ('pending','running'):raise H3Error('일시중지가 끝난 뒤 복원해 주세요.')
    directory=store.root/job.id
    histories=sorted(p for p in (directory/'history').glob('*') if (p/'job.json').is_file())
    if not histories:raise H3Error('수정 전 저장본이 없습니다.')
    previous=histories[-1]
    snapshot=json.loads((previous/'job.json').read_text(encoding='utf-8'));snapshot.pop('elapsed',None)
    # Preserve the present version as well, so restoring can be reversed.
    archive=directory/'history'/str(time.time_ns());archive.mkdir(parents=True)
    (archive/'job.json').write_text(json.dumps(job.to_json(),ensure_ascii=False,indent=2),encoding='utf-8')
    for scene in job.scenes:
        if scene.output and Path(scene.output).is_file():shutil.copy2(scene.output,archive/Path(scene.output).name)
    if job.output and Path(job.output).is_file():shutil.copy2(job.output,archive/Path(job.output).name)
    for output in [snapshot.get('output'),*(s.get('output') for s in snapshot.get('scenes',[]))]:
        if output and (previous/Path(output).name).is_file():shutil.copy2(previous/Path(output).name,output)
    for key,value in snapshot.items():
        setattr(job,key,[Scene(**s) for s in value] if key=='scenes' else value)
    if job.status!='completed':job.status,job.pause_requested='paused',True
    store.save(job)
    return job
