const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const helperAddress=base=>{const url=new URL(base||location.origin,location.origin);url.port='8798';url.pathname='/';url.search=url.hash=url.username=url.password='';return url.origin;};
export function mountServerControls(root,{getWebBase,kind='storybook-web',getProvider=()=> 'qwen-image',onConnected=()=>{}}){
 if(!root||root.dataset.mounted)return;root.dataset.mounted='true';
 if(!document.getElementById('maker-server-control-style')){const style=document.createElement('style');style.id='maker-server-control-style';style.textContent='.maker-server-control{box-sizing:border-box;max-width:1540px;margin:16px auto;padding:16px 20px;border:1px solid #cbd9ce;border-radius:12px;background:#f4f7ef;color:#29463b;font:14px/1.6 system-ui}.maker-server-control>div{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.maker-server-control strong{margin-right:auto}.maker-server-control button{min-height:44px;padding:9px 14px;border:1px solid #abc1b1;border-radius:8px;background:white;color:#29463b;font:600 13px system-ui;cursor:pointer}.maker-server-control button:disabled{opacity:.5;cursor:wait}.maker-server-control p{margin:8px 0 0;overflow-wrap:anywhere}.maker-server-control details{margin-top:8px}.maker-server-control summary{cursor:pointer}.maker-server-control label{display:block;margin-top:10px}.maker-server-control input{box-sizing:border-box;display:block;width:100%;min-height:44px;padding:8px;border:1px solid #abc1b1;border-radius:8px;background:white;color:#29463b;font:14px system-ui}.maker-server-control .error{color:#a63c29}@media(max-width:560px){.maker-server-control{margin:10px;padding:14px}.maker-server-control>div strong{flex-basis:100%}.maker-server-control>div button{flex:1 1 140px}}';document.head.append(style);}
 root.className='maker-server-control';root.setAttribute('aria-label','서버 다시 켜기');root.innerHTML='<div><strong>서버 다시 켜기</strong><button type="button" data-restart-web>웹 서버 다시 켜기</button><button type="button" data-restart-vllm>vLLM 이미지 서버 다시 켜기</button><button type="button" data-restart-image>선택 이미지 서버 다시 켜기</button></div><p role="status" aria-live="polite">완성한 결과는 보관합니다. 진행 중인 작업은 즉시 중지한 뒤 다시 켜세요.</p><details><summary>복구 연결 설정</summary><p>웹 서버가 꺼져 있어도 사용할 수 있습니다. 해당 서버 PC에 복구 도우미가 켜져 있어야 합니다.</p><label>웹 서버 복구 주소<input type="url" data-control-web placeholder="자동 · 웹 서버 PC의 8798 포트"></label><label>이미지 서버 복구 주소<input type="url" data-control-image placeholder="자동 · 이미지 서버 PC의 8798 포트"></label><label>웹 복구 접속 키 (설정한 경우)<input type="password" autocomplete="off" data-key-web></label><label>이미지 복구 접속 키 (설정한 경우)<input type="password" autocomplete="off" data-key-image></label><button type="button" data-control-check>복구 연결 확인</button></details>';
 const status=root.querySelector('[role=status]'),q=selector=>root.querySelector(selector),key='maker-control.'+kind;
 for(const group of ['web','image']){try{q('[data-control-'+group+']').value=localStorage.getItem(key+'.'+group)||'';q('[data-key-'+group+']').value=sessionStorage.getItem(key+'.key.'+group)||'';}catch{}}
 const message=(text,error=false)=>{status.textContent=text;status.classList.toggle('error',error);};
 let busy=false;
 const selectedImage=()=>({'qwen-image-turbo':'image-turbo','qwen-image-quantized':'image-quantized'}[getProvider()]||'vllm-image');
 const update=()=>q('[data-restart-image]').hidden=selectedImage()==='vllm-image'||kind==='video-web';update();document.addEventListener('change',update);document.addEventListener('click',event=>{if(event.target.closest('[data-tab]'))update();});
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
 async function run(target,check=false){
  if(busy)return;busy=true;root.querySelectorAll('button').forEach(button=>button.disabled=true);message(check?'복구 연결을 확인하고 있습니다…':'서버 다시 켜기를 요청하고 있습니다…');
  try{
   const connection=await address(target);let data=await request(connection,target,!check);
   if(check){message(data.label+' · '+data.message);return;}
   const operation=data.operation?.id;message(data.message);
   for(let n=0;n<1800;n++){
    await pause(1000);data=await request(connection,target);
    if(operation&&data.operation?.id!==operation)throw Error('복구 도우미가 다시 시작되었습니다. 연결 상태를 확인하고 다시 요청하세요.');
    message(data.label+' · '+data.message);
    if(data.operation?.status==='ready'){try{await onConnected(target);}catch{message(data.label+' · 다시 켜졌습니다. 웹 서버 연결도 확인해 주세요.');return;}message(data.label+' · 다시 연결되었습니다. 저장한 작업에서 이어 만들 수 있습니다.');return;}
    if(['failed','timeout'].includes(data.operation?.status))throw Error(data.operation.error||data.message);
   }
   throw Error('시작 확인 시간이 지났습니다. 복구 연결을 다시 확인해 주세요.');
  }catch(error){message(error.message,true);q('details').open=true;}
  finally{busy=false;root.querySelectorAll('button').forEach(button=>button.disabled=false);}
 }
 q('[data-restart-web]').onclick=()=>run(kind);q('[data-restart-vllm]').onclick=()=>run('vllm-image');q('[data-restart-image]').onclick=()=>run(selectedImage());q('[data-control-check]').onclick=()=>run(kind,true);
 return {restart:target=>run(target||kind)};
}
