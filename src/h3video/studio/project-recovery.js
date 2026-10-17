// Capture one saved video task so a later selection cannot change the recovery target.
export function createVideoRecovery({getBase,kind,id,save=async()=>{}}){
 if(!['jobs','story','studio/projects'].includes(kind)||!/^[-\w]+$/.test(id||''))throw Error('이어 만들 영상 작업을 선택하세요.');
 const path=`/api/${kind}/${id}`;
 async function request(route,body,signal){
  signal?.throwIfAborted();
  const response=await fetch(getBase().replace(/\/$/,'')+route,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'content-type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:signal?AbortSignal.any([signal,AbortSignal.timeout(15000)]):AbortSignal.timeout(15000)});
  const data=await response.json();if(!response.ok)throw Error(data.error||'저장한 영상 작업을 읽지 못했습니다.');return data;
 }
 async function read(signal){
  if(kind!=='story'){const data=await request(path,undefined,signal);return {data,busy:kind==='jobs'?['pending','running'].includes(data.status):data.busy};}
  const feed=await request('/api/feed',undefined,signal),data=feed.items.find(item=>item.id===id&&item.kind==='story');
  if(!data)throw Error('저장한 영상 작업을 찾지 못했습니다.');
  return {data,busy:['pending','running','pausing'].includes(data.status)};
 }
 return {
  async engine({signal}={}){
   const {data}=await read(signal);
   const needs=kind!=='studio/projects'||data.clips.some(c=>c.pendingCandidates?.some(p=>['paused','failed','pending'].includes(p.status)));
   return needs?(kind==='jobs'&&data.task==='ref2va'?'ref2va':'fl2va'):null;
  },
  async prepare({signal}={}){
   let state=await read(signal);
   if(state.busy){await request(path+'/stop',{},signal);for(let n=0;n<120;n++){signal?.throwIfAborted();await new Promise(resolve=>setTimeout(resolve,250));state=await read(signal);if(!state.busy)break;}}
   if(state.busy)throw Error('현재 장면을 중지하고 있습니다. 잠시 후 다시 이어 만드세요.');
   signal?.throwIfAborted();await save();
  },
  async resume({maxEdge=576,signal}={}){
   const {data,busy}=await read(signal);if(busy)throw Error('영상 작업이 아직 진행 중입니다.');
   if(kind!=='studio/projects'&&data.status==='completed')return false;
   const needsEngine=kind!=='studio/projects'||data.clips.some(c=>c.pendingCandidates?.some(p=>['paused','failed','pending'].includes(p.status)));
   if(needsEngine){
    const health=await request('/api/health',undefined,signal),engine=kind==='jobs'&&data.task==='ref2va'?'ref2va':'fl2va';
    if(!health[engine])throw Error('영상 생성 엔진에 연결하지 못했습니다. 영상 엔진을 실행한 뒤 다시 이어 만드세요.');
   }
   await request(path+'/recovery',{shortEdge:maxEdge},signal);
   await request(path+(kind==='studio/projects'?'/resume':'/continue'),{},signal);
   return true;
  }
 };
}
