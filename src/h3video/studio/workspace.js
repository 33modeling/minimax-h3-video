// A shared view of saved state. Actions remain owned by each maker's existing controller.
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={book:['동화책','쪽'],image:['이미지','장면'],video:['영상','장면']};
export function mountWorkspace(root,{kind='image',onAction=()=>{}}={}){
 let data={},filter='all',selected=null,pending=false,signature='';
 function render(){
  const [name,unit]=data.labels||labels[kind]||labels.image;
  const items=data.items||[],active=items.find(it=>it.active);
  if(!items.some(it=>it.id===selected))selected=active?.id||items[0]?.id||null;
  const current=items.find(it=>it.id===selected),complete=items.filter(it=>it.completed&&!it.dirty&&!it.error&&!it.active).length,failed=items.filter(it=>it.error).length;
  const visible=items.filter(it=>filter==='error'?it.error:filter==='complete'?it.completed&&!it.dirty&&!it.error&&!it.active:filter==='active'?it.active:filter==='pending'?!it.completed||it.dirty||it.error||it.active:true);
  const state=pending?'요청 처리 중':data.requesting?'요청 처리 중':data.busy?'작업 진행 중':failed?'확인 필요':data.resumable?'중지 · 저장됨':data.saved===false&&items.length?'생성 준비':items.length?'저장됨':'시작할 준비가 됐어요';
  const html=`<section class="mw-board" aria-label="${name} 작업 현황" data-workspace-board>
   <div class="mw-heading"><div><span class="mw-eyebrow">${name} 작업 현황</span><h2>${esc(data.title||'새로운 '+name+' 작업')}</h2></div><div class="mw-heading-actions">${items.length?`<button type="button" data-workspace-action="new" ${data.busy||pending||data.requesting?'disabled':''}>＋ 새 작업</button>`:''}<span class="mw-state ${data.busy?'is-running':failed?'is-error':''}"><i aria-hidden="true"></i>${state}</span></div></div>
   ${items.length?`<div class="mw-stats" aria-label="장면별 작업 수"><div><span>전체 ${unit}</span><strong data-workspace-total>${items.length}</strong></div><div><span>완료</span><strong data-workspace-complete>${complete}</strong></div><div><span>남은 ${unit}</span><strong data-workspace-remaining>${items.length-complete}</strong></div><div class="${failed?'has-error':''}"><span>실패 · 확인 필요</span><strong data-workspace-failed>${failed}</strong></div></div>
   <div class="mw-now" role="status" aria-live="polite"><span class="mw-now-label">${data.busy?'지금 진행 중':'현재 상태'}</span><strong data-workspace-message>${esc(data.message||'장면을 선택해 확인하거나 수정하세요.')}</strong>${Number.isFinite(data.elapsedMs)&&data.elapsedMs>0?`<small>경과 ${Math.floor(data.elapsedMs/60000)}분 ${Math.floor(data.elapsedMs/1000)%60}초</small>`:''}</div>
   <div class="mw-main-actions"><button type="button" data-workspace-action="stop" class="mw-stop" ${!data.busy||pending||data.requesting?'disabled':''}>■ 지금 중지</button>${data.saved===false?`<button type="button" data-workspace-action="generate" class="mw-primary" ${data.busy||pending||data.requesting?'disabled':''}>이미지 생성</button>`:`<button type="button" data-workspace-action="resume" class="mw-primary" ${data.busy||!data.resumable||pending||data.requesting?'disabled':''}>▶ 이어 만들기</button>`}<button type="button" data-workspace-action="edit" ${data.canEdit===false||!current||pending||data.requesting?'disabled':''}>${data.busy?'중지하고 선택 '+unit+' 수정':'선택 '+unit+' 수정'}</button><button type="button" data-workspace-action="recover" ${data.busy||!data.resumable||pending||data.requesting?'disabled':''}>설정 바꿔 재개</button></div>
   <div class="mw-scenes-heading"><h3>${unit}별 진행 상황</h3><div class="mw-filter" role="group" aria-label="${unit} 목록 필터">${[['all','전체'],['active','생성 중'],['pending','미완성'],['complete','완료'],['error','실패']].map(([value,label])=>`<button type="button" data-workspace-filter="${value}" aria-pressed="${filter===value}">${label}</button>`).join('')}</div></div>
   <div class="mw-scenes" aria-label="${unit} 선택">${visible.map(it=>{const index=items.indexOf(it),status=it.active?'생성 중':it.error?'실패':it.dirty?'수정됨':it.completed?'완료':'대기';return `<button type="button" data-workspace-scene="${esc(it.id)}" aria-pressed="${it.id===selected}" class="mw-scene ${it.active?'is-active':''} ${it.error?'is-error':''}"><span class="mw-thumb">${it.preview?`<img src="${esc(it.preview)}" alt="${esc(it.label)}" loading="lazy">`:'<span class="mw-no-image" aria-hidden="true">'+String(index+1).padStart(2,'0')+'</span>'}<span class="mw-scene-state">${status}</span></span><span class="mw-scene-title">${String(index+1).padStart(2,'0')} · ${esc(it.label||unit+' '+(index+1))}</span></button>`;}).join('')||'<p class="mw-empty-filter">해당하는 '+unit+'이 없습니다.</p>'}</div>
   <div class="mw-scene-footer"><span>${current?esc(unit+' '+(items.indexOf(current)+1)+' / '+items.length+' 선택 · '+current.label):''}</span><button type="button" data-workspace-action="current" ${!active||pending?'disabled':''}>현재 생성 ${unit}으로 이동 ↗</button></div>
   <p class="mw-preserve">중지해도 완성한 결과와 수정 내용은 남습니다. 이어 만들기는 남은 작업부터 진행합니다.</p>`:
   `<p class="mw-intro">이야기를 준비하고, ${unit}별로 확인하며 완성하세요.</p><ol class="mw-steps"><li><span>01</span><div><strong>이야기 · 파일 준비</strong><p>${kind==='video'?'글·그림·콘티를 가져오세요.':'줄거리를 쓰거나 JSON과 참고 이미지를 가져오세요.'}</p></div></li><li><span>02</span><div><strong>${unit}별 생성 · 수정</strong><p>진행 상황을 보고 필요한 ${unit}만 수정하세요.</p></div></li><li><span>03</span><div><strong>저장 · 이어 만들기</strong><p>중간에 멈춰도 저장한 지점에서 계속하세요.</p></div></li></ol><div class="mw-empty-actions"><button type="button" data-workspace-action="start" class="mw-primary">${name} 만들기 시작 ↗</button><button type="button" data-workspace-action="library">저장한 작업 열기</button></div>`}
  </section>`;
  if(html===signature)return;signature=html;
  const scroll=root.querySelector('.mw-scenes')?.scrollLeft||0,focus=root.contains(document.activeElement)?{action:document.activeElement.dataset.workspaceAction,scene:document.activeElement.dataset.workspaceScene,filter:document.activeElement.dataset.workspaceFilter}:null;
  root.innerHTML=html;
  const strip=root.querySelector('.mw-scenes');if(strip)strip.scrollLeft=scroll;
  if(focus){const target=[...root.querySelectorAll('button')].find(el=>focus.action?el.dataset.workspaceAction===focus.action:focus.scene?el.dataset.workspaceScene===focus.scene:el.dataset.workspaceFilter===focus.filter);target?.focus({preventScroll:true});}
 }
 root.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button||button.disabled)return;
  if(button.dataset.workspaceFilter){filter=button.dataset.workspaceFilter;render();return;}
  const id=button.dataset.workspaceScene||selected;
  if(button.dataset.workspaceScene){selected=id;render();}
  const action=button.dataset.workspaceScene?'view':button.dataset.workspaceAction;if(!action)return;
  if(action==='current'){selected=data.items?.find(it=>it.active)?.id||selected;filter='all';render();root.querySelector('[data-workspace-scene][aria-pressed="true"]')?.scrollIntoView({block:'nearest',inline:'center'});}
  if(pending)return;
  try{pending=true;render();await onAction(action,action==='current'?selected:id);}
  catch(error){data={...data,message:error.message};}
  finally{pending=false;render();}
 });
 render();
 return {update(next){if(next.id!==data.id){filter='all';selected=null;}if(next.selectedId&&next.items?.some(it=>it.id===next.selectedId))selected=next.selectedId;data=next;render();}};
}
