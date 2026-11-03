const operations={preview:'미리보기 합성',render:'최종 영상 출력',transcribe:'음성 인식·자막',inspect:'품질 검사',upscale:'프레임 보정·업스케일'};
const duration=value=>{const s=Math.max(0,Math.ceil(value));return s>=60?`${Math.floor(s/60)}분 ${s%60}초`:`${s}초`;};
export function measuredProgress(metrics){
 if(!metrics)return '';
 const parts=[];
 if(metrics.frames){
  const f=metrics.frames;
  parts.push(`완료 프레임 ${f.completed}/${f.total}`);
  const active=Object.keys(f.active||{}).map(Number).sort((a,b)=>a-b);
  if(active.length)parts.push(`처리 중 프레임 ${active.join(', ')}`);
  else if(f.current&&['retouch','upscale'].includes(metrics.phase)&&f.current>f.completed)parts.push(`현재 ${f.current}번`);
  if(f.workers>1)parts.push(`작업자 ${f.workers}개`);
  if(f.cached)parts.push(`저장본 ${f.cached}개 재사용`);
 }else if(metrics.unit==='steps'&&metrics.total){parts.push(`계산 ${metrics.completed||0}/${metrics.total}`);if(metrics.outputFrames)parts.push(`출력 ${metrics.outputFrames}프레임`);}
 if(Number.isFinite(metrics.elapsedSeconds))parts.push(`${metrics.clockIncomplete?'기록된 작업 시간':'작업 경과'} ${duration(metrics.elapsedSeconds)}`);
 if(Number.isFinite(metrics.phaseElapsedSeconds))parts.push(`현재 단계 ${duration(metrics.phaseElapsedSeconds)}`);
 if(metrics.stalled)parts.push('완료 기록 갱신 없음 · 진행 확인 필요');
 else if(Number.isFinite(metrics.ratePerSecond)&&metrics.ratePerSecond>0){
  parts.push(metrics.frames?`${(1/metrics.ratePerSecond).toFixed(1)}초/프레임`:`${(1/metrics.ratePerSecond).toFixed(1)}초/계산`);
  if(Number.isFinite(metrics.etaSeconds))parts.push(`남은 ${metrics.frames?'프레임':'계산'} 약 ${duration(metrics.etaSeconds)}`);
 }else if(!metrics.suspended&&metrics.frames&&['retouch','upscale'].includes(metrics.phase))parts.push('남은 시간 계산 중');
 if(metrics.retry)parts.push(`재시도 ${metrics.retry}/2`);
 return parts.join(' · ');
}
export function nativeProgress(item,{connectionError=false}={}){
 const rows=item.kind==='story'?item.clips||[]:item.scenes||[];
 const current=rows.find(row=>['running','in_progress'].includes(row.status))||rows.find(row=>row.status!=='completed');
 const done=rows.filter(row=>row.status==='completed').length;
 const metrics=connectionError?{...current?.metrics,suspended:true,ratePerSecond:null,etaSeconds:null}:current?.metrics;
 const position=current?rows.indexOf(current)+1:rows.length;
 const unit=item.kind==='story'?'장면':'출력 구간';
 const parts=[`${unit} ${position}/${rows.length} · 완료 ${done}개`];
 if(current){
  parts.push(current.status==='queued'?'서버 대기열':current.status==='pending'?'준비 중':current.stage||'영상 생성 중');
  if(current.segments)parts.push(`출력 구간 ${current.segments.current}/${current.segments.total}`);
  parts.push(metrics?measuredProgress(metrics):'상세 진척 확인 중');
 }else parts.push(item.status==='completed'?'완료':'이어 붙이기·마무리 중');
 if(connectionError)parts.unshift('연결 끊김 · 마지막 확인');
 return {message:parts.join(' · '),fraction:connectionError?null:item.status==='completed'?1:metrics?.fraction??null};
}
export function videoProgress(project,{requesting=false,action='',connectionError=false}={}){
 const title=project?.title||'영상 작업';
 const measured=m=>measuredProgress(connectionError?{...m,suspended:true,ratePerSecond:null,etaSeconds:null}:m);
 if(requesting)return {message:`${title} · ${action==='edit-shot'?'중지하고 장면 수정 준비 중':action==='resume'?'이어 처리 요청 중':action==='pause'?'중지 요청 중':operations[action]||'작업 요청 중'}`,fraction:null,status:'requesting'};
 const rows=(project?.clips||[]).flatMap((clip,index)=>(clip.pendingCandidates||[]).map(candidate=>({...candidate,label:clip.label||'장면 '+(index+1)})));
 const active=rows.filter(row=>['pending','running'].includes(row.status)),task=project?.task;
 let result;
 if(active.length){
  const completed=rows.filter(row=>row.status==='completed').length,current=active.find(row=>row.status==='running')||active[0];
  const phase=current.status==='pending'?'생성 대기 중':current.stage||'영상 생성 중';
  const segments=current.segments?` · 출력 구간 ${current.segments.current}/${current.segments.total}`:'';
  result={status:'running',fraction:current.metrics?.fraction??null,barLabel:'현재 생성 계산',message:`${title} · ${phase} · 생성 결과 ${completed}/${rows.length} 완료 · ${current.label}${segments}${current.metrics?' · '+measured(current.metrics):' · 상세 진척 확인 중'}`};
 }else if(project?.busy||task&&['queued','running'].includes(task.status)){
  const detail=measured(task?.metrics);
  result={status:'running',fraction:task?.metrics?.fraction??null,barLabel:task?.metrics?.frames?'프레임 처리':'현재 단계',message:`${title} · ${operations[task?.operation]||'영상 처리'} · ${task?.status==='queued'?'작업 대기 중':task?.metrics?.label||task?.message||'처리 중'}${detail?' · '+detail:''}`};
 }else if(task&&['paused','error'].includes(task.status)){
  const detail=measured({...task.metrics,suspended:true,ratePerSecond:null,etaSeconds:null});
  result={status:task.status,fraction:null,message:`${title} · ${task.status==='error'?'실패 · '+(task.error||task.message):'중지 · 저장됨'} · ${operations[task.operation]||'영상 작업'}${detail?' · '+detail:''}`};
 }else{
  const failed=rows.filter(row=>['failed','paused','missing'].includes(row.status));
  if(failed.length)result={status:failed.some(row=>['failed','missing'].includes(row.status))?'error':'paused',fraction:null,message:`${title} · ${rows.filter(row=>row.status==='completed').length}/${rows.length} 완료 · ${failed.length}개 이어 처리 가능${failed[0].error?' · '+failed[0].error:''}`};
  else if(task?.status==='done'||rows.length&&rows.every(row=>row.status==='completed'))result={status:'done',fraction:1,message:`${title} · ${task?.message||'완료'}${task?.metrics?.frames?' · '+measured(task.metrics):''}`};
  else result={status:'idle',fraction:null,message:`${title} · 저장됨 · 작업을 선택하세요.`};
 }
 if(connectionError)return {...result,status:'disconnected',fraction:null,message:`연결 끊김 · 마지막 확인: ${result.message}`};
 return result;
}
export function clipProgress(clip){
 const rows=clip.pendingCandidates||[],active=rows.find(row=>row.status==='running')||rows.find(row=>row.status==='pending');
 if(active)return {status:active.status,message:active.status==='pending'?'생성 대기':(active.stage||'영상 생성 중')+(active.metrics?' · '+measuredProgress(active.metrics):' · 상세 진척 확인 중'),active:true};
 const failed=rows.find(row=>['failed','paused','missing'].includes(row.status));
 if(failed)return {status:failed.status,message:failed.status==='paused'?'중지 · 이어 처리 가능':'실패 · 수정 후 재시도',active:false};
 return {status:'done',message:clip.locked?'확정됨':clip.selected?'영상 완성':'미생성',active:false};
}
