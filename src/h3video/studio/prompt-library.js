// Original production templates. FRAME vendors this file for standalone builds.
export const cameras = [
  {id:'push',label:'천천히 다가가기',frame:'eye-level medium shot',motion:'a slow, steady push-in'},
  {id:'static',label:'고정 샷',frame:'a carefully composed static shot',motion:'a locked-off camera; only the subject moves'},
  {id:'track',label:'피사체 따라가기',frame:'eye-level tracking composition',motion:'a smooth lateral tracking shot following the subject'},
  {id:'orbit',label:'천천히 둘러보기',frame:'three-quarter view with a clear subject',motion:'a slow, small camera arc around the subject'},
  {id:'macro',label:'디테일 클로즈업',frame:'a close-up with shallow depth of field',motion:'a subtle macro push-in; keep the focal detail sharp'},
  {id:'wide',label:'공간을 넓게 보여주기',frame:'a wide establishing shot with readable depth',motion:'a slow wide pan revealing the environment'},
];
export const lights = [
  {id:'window',label:'부드러운 창가 빛',prompt:'soft natural window light, gentle shadows'},
  {id:'golden',label:'해 질 녘 따뜻한 빛',prompt:'warm golden-hour side light with natural highlights'},
  {id:'studio',label:'깔끔한 스튜디오',prompt:'diffused studio key light and a restrained rim light'},
  {id:'night',label:'차분한 야간 조명',prompt:'motivated practical night lighting, controlled contrast'},
  {id:'overcast',label:'흐린 날 자연광',prompt:'soft overcast daylight, neutral and consistent color'},
];
export const looks = [
  {id:'film',label:'시네마틱 실사',prompt:'cinematic live action, natural textures and restrained color'},
  {id:'documentary',label:'다큐멘터리',prompt:'observational documentary, believable natural details'},
  {id:'animation',label:'3D 애니메이션',prompt:'stylized 3D animation with consistent character design'},
  {id:'watercolor',label:'수채화 애니메이션',prompt:'hand-painted watercolor animation, soft paper texture'},
  {id:'graphic',label:'미니멀 그래픽',prompt:'minimal graphic composition with clean shapes'},
];
export const presets = [
  {id:'product',label:'제품·브랜드',hint:'궁금증 → 사용 장면 → 디테일 → 마무리',subject:'보온 텀블러',setting:'밝은 주방의 나무 테이블',hook:'매일 쓰는 물건, 이 차이를 보세요',cta:'내 일상에 맞는지 확인해 보세요',beats:[['첫인상','제품 전체와 사용하는 공간을 보여 준다.'],['쓰임새','제품을 사용하는 한 가지 동작을 보여 준다.'],['디테일','표면과 핵심 구조를 가까이 보여 준다.'],['일상의 변화','같은 제품을 놓은 실제 사용 장면을 보여 준다.'],['기억할 장면','제품을 화면 중심에 두고 자막 여백을 남긴다.']]},
  {id:'howto',label:'설명·사용법',hint:'문제 → 준비 → 핵심 단계 → 결과',subject:'책상 정리 방법',setting:'작은 작업실의 책상',hook:'이 순서로 하면 훨씬 간단해요',cta:'다음에 따라 할 수 있게 저장해 두세요',beats:[['왜 필요한가','해결하려는 상황을 한 화면으로 보여 준다.'],['준비하기','필요한 도구와 재료를 순서대로 놓는다.'],['핵심 단계','손의 한 가지 주요 동작을 가까이 보여 준다.'],['달라진 결과','같은 위치에서 정리된 결과를 보여 준다.'],['한 번 더 정리','완성한 상태를 고정 샷으로 보여 준다.']]},
  {id:'travel',label:'여행·공간',hint:'도착 → 작은 발견 → 현장감 → 여운',subject:'바닷가 산책길',setting:'해 질 무렵의 조용한 해안',hook:'잠깐 멈추고 싶은 풍경',cta:'다음 산책 코스로 기억해 두세요',beats:[['도착','장소 전체를 넓게 보여 준다.'],['발견','그 장소만의 작은 디테일을 보여 준다.'],['걷는 시선','길을 따라 천천히 이동하는 시선을 보여 준다.'],['머무는 순간','주인공이 잠시 풍경을 바라본다.'],['여운','처음과 연결되는 풍경으로 마무리한다.']]},
  {id:'food',label:'음식·레시피',hint:'완성 컷 → 재료 → 조리 → 맛의 디테일',subject:'따뜻한 토마토 수프',setting:'햇빛이 드는 집 주방',hook:'오늘 한 끼는 이렇게 준비해요',cta:'취향에 맞게 바꿔 만들어 보세요',beats:[['완성의 순간','완성한 음식을 먼저 보여 준다.'],['재료','핵심 재료를 같은 조리대 위에 놓는다.'],['만드는 과정','조리 과정의 한 가지 동작을 보여 준다.'],['질감','음식의 김과 표면 질감을 가까이 보여 준다.'],['식탁','완성된 접시를 식탁에 놓으며 마무리한다.']]},
  {id:'story',label:'짧은 이야기',hint:'궁금증 → 발견 → 선택 → 변화 → 결말',subject:'작은 우산을 든 여행자',setting:'비가 그친 골목',hook:'골목 끝에서 작은 일이 시작됐어요',cta:'당신이라면 어떤 선택을 했을까요?',beats:[['시작','주인공과 공간을 소개한다.'],['발견','주인공이 작은 변화를 알아차린다.'],['선택','주인공이 한 가지 행동을 선택한다.'],['변화','그 행동에 대한 주변의 반응을 보여 준다.'],['결말','처음과 달라진 주인공의 표정으로 마무리한다.']]},
  {id:'review',label:'체험·비교',hint:'질문 → 같은 조건 → 관찰 → 판단',subject:'가벼운 여행 가방',setting:'같은 조명 아래의 작업 테이블',hook:'내가 고를 때 확인하는 세 가지',cta:'자신의 사용 조건에 맞춰 골라 보세요',beats:[['질문','확인하려는 대상을 같은 화면에 보여 준다.'],['조건','같은 기준과 환경을 보여 준다.'],['관찰','직접 확인 가능한 한 가지 디테일을 보여 준다.'],['사용','실제로 사용하는 동작을 보여 준다.'],['판단','주요 관찰 지점을 다시 보여 준다.']]},
];
const choice=(rows,id)=>rows.find(row=>row.id===id)||rows[0];
const text=value=>String(value??'').trim();
export function directPrompt(base,{camera='push',light='window'}={}){
  const original=text(base).replace(/\n(?:Camera direction|Lighting direction):[^\n]*/g,'').trim();
  return [original,'Camera direction: '+choice(cameras,camera).motion+'.','Lighting direction: '+choice(lights,light).prompt+'.'].filter(Boolean).join('\n');
}
export function createDraft(input={}){
  const preset=choice(presets,input.preset),subject=text(input.subject)||preset.subject,setting=text(input.setting)||preset.setting;
  const duration=Number(input.duration??30),ratio=['9:16','16:9','1:1'].includes(input.ratio)?input.ratio:'9:16';
  if(!Number.isSafeInteger(duration)||duration<4)throw new Error('길이는 4초 이상의 정수로 적어 주세요.');
  const camera=choice(cameras,input.camera),light=choice(lights,input.light),look=choice(looks,input.look);
  const hook=text(input.hook)||preset.hook,cta=text(input.cta)||preset.cta;
  // Preserve the whole requested duration; only split into native 4–15s shots.
  const count=Math.max(Math.ceil(duration/15),Math.min(preset.beats.length,Math.floor(duration/4)));
  const base=Math.floor(duration/count),extra=duration%count;
  const shots=Array.from({length:count},(_,index)=>{
    const beat=preset.beats[count===1?0:Math.round(index*(preset.beats.length-1)/(count-1))];
    const visual=`${subject}. ${setting}. ${beat[1]}`;
    return {id:'draft-'+(index+1),title:beat[0],duration:base+(index<extra?1:0),visual,
      camera:camera.label,audio:'',caption:index===0?hook:index===count-1?cta:beat[0],transition:index===count-1?'페이드 아웃':'컷',
      imagePrompt:`Subject: ${subject}. Setting: ${setting}. Composition: ${camera.frame}. Lighting: ${light.prompt}. Style: ${look.prompt}. Aspect ratio ${ratio}. Preserve the same subject, clothing, product and location. Leave caption-safe negative space; no rendered text.`,
      videoPrompt:directPrompt(`Subject: ${subject}. Setting: ${setting}. Action: ${beat[1]} Style: ${look.prompt}. Preserve subject identity, clothing, props and spatial direction. One clear action; no rendered captions.`,{camera:camera.id,light:light.id}),
      negativePrompt:'Changing identity, inconsistent clothing or product details, flicker, warped objects, watermarks, rendered subtitles.'};
  });
  return {title:subject+' · '+preset.label,idea:`${subject}. ${setting}. ${hook}. ${cta}`,genre:preset.id==='product'?'브랜드 광고':preset.id==='travel'?'여행 영상':preset.id==='howto'?'설명 영상':'숏폼 스토리',style:look.label,ratio,duration,count,
    continuity:`${subject}. ${setting}. ${look.prompt}. ${light.prompt}. Camera language: ${camera.motion}. 인물·제품·의상·소품은 장면마다 유지합니다.`,look:look.label+' · '+light.label,shots};
}
export function draftProject(draft){
  return {version:1,brief:{idea:draft.idea,genre:draft.genre,style:draft.style,ratio:draft.ratio,duration:draft.duration,count:draft.shots.length,continuity:draft.continuity,cast:[]},board:{title:draft.title,logline:draft.idea,look:draft.look,scenes:draft.shots},origin:'manual',updatedAt:new Date().toISOString()};
}
export function draftText(draft){
  let start=0;return draft.title+`\n${draft.ratio} · ${draft.duration}초 · ${draft.shots.length}개 장면\n`+draft.shots.map((shot,i)=>{const at=start;start+=shot.duration;return `\n${i+1}. ${shot.title} (${at}–${start}초)\n자막: ${shot.caption}\n첫 프레임: ${shot.imagePrompt}\n영상: ${shot.videoPrompt}\n피할 요소: ${shot.negativePrompt}\n`;}).join('');
}

