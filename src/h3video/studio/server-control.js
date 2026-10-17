const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const helperAddress=base=>{const url=new URL(base||location.origin,location.origin);url.port='8798';url.pathname='/';url.search=url.hash=url.username=url.password='';return url.origin;};
export function mountServerControls(root,{getWebBase,kind='storybook-web',getProvider=()=> 'qwen-image',getRecovery=()=>null,onConnected=()=>{}}){
 if(!root||root.dataset.mounted)return;root.dataset.mounted='true';
 if(!document.getElementById('maker-server-control-style')){const style=document.createElement('style');style.id='maker-server-control-style';style.textContent='.maker-server-control{box-sizing:border-box;max-width:1540px;margin:16px auto;padding:16px 20px;border:1px solid #cbd9ce;border-radius:12px;background:#f4f7ef;color:#29463b;font:14px/1.6 system-ui}.maker-server-control>div{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.maker-server-control strong{margin-right:auto}.maker-server-control button{min-height:44px;padding:9px 14px;border:1px solid #abc1b1;border-radius:8px;background:white;color:#29463b;font:600 13px system-ui;cursor:pointer}.maker-server-control button:disabled{opacity:.5;cursor:wait}.maker-server-control [data-recover-generation]{background:#29463b;color:white;border-color:#29463b}.maker-server-control progress{width:100%;height:8px;margin-top:12px;accent-color:#29463b}.maker-server-control details>div{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.maker-server-control p{margin:8px 0 0;overflow-wrap:anywhere}.maker-server-control details{margin-top:8px}.maker-server-control summary{cursor:pointer}.maker-server-control label{display:block;margin-top:10px}.maker-server-control input{box-sizing:border-box;display:block;width:100%;min-height:44px;padding:8px;border:1px solid #abc1b1;border-radius:8px;background:white;color:#29463b;font:14px system-ui}.maker-server-control .error{color:#a63c29}@media(max-width:560px){.maker-server-control{margin:10px;padding:14px}.maker-server-control>div strong{flex-basis:100%}.maker-server-control>div button{flex:1 1 140px}}';document.head.append(style);}
 const video=kind==='video-web';
 root.className='maker-server-control';root.setAttribute('aria-label',video?'작업실 연결 복구':'이미지 생성 복구');root.innerHTML=`<div><strong>${video?'작업실 연결':'이미지 생성이 멈췄나요?'}</strong><button type="button" data-recover-generation>${video?'작업실 연결 복구':'생성 복구 · 이어 만들기'}</button></div><p role="status" aria-live="polite">${video?'저장한 영상과 입력을 보관하고 작업실에 다시 연결합니다.':'작업을 저장하고 이미지 모델을 다시 켠 뒤 남은 그림을 이어 만듭니다. 남은 그림만 최대 512px로 낮추며 완성한 그림은 보관합니다.'}</p><progress data-recovery-progress max="4" value="0" hidden aria-label="복구 진행"></progress><details><summary>고급 설정 · 서버별 다시 켜기</summary><div><button type="button" data-restart-web>웹 화면·저장 서버만 다시 켜기</button>${video?'':'<button type="button" data-restart-vllm>기본 Qwen 이미지 모델 다시 켜기</button><button type="button" data-restart-image>선택 이미지 모델 다시 켜기</button>'}</div><p>${video?'영상 생성 엔진은 별도로 연결됩니다.':'모델 재시작은 메모리를 비우고 다시 불러옵니다.'} 복구하려는 서버 PC에 복구 도우미가 켜져 있어야 합니다.</p><label>웹 서버 복구 주소<input type="url" data-control-web placeholder="자동 · 웹 서버 PC의 8798 포트"></label><label ${video?'hidden':''}>이미지 서버 복구 주소<input type="url" data-control-image placeholder="자동 · 이미지 서버 PC의 8798 포트"></label><label>웹 복구 접속 키 (설정한 경우)<input type="password" autocomplete="off" data-key-web></label><label ${video?'hidden':''}>이미지 복구 접속 키 (설정한 경우)<input type="password" autocomplete="off" data-key-image></label><button type="button" data-control-check>복구 연결 확인</button></details>`;
 const status=root.querySelector('[role=status]'),q=selector=>root.querySelector(selector),key='maker-control.'+kind;
 for(const group of ['web','image']){try{q('[data-control-'+group+']').value=localStorage.getItem(key+'.'+group)||'';q('[data-key-'+group+']').value=sessionStorage.getItem(key+'.key.'+group)||'';}catch{}}
 const message=(text,error=false)=>{status.textContent=text;status.classList.toggle('error',error);};
 let busy=false;
 const imageTarget=provider=>({'qwen-image':'vllm-image','qwen-image-turbo':'image-turbo','qwen-image-quantized':'image-quantized'}[provider]||null);
 const selectedImage=()=>imageTarget(getProvider()||'qwen-image');
 const update=()=>{const button=q('[data-restart-image]');if(button)button.hidden=!selectedImage()||selectedImage()==='vllm-image';};update();document.addEventListener('change',update);document.addEventListener('click',event=>{if(event.target.closest('[data-tab]'))update();});
 root.addEventListener('input',()=>{for(const group of ['web','image'])try{localStorage.setItem(key+'.'+group,q('[data-control-'+group+']').value.trim());sessionStorage.setItem(key+'.key.'+group,q('[data-key-'+group+']').value);}catch{}});
 async function address(target){
  const group=target.endsWith('-web')?'web':'image',custom=q('[data-control-'+group+']').value.trim();let base=getWebBase()||location.origin;
  if(!custom&&group==='image'){
   const cacheKey='maker-control.image-host.'+base+'.'+target;
   try{const response=await fetch(base.replace(/\/$/,'')+'/api/config',{signal:AbortSignal.timeout(2000)});if(!response.ok)throw Error();const config=await response.json(),endpoint=config[target==='image-turbo'?'qwenTurbo':target==='image-quantized'?'qwenQuantized':'qwen'];if(endpoint){const selected=new URL(endpoint.split(',')[0].trim()),webHost=new URL(getWebBase()||location.origin).hostname;if(['localhost','127.0.0.1','[::1]'].includes(selected.hostname)&&!['localhost','127.0.0.1','[::1]'].includes(webHost))selected.hostname=webHost;base=selected.href;try{localStorage.setItem(cacheKey,helperAddress(base));}catch{}}}catch{try{base=localStorage.getItem(cacheKey)||base;}catch{}}
  }
  const url=new URL(custom||helperAddress(base));if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.search||url.hash)throw Error('복구 주소는 http 또는 https 주소로 입력하세요.');
  return {base:url.href.replace(/\/$/,''),secret:q('[data-key-'+group+']').value};
 }
 async function request(connection,target,restart=false){
  let response;try{response=await fetch(connection.base+'/api/control/'+target+(restart?'/restart':''),{method:restart?'POST':'GET',headers:{'x-maker-control':'1',...(restart?{'content-type':'application/json'}:{}),...(connection.secret?{authorization:'Bearer '+connection.secret}:{})},...(restart?{body:'{}'}:{}),signal:AbortSignal.timeout(12000)});}catch{throw Error('복구 도우미에 연결하지 못했습니다. 서버 PC의 도우미 실행 상태·복구 주소·브라우저의 로컬 네트워크 접근을 확인하세요.');}
  const data=await response.json();if(!response.ok)throw Error(data.error||'복구 요청을 처리하지 못했습니다.');return data;
 }
 async function restart(target){
  const connection=await address(target);let data=await request(connection,target,true);
  const operation=data.operation?.id;
  for(let n=0;n<1800;n++){
   message(data.label+' · '+data.message);
   if(data.operation?.status==='ready')return;
   if(['failed','timeout'].includes(data.operation?.status))throw Error(data.operation.error||data.message);
   await pause(1000);data=await request(connection,target);
   if(operation&&data.operation?.id!==operation)throw Error('복구 도우미가 다시 시작되었습니다. 복구를 다시 누르세요.');
  }
  throw Error('모델 시작 확인 시간이 지났습니다. 고급 설정에서 연결을 확인하세요.');
 }
 async function exclusive(action){
  if(busy)return;busy=true;const panels=[...document.querySelectorAll('main')].filter(el=>!el.contains(root)).map(el=>[el,el.inert]);for(const [el]of panels)el.inert=true;root.setAttribute('aria-busy','true');root.querySelectorAll('button,input').forEach(button=>button.disabled=true);
  try{await action();}catch(error){message('복구를 완료하지 못했습니다. '+error.message+' 저장한 결과와 입력은 유지됩니다.',true);q('details').open=true;}
  finally{for(const [el,inert]of panels)el.inert=inert;busy=false;root.removeAttribute('aria-busy');root.querySelectorAll('button,input').forEach(button=>button.disabled=false);}
 }
 async function run(target,check=false){return exclusive(async()=>{
  message(check?'복구 연결을 확인하고 있습니다…':'서버를 다시 켜고 있습니다…');
  if(check){const data=await request(await address(target),target);message(data.label+' · '+data.message);return;}
  await restart(target);await onConnected(target);message('다시 연결되었습니다. 저장한 결과는 보관되어 있습니다.');
 });}
 async function recover(){return exclusive(async()=>{
  const recovery=getRecovery(),progress=q('[data-recovery-progress]');progress.hidden=false;progress.value=0;
  message('1/4 · 작업실 연결을 확인하고 있습니다…');
  let online=false;try{online=(await fetch((getWebBase()||location.origin).replace(/\/$/,'')+'/api/runtime',{signal:AbortSignal.timeout(3000)})).ok;}catch{}
  if(!online)await restart(kind);
  progress.value=1;
  if(video){await onConnected(kind);progress.value=4;q('details').open=false;message('작업실에 다시 연결되었습니다. 저장한 영상과 입력은 보관되어 있습니다.');return;}
  const provider=await recovery?.resolve()||getProvider()||'qwen-image',target=imageTarget(provider);
  if(!target&&!['mock','claude-svg','pollinations','openai'].includes(provider))throw Error('이 모델은 자동 재시작을 지원하지 않습니다. 모델 연결 설정을 확인하세요.');
  message('2/4 · 진행 중인 그림을 중지하고 수정 내용을 저장하고 있습니다…');
  await recovery?.prepare();progress.value=2;
  if(target){message('3/4 · 이미지 모델을 다시 불러오고 있습니다. 준비되면 자동으로 이어 만듭니다…');await restart(target);}
  progress.value=3;message('4/4 · 남은 그림을 메모리 절약 설정으로 이어 만들고 있습니다…');
  const resumed=await recovery?.resume();await onConnected(target||kind);progress.value=4;q('details').open=false;
  message(resumed?'복구 완료 · 완성한 그림은 보관하고, 남은 그림만 최대 512px로 이어 만들고 있습니다.':'복구 완료 · 이미지 생성에 다시 연결되었습니다. 완성한 그림과 입력은 보관되어 있습니다.');
 });}
 q('[data-recover-generation]').onclick=recover;
 q('[data-restart-web]').onclick=()=>run(kind);
 if(!video){q('[data-restart-vllm]').onclick=()=>run('vllm-image');q('[data-restart-image]').onclick=()=>run(selectedImage());}
 q('[data-control-check]').onclick=()=>run(kind,true);
 return {restart:target=>run(target||kind),recover};
}
