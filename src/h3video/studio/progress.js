const operations={preview:'미리보기 합성',render:'최종 영상 출력',transcribe:'음성 인식·자막',inspect:'품질 검사',upscale:'영상 보정·업스케일'};
export function videoProgress(project,{requesting=false,action=''}={}){
 const title=project?.title||'영상 작업';
 if(requesting)return {message:`${title} · ${action==='edit-shot'?'중지하고 장면 수정 준비 중':action==='resume'?'이어 만들기 요청 중':action==='pause'?'중지 요청 중':operations[action]||'작업 요청 중'}`,fraction:null,status:'requesting'};
 const rows=(project.clips||[]).flatMap((clip,index)=>(clip.pendingCandidates||[]).map(candidate=>({...candidate,label:clip.label||'장면 '+(index+1)})));
 const active=rows.filter(row=>['pending','running'].includes(row.status)),task=project.task;
 if(active.length){
  const completed=rows.filter(row=>row.status==='completed').length,current=active.find(row=>row.status==='running')||active[0],phase=current.status==='pending'?'생성 대기 중':current.stage||'영상 생성 중';
  const measured=Number.isFinite(current.progress)?' · 현재 장면 '+Math.round(current.progress*100)+'%':'';
  const known=active.every(row=>Number.isFinite(row.progress));
  return {status:'running',completed,total:rows.length,fraction:known?(completed+active.reduce((n,row)=>n+row.progress,0))/rows.length:null,message:`${title} · ${phase} · ${completed}/${rows.length} 완료 · ${current.label}${measured}`};
 }
 if(project.busy||task&&['queued','running'].includes(task.status))return {status:'running',fraction:task?.progress??null,message:`${title} · ${operations[task?.operation]||'영상 처리'} · ${task?.status==='queued'?'작업 대기 중':task?.message||'처리 중'}`};
 if(task&&['paused','error'].includes(task.status))return {status:task.status,fraction:task.progress??null,message:`${title} · ${task.status==='error'?'실패 · '+(task.error||task.message):'중지 · 저장됨'} · ${operations[task.operation]||'영상 작업'}`};
 const failed=rows.filter(row=>['failed','paused','missing'].includes(row.status));
 if(failed.length)return {status:failed.some(row=>row.status==='failed'||row.status==='missing')?'error':'paused',fraction:null,message:`${title} · ${rows.length-failed.length}/${rows.length} 완료 · ${failed.length}개 이어 만들기 가능${failed[0].error?' · '+failed[0].error:''}`};
 return {status:'done',fraction:task?.status==='done'||rows.length?1:0,message:`${title} · ${task?.message||'저장됨 · 다음 작업을 선택하세요.'}`};
}
export function clipProgress(clip){
 const rows=clip.pendingCandidates||[],active=rows.find(row=>row.status==='running')||rows.find(row=>row.status==='pending');
 if(active)return {status:active.status,message:active.status==='pending'?'생성 대기':(active.stage||'영상 생성 중')+(Number.isFinite(active.progress)?' · '+Math.round(active.progress*100)+'%':' · 진행률 확인 중'),active:true};
 const failed=rows.find(row=>['failed','paused','missing'].includes(row.status));
 if(failed)return {status:failed.status,message:failed.status==='paused'?'중지 · 이어 만들기 가능':'실패 · 수정 후 재시도',active:false};
 return {status:'done',message:clip.locked?'확정됨':clip.selected?'영상 완성':'미생성',active:false};
}
