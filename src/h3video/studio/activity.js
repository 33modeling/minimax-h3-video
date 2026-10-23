// Live server activity is separate from saved results and previous errors.
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sceneLabel=value=>/^page-\d+$/.test(value)?'쪽 '+Number(value.slice(5)):/^\d+(?:\/\d+)?$/.test(value)?'장면 '+value:value==='cover'?'표지':'';
const live=new Set(['running','pending','queued','pausing','in_progress']);
export function libraryState(item){
 if(item.busy||live.has(item.status))return 'working';
 if(item.failed||item.error||['error','failed','paused','cancelled','stopped'].includes(item.status))return 'unfinished';
 if(item.incomplete||item.planning||item.paused||item.completed<item.total)return 'unfinished';
 return ['done','completed','complete'].includes(item.status)&&item.total!==0||item.ready===true||item.total>0&&item.completed===item.total?'complete':'unfinished';
}
export function groupLibrary(items,render,{headingTag='div'}={}){
 return [['working','진행 중 · 대기'],['complete','완료된 결과'],['unfinished','미완성 · 중지 · 실패']].map(([key,label])=>{
  const rows=items.filter(item=>libraryState(item)===key);
  return `<${headingTag} class="maker-library-heading" data-library-group="${key}"><strong>${label}</strong><span>${rows.length}개</span>${!rows.length?'<small>해당 작업 없음</small>':''}</${headingTag}>${rows.map(render).join('')}`;
 }).join('');
}
export function mountActivity({getWebBase,getProvider=()=> 'qwen-image',video=false,pollMs=3000}={}){
 if(document.querySelector('[data-maker-activity]'))return;
 const root=document.createElement('section');root.className='maker-activity';root.dataset.makerActivity='';root.setAttribute('aria-label',video?'영상 서버 작업 상태':'이미지 서버 작업 상태');
 root.innerHTML='<div class="ma-heading"><strong data-activity-title>서버 상태 확인 중</strong><span data-activity-connection></span><button type="button" data-activity-refresh>새로고침</button></div><p data-activity-current role="status" aria-live="polite">현재 작업을 확인하고 있습니다.</p><div class="ma-queues" data-activity-queues></div>';
 document.body.prepend(root);
 const style=document.createElement('style');style.textContent=`
 .maker-activity{position:sticky;top:0;z-index:180;box-sizing:border-box;isolation:isolate;width:100%;background:#f4f7f5;color:#183b2c;border-bottom:1px solid #cbd9ce;padding:12px clamp(12px,3vw,40px);font:14px/1.5 system-ui}
 .maker-activity *{box-sizing:border-box;min-width:0}.ma-heading{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.ma-heading strong{font-size:16px}.ma-heading span{color:#52665b;font-size:12px}.ma-heading button{margin-left:auto;min-height:36px;padding:6px 12px;border:1px solid #9fb7a9;border-radius:8px;background:#fff;color:inherit;font:inherit;cursor:pointer}.maker-activity p{margin:5px 0 0;overflow-wrap:anywhere}.ma-queues{display:flex;gap:8px;flex-wrap:wrap;max-height:180px;overflow:auto}.ma-job{margin-top:8px;border:1px solid #bed7ca;border-radius:8px;padding:7px 10px;background:#fff;max-width:100%;overflow-wrap:anywhere}.ma-job b{display:block;font-size:11px;color:#47745d}.maker-activity[data-state=running]{background:#e7f5ed;border-color:#76b38f}.maker-activity[data-state=offline]{background:#fff2e9;color:#8a3c20;border-color:#ddac91}
 .maker-library-heading{grid-column:1/-1;list-style:none!important;display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:20px 0 6px;padding:12px 0 9px;border-bottom:1px solid #cbd9ce;font:14px/1.5 system-ui!important;color:inherit}.maker-library-heading strong{font-size:18px}.maker-library-heading small{opacity:.65}.maker-library-heading[data-library-group=working]{color:#24754e}.maker-library-heading[data-library-group=unfinished]{color:#995031}
 body .editor-topbar{top:var(--maker-activity-height,0px)}
 .maker-activity[data-state=idle]{padding:5px clamp(12px,3vw,40px);background:#f7f9f7}.maker-activity[data-state=idle] .ma-heading strong{font-size:12px;font-weight:600;color:#3d6a52}.maker-activity[data-state=idle] .ma-heading strong::before{content:'● ';color:#3f8a5d}.maker-activity[data-state=idle] .ma-heading button{min-height:28px;padding:2px 10px;font-size:12px}.maker-activity[data-state=idle] [data-activity-current],.maker-activity[data-state=idle] .ma-queues{display:none}
 @media(max-width:540px){.maker-activity{padding:9px 12px}.ma-heading strong{font-size:14px}.ma-heading span{flex-basis:100%;order:3}.ma-heading button{font-size:12px}.ma-job{width:100%}.ma-queues{max-height:120px}}
 `;document.head.append(style);
 const q=s=>root.querySelector(s);let timer,healthTimer,pending=false,epoch=0,healthEpoch=0,lastBase='',lastProvider='',lastActivity='',health=null,checkedAt=0;
 const base=()=>String(getWebBase?.()||location.origin).replace(/\/+$/,'');
 const provider=()=>getProvider()||'qwen-image';
 const json=async(url)=>{const r=await fetch(url,{signal:AbortSignal.timeout(6500),cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);return r.json();};
 const resize=new ResizeObserver(()=>document.documentElement.style.setProperty('--maker-activity-height',root.offsetHeight+'px'));resize.observe(root);
 function connection(){q('[data-activity-connection]').textContent=!checkedAt?'모델 연결 확인 중':health===null?'모델 연결 확인 필요':video?`영상 엔진 · 기본 ${health.fl2va?'연결됨':'연결 안 됨'} · 참고 영상 ${health.ref2va?'연결됨':'연결 안 됨'}`:health.ok?'이미지 모델 연결됨':'이미지 모델 연결 안 됨';}
 async function checkHealth(){const token=++healthEpoch,address=base(),model=provider();try{const h=await json(address+'/api/health'+(video?'':'?provider='+encodeURIComponent(model)));if(token!==healthEpoch||address!==base()||model!==provider())return;health=h;checkedAt=Date.now();}catch{if(token===healthEpoch){health=null;checkedAt=Date.now();}}connection();if(token===healthEpoch)void refresh();clearTimeout(healthTimer);healthTimer=setTimeout(checkHealth,15000);}
 function render(running,pendingJobs,count){
  const preparing=Math.max(0,count-running.length-pendingJobs.length),busy=running.length>0||preparing>0,waiting=pendingJobs.length;
  root.dataset.state=busy?'running':waiting?'queued':health&&(video?health.fl2va||health.ref2va:health.ok)?'idle':'offline';
  q('[data-activity-title]').textContent=(video?'영상 서버':'이미지 서버')+' · '+(busy?'작업 중':waiting?'대기 중':root.dataset.state==='idle'?'대기 작업 없음':'모델 연결 확인 필요');
  q('[data-activity-current]').textContent=busy?`진행 ${running.length+preparing}개 · 대기 ${waiting}개`:waiting?`대기 ${waiting}개 · 순서가 되면 시작합니다.`:root.dataset.state==='idle'?'진행 중인 작업이 없습니다.':'진행 중인 작업 없음 · 모델 연결을 확인하세요.';
  q('[data-activity-queues]').innerHTML=[...running.map(row=>`<div class="ma-job" data-active-job><b>● 진행 중${row.stage?' · '+esc(row.stage):''}</b>${esc(row.title||'이미지 생성')}${sceneLabel(row.item||'')?' · '+esc(sceneLabel(row.item)):''}${row.message?' · '+esc(row.message):''}</div>`),...pendingJobs.map((row,i)=>`<div class="ma-job" data-queued-job><b>대기 ${row.position||i+1}번째</b>${esc(row.title||'생성 작업')}${sceneLabel(row.item||'')?' · '+esc(sceneLabel(row.item)):''}</div>`),...(preparing?['<div class="ma-job"><b>준비·처리 중</b>작업 정보를 불러오고 있습니다.</div>']:[])].join('');connection();const signature=JSON.stringify([running.map(row=>[row.id,row.status,row.item]),pendingJobs.map(row=>[row.id,row.position]),count]);if(signature!==lastActivity){lastActivity=signature;document.dispatchEvent(new CustomEvent('maker:activity'));}
 }
 async function refresh(){
  if(pending||document.hidden)return;pending=true;const token=epoch,address=base();
  try{
   const results=await Promise.allSettled([json(address+(video?'/api/activity':'/api/studio/queue')),json(address+'/api/runtime')]);
   if(token!==epoch||address!==base())return;
   const [queue,runtime]=results;if(queue.status==='rejected'&&runtime.status==='rejected')throw Error('offline');
   const value=queue.status==='fulfilled'?queue.value:{running:[],pending:[]},count=runtime.status==='fulfilled'?Number(runtime.value.activeCount)||0:0;
   render(value.running||[],value.pending||[],Math.max(count,(value.running?.length||0)+(value.pending?.length||0)));
  }catch{if(token!==epoch)return;root.dataset.state='offline';q('[data-activity-title]').textContent=(video?'영상':'이미지')+' 웹 서버 · 연결 끊김';q('[data-activity-connection]').textContent='서버 주소와 연결을 확인하세요.';q('[data-activity-current]').textContent='현재 진행 상황을 확인할 수 없습니다.';q('[data-activity-queues]').replaceChildren();}
  finally{pending=false;clearTimeout(timer);timer=setTimeout(refresh,pollMs);}
 }
 function changed(){if(base()!==lastBase||provider()!==lastProvider){lastBase=base();lastProvider=provider();epoch++;health=null;checkedAt=0;root.dataset.state='checking';q('[data-activity-title]').textContent='서버 상태 확인 중';q('[data-activity-current]').textContent='현재 작업을 확인하고 있습니다.';q('[data-activity-queues]').replaceChildren();void checkHealth();}void refresh();}
 q('[data-activity-refresh]').onclick=()=>{void checkHealth();void refresh();};
 document.addEventListener('change',changed);document.addEventListener('maker:connection-change',changed);document.addEventListener('visibilitychange',changed);
 // A cached document resumes its existing observers and timers on browser Back.
 window.addEventListener('pageshow',changed);changed();
 return {refresh};
}
