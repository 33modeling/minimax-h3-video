const pause=(ms,signal)=>new Promise((resolve,reject)=>{
 const done=()=>{signal?.removeEventListener('abort',abort);resolve();},timer=setTimeout(done,ms);
 const abort=()=>{clearTimeout(timer);reject(signal.reason);};
 if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
});
const helperAddress=base=>{const url=new URL(base||location.origin,location.origin);url.port='8798';url.pathname='/';url.search=url.hash=url.username=url.password='';return url.origin;};
export function mountServerControls(root,{getWebBase,kind='storybook-web',getProvider=()=> 'qwen-image',getRecovery=()=>null,onConnected=()=>{}}){
 if(!root||root.dataset.mounted)return;root.dataset.mounted='true';
 if(!document.getElementById('maker-server-control-style')){const style=document.createElement('style');style.id='maker-server-control-style';style.textContent='.maker-server-control{box-sizing:border-box;max-width:1540px;margin:16px auto;padding:16px 20px;border:1px solid #cbd9ce;border-radius:12px;background:#f4f7ef;color:#29463b;font:14px/1.6 system-ui}.maker-server-control>div{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.maker-server-control strong{margin-right:auto}.maker-server-control button{min-height:44px;padding:9px 14px;border:1px solid #abc1b1;border-radius:8px;background:white;color:#29463b;font:600 13px system-ui;cursor:pointer}.maker-server-control button:disabled{opacity:.5;cursor:wait}.maker-server-control [data-recover-generation]{background:#29463b;color:white;border-color:#29463b}.maker-server-control progress{width:100%;height:8px;margin-top:12px;accent-color:#29463b}.maker-server-control details>div{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.maker-server-control p{margin:8px 0 0;overflow-wrap:anywhere}.maker-server-control details{margin-top:8px}.maker-server-control summary{cursor:pointer}.maker-server-control label{display:block;margin-top:10px}.maker-server-control input{box-sizing:border-box;display:block;width:100%;min-height:44px;padding:8px;border:1px solid #abc1b1;border-radius:8px;background:white;color:#29463b;font:14px system-ui}.maker-server-control [hidden]{display:none!important}.maker-server-control .maker-recovery-heading{display:flex;justify-content:space-between;gap:12px;align-items:center}.maker-server-control [data-recovery-state]{padding:3px 9px;border-radius:20px;background:#e0eadf;font-size:12px}.maker-server-control .maker-recovery-settings{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:12px 0}.maker-server-control .maker-recovery-settings label{margin:0;flex:1 1 220px}.maker-server-control select{box-sizing:border-box;width:100%;min-height:44px;padding:8px;border:1px solid #abc1b1;border-radius:8px;background:white;color:#29463b;font:14px system-ui}.maker-server-control [data-cancel-recovery]{color:#a63c29;border-color:#d4a896}.maker-server-control .error{color:#a63c29}@media(max-width:560px){.maker-server-control{margin:10px;padding:14px}.maker-server-control>div strong{flex-basis:100%}.maker-server-control>div button{flex:1 1 140px}}';document.head.append(style);}
 const video=kind==='video-web';
 root.className='maker-server-control';root.setAttribute('aria-label',video?'영상 작업 복구':'이미지 생성 복구');
 root.innerHTML=`<div class="maker-recovery-heading"><strong>${video?'영상 작업 복구':'이미지 작업 복구'}</strong><span data-recovery-state>준비</span></div><div class="maker-recovery-settings"><label>${video?'남은 영상 해상도 · 짧은 변':'남은 그림 해상도 · 긴 변'}<select data-recovery-size>${video?'<option value="576">최대 576px · 가벼운 생성</option><option value="448">최대 448px · 메모리 절약</option>':'<option value="512">최대 512px · 메모리 절약</option><option value="768">최대 768px</option>'}<option value="0">현재 설정 유지</option></select></label><button type="button" data-recover-generation>${video?'저장한 영상 이어 만들기':'생성 복구 · 이어 만들기'}</button><button type="button" data-cancel-recovery hidden>복구 대기 취소</button></div><p role="status" aria-live="polite">${video?'중지한 작업을 저장하고 남은 장면부터 이어 만듭니다. 완성한 영상은 보관합니다.':'진행 중인 작업을 저장하고 이미지 모델을 다시 켠 뒤 남은 그림만 이어 만듭니다. 완성한 그림은 보관합니다.'}</p><progress data-recovery-progress max="4" value="0" hidden aria-label="복구 진행"></progress><div class="maker-server-actions"><button type="button" data-restart-web>웹 서버만 다시 켜기</button>${video?'':'<button type="button" data-restart-vllm>이미지 모델만 다시 켜기</button><button type="button" data-restart-image>선택 이미지 모델만 다시 켜기</button>'}</div><details><summary>서버 연결·상세 설정</summary><p>${video?'웹 서버 재시작은 영상 생성 엔진을 끄지 않습니다. 영상 엔진 연결 오류는 아래 상태에서 확인하세요.':'웹 서버와 이미지 모델은 각각 다시 켤 수 있습니다. 모델을 다시 불러오는 동안에는 복구 대기를 취소할 수 있습니다.'}</p><label>웹 서버 복구 주소<input type="url" data-control-web placeholder="자동 · 웹 서버 PC의 8798 포트"></label><label ${video?'hidden':''}>이미지 서버 복구 주소<input type="url" data-control-image placeholder="자동 · 이미지 서버 PC의 8798 포트"></label><label>웹 복구 접속 키 (설정한 경우)<input type="password" autocomplete="off" data-key-web></label><label ${video?'hidden':''}>이미지 복구 접속 키 (설정한 경우)<input type="password" autocomplete="off" data-key-image></label><button type="button" data-control-check>서버 연결 확인</button></details>`;
 const status=root.querySelector('[role=status]'),q=selector=>root.querySelector(selector),key='maker-control.'+kind;
 for(const group of ['web','image']){try{q('[data-control-'+group+']').value=localStorage.getItem(key+'.'+group)||'';q('[data-key-'+group+']').value=sessionStorage.getItem(key+'.key.'+group)||'';}catch{}}
 const message=(text,error=false)=>{status.textContent=text;status.classList.toggle('error',error);};
 let busy=false,controller=null,recoveryObserver=null;
 const checkCancelled=()=>controller?.signal.throwIfAborted();
 const boundedSignal=ms=>controller?AbortSignal.any([controller.signal,AbortSignal.timeout(ms)]):AbortSignal.timeout(ms);
 const imageTarget=provider=>({'qwen-image':'vllm-image','qwen-image-turbo':'image-turbo','qwen-image-quantized':'image-quantized'}[provider]||null);
 const selectedImage=()=>imageTarget(getProvider()||'qwen-image');
 const update=()=>{const target=selectedImage(),button=q('[data-restart-image]'),standard=q('[data-restart-vllm]');if(button)button.hidden=!target||target==='vllm-image';if(standard)standard.hidden=target!=='vllm-image';};update();document.addEventListener('change',update);document.addEventListener('click',event=>{if(event.target.closest('[data-tab]'))update();});
 root.addEventListener('input',()=>{for(const group of ['web','image'])try{localStorage.setItem(key+'.'+group,q('[data-control-'+group+']').value.trim());sessionStorage.setItem(key+'.key.'+group,q('[data-key-'+group+']').value);}catch{}});
 async function address(target){
  const group=target.endsWith('-web')?'web':'image',custom=q('[data-control-'+group+']').value.trim();let base=getWebBase()||location.origin;
  if(!custom&&group==='image'){
   const cacheKey='maker-control.image-host.'+base+'.'+target;
   try{const response=await fetch(base.replace(/\/$/,'')+'/api/config',{signal:boundedSignal(2000)});if(!response.ok)throw Error();const config=await response.json(),endpoint=config[target==='image-turbo'?'qwenTurbo':target==='image-quantized'?'qwenQuantized':'qwen'];if(endpoint){const selected=new URL(endpoint.split(',')[0].trim()),webHost=new URL(getWebBase()||location.origin).hostname;if(['localhost','127.0.0.1','[::1]'].includes(selected.hostname)&&!['localhost','127.0.0.1','[::1]'].includes(webHost))selected.hostname=webHost;base=selected.href;try{localStorage.setItem(cacheKey,helperAddress(base));}catch{}}}catch{try{base=localStorage.getItem(cacheKey)||base;}catch{}}
  }
  const url=new URL(custom||helperAddress(base));if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.search||url.hash)throw Error('복구 주소는 http 또는 https 주소로 입력하세요.');
  return {base:url.href.replace(/\/$/,''),secret:q('[data-key-'+group+']').value};
 }
 async function request(connection,target,restart=false){
  let response;try{response=await fetch(connection.base+'/api/control/'+target+(restart?'/restart':''),{method:restart?'POST':'GET',headers:{'x-maker-control':'1',...(restart?{'content-type':'application/json'}:{}),...(connection.secret?{authorization:'Bearer '+connection.secret}:{})},...(restart?{body:'{}'}:{}),signal:boundedSignal(12000)});}catch{checkCancelled();throw Error('복구 도우미에 연결하지 못했습니다. 서버 PC의 도우미 실행 상태·복구 주소·브라우저의 로컬 네트워크 접근을 확인하세요.');}
  checkCancelled();const data=await response.json();if(!response.ok)throw Error(data.error||'복구 요청을 처리하지 못했습니다.');return data;
 }
 async function restart(target){
  const connection=await address(target);let data=await request(connection,target,true);
  const operation=data.operation?.id;
  for(let n=0;n<1800;n++){
   checkCancelled();message(data.label+' · '+data.message);
   if(data.operation?.status==='ready')return;
   if(['failed','timeout'].includes(data.operation?.status))throw Error(data.operation.error||data.message);
   await pause(1000,controller.signal);data=await request(connection,target);
   if(operation&&data.operation?.id!==operation)throw Error('복구 도우미가 다시 시작되었습니다. 복구를 다시 누르세요.');
  }
  throw Error('모델 시작 확인 시간이 지났습니다. 고급 설정에서 연결을 확인하세요.');
 }
 async function exclusive(action){
  if(busy)return;busy=true;controller=new AbortController();
  const regions=[];const collect=el=>{if(el===root)return;if(!el.contains(root)){regions.push(el);return;}for(const child of el.children)if(!['SCRIPT','STYLE'].includes(child.tagName))collect(child);};for(const main of document.querySelectorAll('main'))collect(main);
  const panels=regions.map(el=>[el,el.inert]);for(const [el]of panels)el.inert=true;
  const cancel=q('[data-cancel-recovery]'),badge=q('[data-recovery-state]');cancel.hidden=false;badge.textContent='복구 중';
  root.setAttribute('aria-busy','true');root.querySelectorAll('button,input,select').forEach(el=>el.disabled=el!==cancel);
  try{await action();checkCancelled();badge.textContent='연결됨';}
  catch(error){
   if(controller.signal.aborted){badge.textContent='대기 취소됨';message('복구 대기를 취소했습니다. 저장한 결과는 보관됩니다. 이미 접수된 서버 재시작이나 생성 요청은 계속될 수 있습니다. 아래 작업의 진행 상태를 확인하세요.');}
   else{badge.textContent='확인 필요';message('복구를 완료하지 못했습니다. '+error.message+' 저장한 결과와 입력은 유지됩니다.',true);q('details').open=true;}
  }
  finally{if(controller.signal.aborted)void recoveryObserver?.refresh?.().catch(()=>{});recoveryObserver=null;for(const [el,inert]of panels)el.inert=inert;busy=false;controller=null;cancel.hidden=true;root.removeAttribute('aria-busy');root.querySelectorAll('button,input,select').forEach(el=>el.disabled=false);update();}
 }
 q('[data-cancel-recovery]').onclick=()=>{controller?.abort(new DOMException('복구 대기 취소','AbortError'));};
 async function run(target,check=false){return exclusive(async()=>{
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
   if(recovery){message('2/4 · 선택한 영상 작업을 중지하고 저장하고 있습니다…');await recovery.prepare({signal:controller.signal});checkCancelled();progress.value=2;message('3/4 · 영상 엔진과 저장한 장면을 확인하고 있습니다…');const resumed=await recovery.resume({maxEdge:Number(q('[data-recovery-size]').value),signal:controller.signal});checkCancelled();await onConnected(kind);progress.value=4;q('details').open=false;message(resumed?'복구 완료 · 완성한 영상은 보관하고 남은 장면부터 이어 만들고 있습니다.':'복구 완료 · 작업실에 연결되었습니다. 저장한 영상을 선택하면 이어 만들 수 있습니다.');}
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
 if(!video){q('[data-restart-vllm]').onclick=()=>run('vllm-image');q('[data-restart-image]').onclick=()=>run(selectedImage());}
 q('[data-control-check]').onclick=()=>run(kind,true);
 return {restart:target=>run(target||kind),recover};
}