const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const options=rows=>rows.map(row=>`<option value="${row.id}">${row.label}</option>`).join('');
/** @param {HTMLElement} host @param {{onApply?:(draft:any)=>any,applyLabel?:string,dark?:boolean}} options */
export function mountPromptLibrary(host,{onApply,applyLabel='이 초안 사용',dark=false}={}){
  const shadow=host.shadowRoot||host.attachShadow({mode:'open'});let draft=null,disposed=false;
  shadow.innerHTML=`<style>
  :host{display:block;min-width:0;margin:18px 0;font:14px/1.6 system-ui,sans-serif;color:${dark?'#e7ece9':'#252a26'};--panel:${dark?'#151c1a':'#f5f5ef'};--edge:${dark?'#3b4841':'#d3d8cd'};--field:${dark?'#0e1411':'#fff'};--accent:${dark?'#91d9b5':'#245c43'}}*{box-sizing:border-box}details{border:1px solid var(--edge);border-radius:14px;background:var(--panel)}summary{padding:16px 18px;cursor:pointer;font-weight:700;font-size:16px}section{padding:0 18px 18px}p{margin:5px 0 14px;opacity:.8}input,select,textarea,button{font:inherit}input,select,textarea{width:100%;min-width:0;min-height:44px;border:1px solid var(--edge);border-radius:8px;background:var(--field);color:inherit;padding:9px}textarea{resize:vertical;overflow-wrap:anywhere}label{display:block;font-size:13px;font-weight:600}label input,label select,label textarea{margin-top:5px}button{min-height:44px;border:1px solid var(--edge);border-radius:9px;background:var(--field);color:inherit;padding:9px 12px;cursor:pointer}button:disabled{opacity:.5;cursor:wait}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:3px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:12px 0}.preset{text-align:left}.preset[aria-pressed=true]{border:2px solid var(--accent);padding:8px 11px}.preset b,.preset small{display:block}.preset small{font-size:11px;opacity:.7}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin:15px 0}.primary{background:var(--accent);color:${dark?'#102119':'#fff'};border-color:var(--accent);font-weight:700}.preview article{border-top:1px solid var(--edge);padding:12px 0}.preview header{display:flex;gap:8px;align-items:center;margin-bottom:8px}.preview header b{flex:1}.preview article details{margin-top:8px;border-radius:8px}.preview article summary{font-size:13px;padding:9px}.preview article details label{margin:9px}.note{font-size:12px}.status{white-space:pre-line;overflow-wrap:anywhere}h3{margin:12px 0 0;font-size:15px}[hidden]{display:none!important}@media(max-width:520px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.fields{grid-template-columns:minmax(0,1fr)}section{padding:0 12px 12px}summary{padding:14px 12px}}
  </style><details><summary>템플릿으로 기획 · 카메라와 조명 고르기</summary><section><p>주제와 연출을 바꿔 직접 편집할 장면 초안을 만드세요. AI 호출 없이 시작하며, 적용 전에는 현재 작업을 바꾸지 않습니다.</p><label>템플릿 검색<input type="search" data-search placeholder="제품, 음식, 여행, 이야기…"></label><div class="grid" data-presets>${presets.map((p,i)=>`<button type="button" class="preset" data-preset="${p.id}" aria-pressed="${i===0}"><b>${p.label}</b><small>${p.hint}</small></button>`).join('')}</div><form><div class="fields"><label>주제·제품·주인공<input name="subject" required value="${presets[0].subject}"></label><label>장소·상황<input name="setting" value="${presets[0].setting}"></label><label>초안 길이 (초)<input name="duration" type="number" min="4" step="1" required value="30"></label><label>화면 비율<select name="ratio" aria-label="화면 비율"><option>9:16</option><option>16:9</option><option>1:1</option></select></label><label>카메라 움직임<select name="camera" aria-label="카메라 움직임">${options(cameras)}</select></label><label>조명<select name="light" aria-label="조명">${options(lights)}</select></label><label>비주얼 스타일<select name="look" aria-label="비주얼 스타일">${options(looks)}</select></label><label>첫 문장 · 훅<input name="hook" value="${presets[0].hook}"></label><label>마지막 문장 · 행동 유도<input name="cta" value="${presets[0].cta}"></label></div><div class="actions"><button type="submit">새 장면 초안 미리보기</button></div></form><div class="preview" data-preview></div><div class="actions" data-output hidden><button type="button" class="primary" data-apply>${escape(applyLabel)}</button><button type="button" data-copy>프롬프트 전체 복사</button><button type="button" data-download>콘티 JSON 받기</button></div><p class="note">구성 초안이며 생성된 이미지·영상이 아닙니다. 영상 생성은 적용한 장면을 확인한 뒤 제작 화면에서 실행하세요.</p><p role="status" class="status" aria-live="polite"></p></section></details>`;
  const q=s=>shadow.querySelector(s),form=q('form'),status=q('[role=status]');let selected='product';
  q('[data-search]').oninput=event=>{const term=event.target.value.trim().toLowerCase();shadow.querySelectorAll('[data-preset]').forEach(button=>{button.hidden=!button.textContent.toLowerCase().includes(term);});};
  shadow.querySelectorAll('[data-preset]').forEach(button=>button.onclick=()=>{
    const before=choice(presets,selected),next=choice(presets,button.dataset.preset);selected=next.id;
    for(const key of ['subject','setting','hook','cta'])if(!form.elements[key].value.trim()||form.elements[key].value===before[key])form.elements[key].value=next[key];
    shadow.querySelectorAll('[data-preset]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
    status.textContent=next.label+'을 골랐습니다. 새 초안을 미리 확인하세요.';
  });
  form.onsubmit=event=>{
    event.preventDefault();if(!form.reportValidity())return;
    try{
      draft=createDraft({preset:selected,...Object.fromEntries(new FormData(form))});
      q('[data-preview]').innerHTML=`<h3>${escape(draft.title)} · ${draft.shots.length}장면 · ${draft.duration}초</h3>`+draft.shots.map((shot,i)=>`<article><header><span>${String(i+1).padStart(2,'0')}</span><b>${escape(shot.title)}</b><span>${shot.duration}초</span></header><label>자막<input data-index="${i}" data-field="caption" value="${escape(shot.caption)}"></label><details><summary>이미지·영상 프롬프트 편집</summary>${[['visual','화면과 행동'],['imagePrompt','첫 프레임 이미지'],['videoPrompt','영상 생성 프롬프트'],['negativePrompt','피할 요소']].map(([key,label])=>`<label>${label}<textarea rows="3" data-index="${i}" data-field="${key}">${escape(shot[key])}</textarea></label>`).join('')}</details></article>`).join('');
      q('[data-output]').hidden=false;status.textContent='장면과 자막을 고친 다음 적용하세요. 아직 현재 작업은 바뀌지 않았습니다.';
    }catch(error){status.textContent=error.message;}
  };
  q('[data-preview]').oninput=event=>{const {index,field}=event.target.dataset;if(draft&&draft.shots[index]&&['caption','visual','imagePrompt','videoPrompt','negativePrompt'].includes(field))draft.shots[index][field]=event.target.value;};
  q('[data-apply]').onclick=async()=>{
    if(!draft||!onApply)return;const button=q('[data-apply]');button.disabled=true;
    try{await onApply(structuredClone(draft));if(!disposed)status.textContent='초안을 적용했습니다. 제작 화면에서 장면과 길이를 확인하세요.';}catch(error){if(!disposed)status.textContent=error.message;}finally{if(!disposed)button.disabled=false;}
  };
  q('[data-copy]').onclick=async()=>{try{await navigator.clipboard.writeText(draftText(draft));status.textContent='장면별 프롬프트를 복사했습니다.';}catch{status.textContent='복사 권한이 없습니다. 콘티 JSON으로 내려받아 주세요.';}};
  q('[data-download]').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(draftProject(draft),null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='video-prompt-storyboard.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  return {dispose(){disposed=true;shadow.replaceChildren();}};
}

export function mountDirections(host,textarea){
  const shadow=host.attachShadow({mode:'open'});
  shadow.innerHTML=`<style>:host{display:block;margin:12px 0;font:13px/1.6 system-ui,sans-serif}section{border:1px solid #87998d88;border-radius:10px;padding:12px}.fields{display:flex;flex-wrap:wrap;gap:10px}label{display:block;flex:1;min-width:140px}select,button{font:inherit;min-height:44px;padding:8px;border:1px solid #87998d88;border-radius:7px;background:transparent;color:inherit}select{display:block;width:100%}button{margin-top:10px;cursor:pointer}p{margin:7px 0 0;font-size:12px}select:focus-visible,button:focus-visible{outline:3px solid #559f79;outline-offset:2px}</style><section><b>연출 도우미</b><div class="fields"><label>카메라 움직임<select data-camera aria-label="카메라 움직임">${options(cameras)}</select></label><label>조명<select data-light aria-label="조명">${options(lights)}</select></label></div><button type="button">영상 프롬프트에 연출 적용</button><p role="status" aria-live="polite">피사체와 장면 설명을 유지하며 선택한 연출을 붙입니다.</p></section>`;
  shadow.querySelector('button').onclick=()=>{
    textarea.value=directPrompt(textarea.value,{camera:shadow.querySelector('[data-camera]').value,light:shadow.querySelector('[data-light]').value});
    textarea.dispatchEvent(new Event('input',{bubbles:true}));shadow.querySelector('[role=status]').textContent='연출을 적용했습니다. 저장 전에 프롬프트를 확인하세요.';
  };
}
