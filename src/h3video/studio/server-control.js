const pause=(ms,signal)=>new Promise((resolve,reject)=>{
 const done=()=>{signal?.removeEventListener('abort',abort);resolve();},timer=setTimeout(done,ms);
 const abort=()=>{clearTimeout(timer);reject(signal.reason);};
 if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
});
const helperAddress=base=>{const url=new URL(base||location.origin,location.origin);url.port='8798';url.pathname='/';url.search=url.hash=url.username=url.password='';return url.origin;};
export function mountServerControls(root,{getWebBase,kind='storybook-web',getProvider=()=> 'qwen-image',getRecovery=()=>null,onConnected=()=>{}}){
 if(!root||root.dataset.mounted)return;root.dataset.mounted='true';
 installWorkspaceLayout();
 if(!document.getElementById('maker-server-control-style')){const style=document.createElement('style');style.id='maker-server-control-style';style.textContent='.maker-server-control{box-sizing:border-box;max-width:1540px;margin:16px auto;padding:16px 20px;border:1px solid #cbd9ce;border-radius:12px;background:#f4f7ef;color:#29463b;font:14px/1.6 system-ui}.maker-server-control>div{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.maker-server-control strong{margin-right:auto}.maker-server-control button{min-height:44px;padding:9px 14px;border:1px solid #abc1b1;border-radius:8px;background:white;color:#29463b;font:600 13px system-ui;cursor:pointer}.maker-server-control button:disabled{opacity:.5;cursor:wait}.maker-server-control [data-recover-generation]{background:#29463b;color:white;border-color:#29463b}.maker-server-control progress{width:100%;height:8px;margin-top:12px;accent-color:#29463b}.maker-server-control details>div{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.maker-server-control p{margin:8px 0 0;overflow-wrap:anywhere}.maker-server-control details{margin-top:8px}.maker-server-control summary{cursor:pointer}.maker-server-control label{display:block;margin-top:10px}.maker-server-control input{box-sizing:border-box;display:block;width:100%;min-height:44px;padding:8px;border:1px solid #abc1b1;border-radius:8px;background:white;color:#29463b;font:14px system-ui}.maker-server-control [hidden]{display:none!important}.maker-server-control .maker-recovery-heading{display:flex;justify-content:space-between;gap:12px;align-items:center}.maker-server-control [data-recovery-state]{padding:3px 9px;border-radius:20px;background:#e0eadf;font-size:12px}.maker-server-control .maker-recovery-settings{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:12px 0}.maker-server-control .maker-recovery-settings label{margin:0;flex:1 1 220px}.maker-server-control select{box-sizing:border-box;width:100%;min-height:44px;padding:8px;border:1px solid #abc1b1;border-radius:8px;background:white;color:#29463b;font:14px system-ui}.maker-server-control [data-cancel-recovery]{color:#a63c29;border-color:#d4a896}.maker-server-control [data-server-log-panel]{margin-top:14px;border-top:1px solid #cbd9ce;padding-top:14px}.maker-server-control [data-server-log-panel]>div{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.maker-server-control [data-server-log-panel] label{margin:0;display:flex;gap:6px;align-items:center}.maker-server-control [data-server-log-panel] input{width:18px;min-height:18px}.maker-server-control pre{box-sizing:border-box;background:#17251e;color:#e5f1e9;padding:14px;border-radius:10px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;font:12px/1.6 ui-monospace,monospace}.maker-server-control .error{color:#a63c29}@media(max-width:560px){.maker-server-control{margin:10px;padding:14px}.maker-server-control>div strong{flex-basis:100%}.maker-server-control>div button{flex:1 1 140px}}';document.head.append(style);}
 const video=kind==='video-web';
 root.className='maker-server-control';root.setAttribute('aria-label',video?'영상 작업 복구':'이미지 생성 복구');
 root.innerHTML=`<div class="maker-recovery-heading"><strong>${video?'영상 작업 복구':'이미지 작업 복구'}</strong><span data-recovery-state>준비</span></div><div class="maker-recovery-settings"><label>${video?'남은 영상 해상도 · 짧은 변':'남은 그림 해상도 · 긴 변'}<select data-recovery-size>${video?'<option value="576">최대 576px · 가벼운 생성</option><option value="448">최대 448px · 메모리 절약</option>':'<option value="512">최대 512px · 메모리 절약</option><option value="768">최대 768px</option>'}<option value="0">현재 설정 유지</option></select></label><button type="button" data-recover-generation>${video?'저장한 영상 이어 만들기':'생성 복구 · 이어 만들기'}</button><button type="button" data-cancel-recovery hidden>복구 대기 취소</button></div><p role="status" aria-live="polite">${video?'중지한 작업을 저장하고 남은 장면부터 이어 만듭니다. 완성한 영상은 보관합니다.':'진행 중인 작업을 저장하고 이미지 모델을 다시 켠 뒤 남은 그림만 이어 만듭니다. 완성한 그림은 보관합니다.'}</p><progress data-recovery-progress max="4" value="0" hidden aria-label="복구 진행"></progress><div class="maker-server-actions"><button type="button" data-restart-web>웹 서버만 다시 켜기</button>${video?'':'<button type="button" data-restart-vllm>이미지 모델만 다시 켜기</button><button type="button" data-restart-image>선택 이미지 모델만 다시 켜기</button>'}</div><details><summary>서버 연결·상세 설정</summary><p>${video?'웹 서버 재시작은 영상 생성 엔진을 끄지 않습니다. 영상 엔진 연결 오류는 아래 상태에서 확인하세요.':'웹 서버와 이미지 모델은 각각 다시 켤 수 있습니다. 모델을 다시 불러오는 동안에는 복구 대기를 취소할 수 있습니다.'}</p><label>웹 서버 복구 주소<input type="url" data-control-web placeholder="자동 · 웹 서버 PC의 8798 포트"></label><label ${video?'hidden':''}>이미지 서버 복구 주소<input type="url" data-control-image placeholder="자동 · 이미지 서버 PC의 8798 포트"></label><label>웹 복구 접속 키 (설정한 경우)<input type="password" autocomplete="off" data-key-web></label><label ${video?'hidden':''}>이미지 복구 접속 키 (설정한 경우)<input type="password" autocomplete="off" data-key-image></label><button type="button" data-control-check>서버 연결 확인</button></details>`;
 const status=root.querySelector('[role=status]'),q=selector=>root.querySelector(selector),key='maker-control.'+kind;
 if(video)root.querySelector('.maker-server-actions').insertAdjacentHTML('beforeend','<button type="button" data-recover-video="fl2va">영상 모델 복구</button><button type="button" data-recover-video="ref2va">참고 영상 모델 복구</button>');
 root.insertAdjacentHTML('beforeend',`<button type="button" data-show-server-logs data-log-control>${video?'영상 웹 서버 로그':'이미지 서버 로그'}</button><section data-server-log-panel hidden aria-label="서버 로그"><div><strong>서버 로그</strong><button type="button" data-log-refresh data-log-control>새로고침</button><button type="button" data-log-copy data-log-control>로그 복사</button><button type="button" data-log-save data-log-control>파일 저장</button><button type="button" data-log-close data-log-control>닫기</button><label><input type="checkbox" data-log-live checked data-log-control>실시간 갱신</label></div><label><input type="checkbox" data-log-history data-log-control>이전 실행 기록 포함</label><p data-log-status role="status" aria-live="polite"></p><pre data-server-output tabindex="0" aria-label="서버 출력"></pre><details ${video?'hidden':''}><summary>이미지 요청·오류·재시도 기록</summary><pre data-request-output tabindex="0" aria-label="이미지 요청 기록"></pre></details></section>`);
 for(const group of ['web','image']){try{q('[data-control-'+group+']').value=localStorage.getItem(key+'.'+group)||'';q('[data-key-'+group+']').value=sessionStorage.getItem(key+'.key.'+group)||'';}catch{}}
 const message=(text,error=false)=>{status.textContent=text;status.classList.toggle('error',error);};
 let busy=false,controller=null,recoveryObserver=null,lastTarget=null;
 const checkCancelled=()=>controller?.signal.throwIfAborted();
 const boundedSignal=ms=>controller?AbortSignal.any([controller.signal,AbortSignal.timeout(ms)]):AbortSignal.timeout(ms);
 const imageTarget=provider=>({'qwen-image':'vllm-image','qwen-image-turbo':'image-turbo','qwen-image-quantized':'image-quantized'}[provider]||null);
 const selectedImage=()=>imageTarget(getProvider()||'qwen-image');
 const update=()=>{const target=selectedImage(),button=q('[data-restart-image]'),standard=q('[data-restart-vllm]');if(button)button.hidden=!target||target==='vllm-image';if(standard)standard.hidden=target!=='vllm-image';};update();document.addEventListener('maker:provider-change',update);document.addEventListener('change',update);document.addEventListener('click',event=>{if(event.target.closest('[data-tab]'))update();});
 root.addEventListener('input',()=>{for(const group of ['web','image'])try{localStorage.setItem(key+'.'+group,q('[data-control-'+group+']').value.trim());sessionStorage.setItem(key+'.key.'+group,q('[data-key-'+group+']').value);}catch{}});
 async function address(target,options={}){
  const group=target.endsWith('-web')||target.startsWith('video-')?'web':'image',custom=options.custom??q('[data-control-'+group+']').value.trim();let base=options.base||getWebBase()||location.origin;
  if(!custom&&group==='image'){
   const cacheKey='maker-control.image-host.'+base+'.'+target+'.'+(options.endpointIndex||0);
   try{const response=await fetch(base.replace(/\/$/,'')+'/api/config',{signal:options.signal||boundedSignal(2000)});if(!response.ok)throw Error();const config=await response.json(),endpoint=config[target==='image-turbo'?'qwenTurbo':target==='image-quantized'?'qwenQuantized':'qwen'];if(endpoint){const selected=new URL(endpoint.split(',')[options.endpointIndex||0].trim()),webHost=new URL(options.base||getWebBase()||location.origin).hostname;if(['localhost','127.0.0.1','[::1]'].includes(selected.hostname)&&!['localhost','127.0.0.1','[::1]'].includes(webHost))selected.hostname=webHost;base=selected.href;try{localStorage.setItem(cacheKey,helperAddress(base));}catch{}}}catch{try{base=localStorage.getItem(cacheKey)||base;}catch{}}
  }
  const url=new URL(custom||helperAddress(base));if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.search||url.hash)throw Error('복구 주소는 http 또는 https 주소로 입력하세요.');
  return {base:url.href.replace(/\/$/,''),secret:options.secret??q('[data-key-'+group+']').value};
 }
 const connectionError=message=>Object.assign(Error(message),{retryable:true});
 async function request(connection,target,restart=false,requestId){
  let response;try{response=await fetch(connection.base+'/api/control/'+target+(restart?'/restart':''),{method:restart?'POST':'GET',headers:{'x-maker-control':'1',...(restart?{'content-type':'application/json'}:{}),...(connection.secret?{authorization:'Bearer '+connection.secret}:{})},...(restart?{body:JSON.stringify({requestId})}:{}),signal:boundedSignal(12000)});}catch{checkCancelled();throw connectionError('복구 도우미에 연결하지 못했습니다. 서버 PC의 도우미 실행 상태·복구 주소·브라우저의 로컬 네트워크 접근을 확인하세요.');}
  checkCancelled();const data=await response.json().catch(()=>({}));if(!response.ok)throw Object.assign(Error(data.error||'복구 요청을 처리하지 못했습니다.'),{retryable:!restart&&[408,429,502,503,504].includes(response.status)});if(data.id!==target)throw Error('선택한 서버의 상태를 확인하지 못했습니다. 복구 주소를 확인하세요.');return data;
 }
 const providerFor=target=>({'vllm-image':'qwen-image','image-turbo':'qwen-image-turbo','image-quantized':'qwen-image-quantized'}[target]);
 async function webImage(target,action='status',options={}){
  const provider=providerFor(target);if(!provider||(options.customImage??q('[data-control-image]').value.trim()))return null;
  let response;
  try{response=await fetch((options.base||getWebBase()||location.origin).replace(/\/$/,'')+'/api/image-server/'+provider+(action==='status'?'':'/'+action)+(options.query||''),{method:action==='restart'?'POST':'GET',headers:action==='restart'?{'content-type':'application/json'}:{},...(action==='restart'?{body:JSON.stringify({requestId:options.requestId})}:{}),signal:options.signal||(action==='logs'?AbortSignal.timeout(10000):boundedSignal(12000))});}
  catch(error){if(options.signal?.aborted)throw error;if(action!=='logs')checkCancelled();throw connectionError(action==='logs'?'서버 로그를 읽지 못했습니다. 웹 서버 연결을 확인하세요.':'웹 서버에 연결하지 못했습니다. 웹 서버 연결 주소와 실행 상태를 확인하세요.');}
  const data=await response.json().catch(()=>({}));
  if(response.status===404||data.code==='REMOTE_IMAGE_SERVER')return null;
  if(!response.ok)throw Object.assign(Error(data.error||'이미지 서버 요청 실패 ('+response.status+')'),{retryable:action==='status'&&[408,429,502,503,504].includes(response.status)});if(data.id!==target||action==='restart'&&!data.operation?.id)throw Error('선택한 이미지 서버의 상태를 확인하지 못했습니다. 웹 서버를 업데이트하고 연결을 확인하세요.');return data;
 }
 let logTimer=null,logTarget=null,logEpoch=0,logController=null,logSelection={},logProvider=null;
 const logBase=()=>String(getWebBase()||location.origin).replace(/\/$/,'');
 const connectionKey=()=>JSON.stringify([logBase(),...['web','image'].flatMap(group=>[q('[data-control-'+group+']').value,q('[data-key-'+group+']').value])]);
 let logConnection=connectionKey();
 function invalidateLogs(){
  clearTimeout(logTimer);logEpoch++;logController?.abort();logController=null;
  q('[data-log-status]').textContent='';q('[data-server-output]').textContent='';q('[data-request-output]').textContent='';
 }
 async function refreshLogs(){
  if(q('[data-server-log-panel]').hidden)return;
  invalidateLogs();const epoch=logEpoch,abort=new AbortController();logController=abort;
  const signal=AbortSignal.any([abort.signal,AbortSignal.timeout(12000)]),base=logSelection.base||logBase(),target=logTarget||selectedImage()||kind;
  const selected={...logSelection},history=q('[data-log-history]').checked,provider=providerFor(target),group=target.endsWith('-web')||target.startsWith('video-')?'web':'image';
  const custom=q('[data-control-'+group+']').value.trim(),secret=q('[data-key-'+group+']').value,customImage=q('[data-control-image]').value.trim();
  const current=()=>epoch===logEpoch&&!q('[data-server-log-panel]').hidden&&logConnection===connectionKey();
  const query=new URLSearchParams();if(history)query.set('history','1');if(selected.requestId&&!history)query.set('requestId',selected.requestId);if(Number.isInteger(selected.endpointIndex))query.set('endpoint',selected.endpointIndex);if(selected.endpoint)query.set('expectedEndpoint',selected.endpoint);
  q('[data-log-status]').textContent='서버 상태와 기록을 확인하고 있습니다…';
  const output=async()=>{
   try{
    let data=await webImage(target,'logs',{base,signal,query:query.size?'?'+query:'',customImage});
    if(!data){const connection=await address(target,{base,signal,custom,secret});signal.throwIfAborted();const response=await fetch(connection.base+'/api/control/'+target+'/logs'+(query.size?'?'+query:''),{headers:{'x-maker-control':'1',...(connection.secret?{authorization:'Bearer '+connection.secret}:{})},signal});data=await response.json();if(!response.ok)throw Error(data.error||'서버 로그를 읽지 못했습니다.');if(data.id!==target)throw Error('선택한 서버와 다른 기록이 반환되었습니다.');if(selected.endpoint&&data.url){const expected=new URL(selected.endpoint),actual=new URL(data.url),host=new URL(connection.base).hostname;const normalized=url=>['localhost','127.0.0.1','[::1]'].includes(url.hostname)?host:url.hostname;if(normalized(expected)!==normalized(actual)||expected.port!==actual.port)throw Error('요청을 보낸 이미지 서버와 로그 서버가 다릅니다. 연결 주소를 확인하세요.');}}
    if(!current())return;
    const health=data.health?.status==='ready'?'현재 서버: 연결됨':data.health?.message?'현재 서버: '+data.health.message:'현재 연결 상태를 확인하지 못했습니다.';
    q('[data-log-status]').textContent=health+' · '+(data.label||'서버')+(data.url?' · '+data.url:'')+(data.pid?' · PID '+data.pid:'')+(selected.requestId?' · 요청 '+selected.requestId:'')+' · '+new Date().toLocaleTimeString('ko-KR');
    q('[data-server-output]').textContent=(history?'이전 실행 포함 · 현재 서버 상태와 다를 수 있습니다.\n\n':'')+(data.text||data.message||'일치하는 서버 출력이 없습니다.');
   }catch(error){if(current()){q('[data-log-status]').textContent=error.message;q('[data-server-output]').textContent='서버 출력을 가져오지 못했습니다.';}}
  };
  const requests=async()=>{
   if(video||!provider)return;
   try{
    const params=new URLSearchParams({provider});if(selected.requestId)params.set('requestId',selected.requestId);if(selected.endpoint)params.set('endpoint',selected.endpoint);
    const response=await fetch(base+'/api/image-logs?'+params,{signal}),data=await response.json();
    if(current())q('[data-request-output]').textContent=response.ok?data.text||data.message:data.error||'이미지 요청 기록을 읽지 못했습니다.';
   }catch{if(current())q('[data-request-output]').textContent='이미지 요청 기록을 가져오지 못했습니다.';}
  };
  await Promise.allSettled([output(),requests()]);
  if(current()&&q('[data-log-live]').checked)logTimer=setTimeout(refreshLogs,3000);
 }
 function showLogs(target,selection={}){
  invalidateLogs();logTarget=target||selectedImage()||kind;logSelection=selection;logProvider=selectedImage();logConnection=connectionKey();q('[data-log-history]').checked=false;q('[data-server-log-panel]').hidden=false;void refreshLogs();
 }
 function syncLogs(){
  if(q('[data-server-log-panel]').hidden)return;
  const changed=logConnection!==connectionKey();
  if(changed||(!video&&logProvider!==selectedImage()))showLogs(video?kind:selectedImage());
 }
 document.addEventListener('maker:show-logs',event=>{const {provider,...selection}=event.detail||{};showLogs(imageTarget(provider)||kind,selection);root.scrollIntoView({behavior:'smooth',block:'start'});});
 document.addEventListener('maker:provider-change',syncLogs);document.addEventListener('maker:connection-change',syncLogs);document.addEventListener('change',syncLogs);
 root.addEventListener('input',event=>{if(event.target.matches('[data-control-web],[data-control-image],[data-key-web],[data-key-image]'))syncLogs();});
 q('[data-show-server-logs]').onclick=()=>showLogs(video?kind:selectedImage());
 q('[data-log-refresh]').onclick=()=>{if(logConnection!==connectionKey())showLogs(video?kind:selectedImage());else void refreshLogs();};
 q('[data-log-history]').onchange=()=>void refreshLogs();
 q('[data-log-live]').onchange=()=>{clearTimeout(logTimer);if(q('[data-log-live]').checked)void refreshLogs();};
 q('[data-log-close]').onclick=()=>{q('[data-server-log-panel]').hidden=true;invalidateLogs();};
 const logText=()=>[q('[data-log-status]').textContent,q('[data-server-output]').textContent,q('[data-request-output]').textContent].filter(Boolean).join('\n\n');
 q('[data-log-copy]').onclick=async()=>{try{await navigator.clipboard.writeText(logText());q('[data-log-status]').textContent='로그를 복사했습니다.';}catch{const text=document.createElement('textarea');text.value=logText();text.style.position='fixed';text.style.opacity='0';root.append(text);text.select();const copied=document.execCommand('copy');text.remove();q('[data-log-status]').textContent=copied?'로그를 복사했습니다.':'파일 저장을 누르거나 로그를 선택해 복사하세요.';}};
 q('[data-log-save]').onclick=()=>{const url=URL.createObjectURL(new Blob([logText()],{type:'text/plain;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download='image-server-'+new Date().toISOString().replace(/[:.]/g,'-')+'.log';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
 async function restart(target){
  lastTarget=target;
  // Keep the destination fixed until this operation ends, including after a reconnect.
  const base=String(getWebBase()||location.origin).replace(/\/$/,''),customImage=q('[data-control-image]').value.trim(),requestId=crypto.randomUUID();
  const selected=logTarget===target&&(!logSelection.base||logSelection.base.replace(/\/$/,'')===base)?{...logSelection}:{};
  const query=new URLSearchParams();if(Number.isInteger(selected.endpointIndex))query.set('endpoint',selected.endpointIndex);if(selected.endpoint)query.set('expectedEndpoint',selected.endpoint);
  const options={base,customImage,requestId,query:query.size?'?'+query:'',endpointIndex:selected.endpointIndex};
  let direct=Boolean(providerFor(target)&&!customImage),connection=null,data=null,uncertain=false;
  try{if(direct){data=await webImage(target,'restart',options);if(!data)direct=false;}if(!direct){connection=await address(target,{base,endpointIndex:selected.endpointIndex});checkCancelled();data=await request(connection,target,true,requestId);}}
  catch(error){if(!error.retryable)throw error;uncertain=true;message('재시작 응답을 받지 못해 접수 상태를 다시 확인하고 있습니다…');}
  const read=()=>direct?webImage(target,'status',options):request(connection,target);
  let operation=data?.operation?.id,failures=0,confirmations=0;
  for(let n=0;n<1800;n++){
   checkCancelled();
   if(data){
    if(uncertain){if(data.operation?.requestId===requestId){uncertain=false;operation=data.operation.id;}else if(++confirmations>=5)throw Error('재시작 접수 여부를 확인하지 못했습니다. 서버 로그와 현재 상태를 확인한 뒤 다시 시도하세요.');}
    if(!uncertain){
     if(!operation||data.operation?.id!==operation)throw Error('재시작 요청이 변경되었습니다. 서버 상태를 확인한 뒤 다시 시도하세요.');
     message(data.label+' · '+data.message);
     if(data.operation.status==='ready'){if(data.status!=='ready')throw Error('재시작 후 서버가 응답하지 않습니다. 서버 로그를 확인하세요.');return;}
     if(['failed','timeout'].includes(data.operation.status))throw Error(data.operation.error||data.message);
    }
   }
   await pause(1000,controller.signal);
   try{data=await read();if(!data)throw Error('이미지 서버 연결 설정이 변경되었습니다. 현재 주소를 확인하세요.');failures=0;}
   catch(error){checkCancelled();if(!error.retryable||++failures>=5)throw error;data=null;message('서버가 다시 연결되는 동안 상태를 다시 확인하고 있습니다… ('+failures+'/5)');}
  }
  throw Error('모델 시작 확인 시간이 지났습니다. 고급 설정에서 연결을 확인하세요.');
 }
 async function exclusive(action){
  if(busy){message('앞선 재시작 요청을 처리 중입니다. 복구 대기 취소 또는 서버 로그를 확인하세요.');return;}busy=true;controller=new AbortController();const trigger=document.activeElement?.closest('button');const label=trigger&&root.contains(trigger)?trigger.textContent:null;if(label)trigger.textContent='요청 처리 중…';
  const regions=[];const collect=el=>{if(el===root)return;if(!el.contains(root)){regions.push(el);return;}for(const child of el.children)if(!['SCRIPT','STYLE'].includes(child.tagName))collect(child);};for(const main of document.querySelectorAll('main'))collect(main);
  const panels=regions.map(el=>[el,el.inert]);for(const [el]of panels)el.inert=true;
  const cancel=q('[data-cancel-recovery]'),badge=q('[data-recovery-state]');cancel.hidden=false;badge.textContent='복구 중';
  const controls=[...root.querySelectorAll('button,input,select')].map(el=>[el,el.disabled]);
  root.setAttribute('aria-busy','true');for(const [el,disabled]of controls)el.disabled=disabled||el!==cancel&&!el.matches('[data-log-control]');
  try{await action();checkCancelled();badge.textContent='연결됨';}
  catch(error){
   if(controller.signal.aborted){badge.textContent='대기 취소됨';message('복구 대기를 취소했습니다. 저장한 결과는 보관됩니다. 이미 접수된 서버 재시작이나 생성 요청은 계속될 수 있습니다. 아래 작업의 진행 상태를 확인하세요.');}
   else{badge.textContent='확인 필요';message('복구를 완료하지 못했습니다. '+error.message+' 저장한 결과와 입력은 유지됩니다.',true);q('details').open=true;if(lastTarget)showLogs(lastTarget);}
  }
  finally{if(controller.signal.aborted)void recoveryObserver?.refresh?.().catch(()=>{});recoveryObserver=null;for(const [el,inert]of panels)el.inert=inert;busy=false;controller=null;cancel.hidden=true;root.removeAttribute('aria-busy');for(const [el,disabled]of controls)el.disabled=disabled;update();if(label)trigger.textContent=label;}
 }
 q('[data-cancel-recovery]').onclick=()=>{controller?.abort(new DOMException('복구 대기 취소','AbortError'));};
 async function run(target,check=false){lastTarget=target;return exclusive(async()=>{
  message(check?'복구 연결을 확인하고 있습니다…':'서버를 다시 켜고 있습니다…');
  if(check){const data=await request(await address(target),target);if(data.status!=='ready')throw Error(data.label+' · '+data.message);message(data.label+' · '+data.message);return;}
  await restart(target);checkCancelled();await onConnected(target);message('다시 연결되었습니다. 저장한 결과는 보관되어 있습니다.');
 });}
 async function recover(){return exclusive(async()=>{
  const recovery=getRecovery(),progress=q('[data-recovery-progress]');progress.hidden=false;progress.value=0;recoveryObserver=recovery;
  message('1/4 · 작업실 연결을 확인하고 있습니다…');
  let online=false;try{online=(await fetch((getWebBase()||location.origin).replace(/\/$/,'')+'/api/runtime',{signal:boundedSignal(3000)})).ok;}catch{}
  checkCancelled();if(!online)await restart(kind);checkCancelled();
  progress.value=1;
  if(video){
   if(recovery){message('2/4 · 선택한 영상 작업을 중지하고 저장하고 있습니다…');await recovery.prepare({signal:controller.signal});checkCancelled();progress.value=2;message('3/4 · 영상 엔진과 저장한 장면을 확인하고 있습니다…');const engine=await recovery.engine?.({signal:controller.signal});if(engine){const health=await fetch((getWebBase()||location.origin).replace(/\/$/,'')+'/api/health',{signal:boundedSignal(15000)}).then(response=>response.json());if(!health[engine])await recoverVideoEngine(engine);}checkCancelled();const resumed=await recovery.resume({maxEdge:Number(q('[data-recovery-size]').value),signal:controller.signal});checkCancelled();await onConnected(kind);progress.value=4;q('details').open=false;message(resumed?'복구 완료 · 완성한 영상은 보관하고 남은 장면부터 이어 만들고 있습니다.':'복구 완료 · 작업실에 연결되었습니다. 저장한 영상을 선택하면 이어 만들 수 있습니다.');}
   else{await onConnected(kind);checkCancelled();progress.value=4;q('details').open=false;message('복구 완료 · 작업실에 다시 연결되었습니다. 중지한 영상은 아래 작업 목록에서 선택해 이어 만드세요.');}return;
  }
  const provider=await recovery?.resolve({signal:controller.signal})||getProvider()||'qwen-image',target=imageTarget(provider);
  if(!target&&!['mock','claude-svg','pollinations','openai'].includes(provider))throw Error('이 모델은 자동 재시작을 지원하지 않습니다. 모델 연결 설정을 확인하세요.');
  checkCancelled();message('2/4 · 진행 중인 그림을 중지하고 수정 내용을 저장하고 있습니다…');
  await recovery?.prepare({signal:controller.signal});checkCancelled();progress.value=2;
  if(target){message('3/4 · 이미지 모델을 다시 불러오고 있습니다. 준비되면 자동으로 이어 만듭니다…');await restart(target);}
  checkCancelled();progress.value=3;message('4/4 · 남은 그림을 메모리 절약 설정으로 이어 만들고 있습니다…');
  const edge=Number(q('[data-recovery-size]').value),resumed=await recovery?.resume({maxEdge:edge,signal:controller.signal});checkCancelled();await onConnected(target||kind);progress.value=4;q('details').open=false;
  message(resumed?`복구 완료 · 완성한 그림은 보관하고, ${edge?'남은 그림만 최대 '+edge+'px로':'남은 그림을 현재 설정으로'} 이어 만들고 있습니다.`:'복구 완료 · 이미지 생성에 다시 연결되었습니다. 완성한 그림과 입력은 보관되어 있습니다.');
 });}
 q('[data-recover-generation]').onclick=recover;
 q('[data-restart-web]').onclick=()=>run(kind);
 if(!video){q('[data-restart-vllm]').onclick=q('[data-restart-image]').onclick=()=>{const target=selectedImage();if(target)return run(target);return exclusive(async()=>{throw Error('선택한 모델은 이 PC의 이미지 모델 재시작 대상이 아닙니다.');});};}
 async function recoverVideoEngine(target){
  const base=(getWebBase()||location.origin).replace(/\/$/,'');
  message('영상 모델을 복구하고 있습니다. 기존 로컬 모델을 다시 사용합니다.');
  const response=await fetch(base+'/api/engines/'+target+'/recover',{method:'POST',headers:{'content-type':'application/json'},body:'{}',signal:boundedSignal(12000)}),data=await response.json();
  if(!response.ok||!data.id){await restart('video-'+target);checkCancelled();await onConnected(kind);message('영상 모델을 다시 시작했습니다. 저장한 작업에서 이어 만드세요.');return;}
  for(let n=0;n<1800;n++){
   checkCancelled();await pause(1000,controller.signal);
   const response=await fetch(base+'/api/engines/'+target+'/'+data.id,{signal:boundedSignal(10000)}),state=await response.json();
   if(!response.ok)throw Error(state.error||'영상 모델 복구 상태 확인 실패');
   if(state.status==='failed')throw Error(state.error||'영상 모델 복구 실패');
   if(state.status==='completed'){await onConnected(kind);message('영상 모델 복구 완료 · 저장한 영상은 보관되어 있습니다. 이어 만들기를 누르세요.');return;}
  }
  throw Error('영상 모델 시작 확인 시간이 지났습니다. 서버 로그를 확인하세요.');
 }
 if(video)for(const button of root.querySelectorAll('[data-recover-video]'))button.onclick=()=>exclusive(async()=>{await getRecovery()?.prepare({signal:controller.signal});checkCancelled();await recoverVideoEngine(button.dataset.recoverVideo);});
 q('[data-control-check]').onclick=()=>run(kind,true);
 return {restart:target=>run(target||kind),recover,showLogs};
}

function installWorkspaceLayout(){
 if(document.getElementById('maker-workspace-layout'))return;
 const style=document.createElement('style');style.id='maker-workspace-layout';
 style.textContent=`
 .maker-server-control{width:auto;min-width:0;margin:16px clamp(16px,3vw,42px);font-size:13px}
 .maker-server-control *{box-sizing:border-box;min-width:0}
 .maker-server-control .maker-recovery-heading{flex-wrap:nowrap}
 .maker-server-control .maker-recovery-heading strong{flex-basis:auto;margin:0;font-size:15px}
 .maker-server-control [data-recovery-state]{flex-shrink:0;white-space:nowrap}
 .maker-server-control button{max-width:100%;overflow-wrap:anywhere;line-height:1.5}
 .maker-server-control .maker-server-actions{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(180px,100%),1fr));margin:12px 0 8px}
 .maker-server-control .maker-recovery-settings label{flex:1 1 200px;margin:0}
 .maker-server-control>p{font-size:12px;line-height:1.6}
 .maker-server-control>details>label{margin:12px 0}
 .maker-server-control pre{max-width:100%;tab-size:2}
 body:has(#jobControls,#imageJobDock,#liveJobControls){padding-bottom:var(--maker-dock-space,0px)!important}
 #jobControls,#imageJobDock,#liveJobControls{max-height:45dvh;overflow-y:auto;overscroll-behavior:contain}
 @media(max-width:560px){
 .maker-server-control{margin:12px 16px;padding:14px}
 .maker-server-control .maker-recovery-heading strong{flex-basis:auto}
 .maker-server-control .maker-server-actions{grid-template-columns:repeat(2,minmax(0,1fr))}
 .maker-server-control .maker-server-actions button{font-size:12px;padding:8px}
 .maker-server-control .maker-recovery-settings{align-items:stretch;gap:8px}
 .maker-server-control .maker-recovery-settings label{flex-basis:100%}
 .maker-server-control .maker-recovery-settings button{flex:1 1 130px}
 .maker-server-control [data-server-log-panel]>div>strong{flex-basis:100%}
 }
 `;document.head.append(style);
 const docks=[...document.querySelectorAll('#jobControls,#imageJobDock,#liveJobControls')];
 let scheduled=false;
 const update=()=>{scheduled=false;const height=Math.max(0,...docks.map(el=>el.getBoundingClientRect().height));document.body.style.setProperty('--maker-dock-space',height?`${Math.ceil(height)+16}px`:'0px');};
 const schedule=()=>{if(!scheduled){scheduled=true;requestAnimationFrame(update);}};
 const size=new ResizeObserver(schedule),visibility=new MutationObserver(schedule);
 for(const dock of docks){size.observe(dock);visibility.observe(dock,{attributes:true,attributeFilter:['hidden','style'],childList:true,subtree:true});}
 window.addEventListener('resize',schedule);schedule();
}
