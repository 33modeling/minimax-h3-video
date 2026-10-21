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
// Small code-native illustrations describe the template, never generated footage.
const artwork={
 product:'<ellipse cx="100" cy="95" rx="42" ry="7" fill="#203c3518"/><path d="M80 30h40l-4 62H84z" fill="#427565"/><rect x="79" y="23" width="42" height="10" rx="4" fill="#254d40"/><path d="M89 38v42" stroke="#ffffff55" stroke-width="3"/><path d="M53 42h10m-5-5v10M142 65h10m-5-5v10" stroke="#8b9b72" stroke-width="2"/>',
 howto:'<rect x="44" y="31" width="54" height="62" rx="7" fill="#ffffffb0"/><rect x="89" y="22" width="67" height="72" rx="8" fill="#cfb995"/><path d="m102 43 5 5 9-10m-14 24 5 5 9-10m8-11h20m-20 18h20M101 81h43" stroke="#755a3d" stroke-width="2.5" fill="none"/>',
 travel:'<circle cx="139" cy="34" r="16" fill="#e5ae62"/><path d="m0 105 68-70 65 70" fill="#85a99a"/><path d="m68 105 64-50 68 50" fill="#4d786a"/><path d="M0 102q65-28 110 0t90-5v23H0" fill="#c3d8c4"/>',
 food:'<ellipse cx="100" cy="67" rx="51" ry="33" fill="#ffffffa8"/><ellipse cx="100" cy="65" rx="39" ry="25" fill="#b9583f"/><path d="M79 65q20-22 41 0M83 73q17-17 34 0" stroke="#e8b88c" stroke-width="3" fill="none"/><path d="m98 49 7-9 8 11" fill="#6a8860"/><path d="M36 41v49m129-49v49" stroke="#94745b" stroke-width="3"/>',
 story:'<path d="M61 105V54a39 39 0 0 1 78 0v51" fill="#8895af"/><path d="M77 105V55a23 23 0 0 1 46 0v50" fill="#dce0eb"/><circle cx="100" cy="63" r="8" fill="#5d6685"/><path d="M88 100V83a12 12 0 0 1 24 0v17" fill="#5d6685"/><circle cx="40" cy="34" r="3" fill="#a199b3"/><path d="m156 38 3 6 6 3-6 3-3 6-3-6-6-3 6-3z" fill="#a199b3"/>',
 review:'<rect x="47" y="35" width="44" height="59" rx="8" fill="#a9a6b9"/><rect x="111" y="25" width="44" height="69" rx="8" fill="#72748e"/><path d="M56 78h26m39-7h24" stroke="#ffffffa0" stroke-width="3"/><path d="m95 57 5-5 5 5m-10 9 5 5 5-5" stroke="#72748e" stroke-width="2" fill="none"/>'
};
const art=id=>`<svg viewBox="0 0 200 120" fill="none" aria-hidden="true">${artwork[id]}</svg>`;
const palettes={product:'#e5eee4',howto:'#f0e7d7',travel:'#e0ebe7',food:'#f3e3d5',story:'#e6e5ef',review:'#e7e7ef'};
/** @param {HTMLElement} host @param {{onApply?:(draft:any)=>any,applyLabel?:string,dark?:boolean,theme?:'light'|'auto'}} options */
export function mountPromptLibrary(host,{onApply,applyLabel='이 초안 사용',dark=false,theme='light'}={}){
  const shadow=host.shadowRoot||host.attachShadow({mode:'open'});let draft=null,disposed=false;
  const darkColors='--ink:#e8f0ec;--muted:#a6b9af;--panel:#141e1b;--surface:#1b2923;--edge:#35493e;--field:#101a16;--accent:#9ed6b5;--soft:#263c30;--on-accent:#12271b;color-scheme:dark;';
  shadow.innerHTML=`<style>
  :host{display:block;container-type:inline-size;min-width:0;margin:20px 0;font:14px/1.6 system-ui,sans-serif;--ink:#243c30;--muted:#627568;--panel:#f9faf6;--surface:#fff;--edge:#dbe2d7;--field:#fff;--accent:#305c43;--soft:#eaf0e5;--on-accent:#fff;color:var(--ink);${dark?darkColors:''}}
  ${theme==='auto'?`@media(prefers-color-scheme:dark){:host{${darkColors}}}`:''}
  *{box-sizing:border-box}input,select,textarea,button{font:inherit;color:inherit}button,summary{-webkit-tap-highlight-color:transparent}button{cursor:pointer}button:disabled{opacity:.5;cursor:wait}[hidden]{display:none!important}
  .library{border:1px solid var(--edge);border-radius:20px;background:var(--panel);overflow:clip;box-shadow:0 4px 20px #16291a05}
  summary{cursor:pointer;list-style:none}summary::-webkit-details-marker{display:none}.library>summary{padding:22px;display:flex;align-items:center;gap:14px;background:linear-gradient(110deg,var(--soft),var(--panel))}
  .mark{width:44px;height:44px;border-radius:13px;background:var(--accent);color:var(--on-accent);display:grid;place-items:center;flex:none}.mark svg{width:25px;height:25px}.summary-copy{flex:1;min-width:0}.eyebrow{display:block;letter-spacing:1.7px;font:10px/1.6 ui-monospace,monospace;color:var(--muted);margin-bottom:4px}.summary-copy strong{display:block;font-size:17px;letter-spacing:-.5px;line-height:1.5}.summary-copy small{display:block;color:var(--muted);font-size:12px;margin-top:3px}.chevron{font-size:22px;transition:transform .2s}.library[open]>.library-summary .chevron{transform:rotate(90deg)}
  .body{padding:0 22px 20px}.step-head{display:flex;gap:10px;align-items:center;margin:22px 0 12px}.step-num{font:11px ui-monospace,monospace;color:var(--muted);border:1px solid var(--edge);width:28px;height:28px;display:grid;place-items:center;border-radius:50%}.step-head h3{margin:0;font-size:15px;letter-spacing:-.3px}.step-head small{margin-left:auto;color:var(--muted);font-size:11px}
  input,select,textarea{width:100%;min-width:0;min-height:44px;border:1px solid var(--edge);border-radius:10px;background:var(--field);padding:10px 12px;transition:border-color .15s}textarea{resize:vertical;overflow-wrap:anywhere}label{display:block;font-size:12px;font-weight:600;color:var(--muted)}label input,label select,label textarea{margin-top:6px;color:var(--ink);font-weight:400;font-size:14px}input:hover,select:hover,textarea:hover{border-color:var(--accent)}
  button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible,.shot-list:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
  button{min-height:44px;border:1px solid var(--edge);border-radius:10px;background:var(--surface);padding:10px 14px;font-weight:600}button:hover:not(:disabled){border-color:var(--accent)}.search{position:relative}.search input{padding-left:38px}.search svg{position:absolute;left:13px;bottom:14px;width:17px;height:17px;color:var(--muted)}
  .grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}.preset{text-align:left;padding:0;border-radius:13px;overflow:hidden;position:relative;transition:border-color .15s,box-shadow .15s}.preset[aria-pressed=true]{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent)}.preset[aria-pressed=true]::after{content:'✓';position:absolute;top:8px;right:8px;border-radius:50%;width:23px;height:23px;background:var(--accent);color:var(--on-accent);text-align:center;font-size:13px}.art{display:block;background:var(--art);height:90px}.art svg{display:block;width:100%;height:100%}.preset-copy{display:block;padding:11px 12px}.preset b{display:block;font-size:13px}.preset small{display:block;color:var(--muted);font-size:11px;line-height:1.6;font-weight:400;margin-top:3px}.empty-search{color:var(--muted);text-align:center;padding:18px;font-size:13px}
  .studio-workspace{border-top:1px solid var(--edge);margin-top:22px}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.full{grid-column:1/-1}.advanced{border-top:1px solid var(--edge);margin-top:18px;padding-top:3px}.advanced>summary{min-height:44px;display:flex;align-items:center;justify-content:space-between;color:var(--muted);font-size:12px}.advanced>summary::after{content:'+';font-size:18px}.advanced[open]>summary::after{content:'−'}.advanced .fields{padding:8px 0}.actions{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 0}.primary{background:var(--accent);color:var(--on-accent);border-color:var(--accent)}form .actions button{width:100%}.preview-pane{min-width:0}.preview-empty{display:grid;place-content:center;text-align:center;min-height:210px;border:1px dashed var(--edge);border-radius:14px;color:var(--muted);padding:24px}.preview-empty svg{width:60px;height:42px;margin:0 auto 12px}.preview-empty b{font-size:14px;color:var(--ink)}.preview-empty p{font-size:12px;margin:6px 0 0}
  .draft-heading{display:flex;gap:8px;align-items:start;margin-bottom:14px}.draft-heading h4{margin:0;flex:1;min-width:0;overflow-wrap:anywhere;font-size:15px;line-height:1.6;letter-spacing:-.3px}.badge{white-space:nowrap;background:var(--soft);color:var(--accent);border-radius:6px;padding:3px 7px;font:11px/1.7 ui-monospace,monospace}.timeline{display:flex;gap:4px;overflow:hidden;border-radius:6px;margin-bottom:8px}.timeline span{height:5px;min-width:1px;background:var(--accent);opacity:.6}.timeline span:nth-child(even){opacity:.3}.draft-meta{font-size:12px;color:var(--muted);margin:0 0 14px}.shot-list{max-height:540px;overflow:auto;scrollbar-width:thin;scrollbar-color:var(--edge) transparent;padding:3px;margin:-3px}
  .preview article{border:1px solid var(--edge);background:var(--surface);border-radius:13px;padding:14px;margin-bottom:10px}.preview header{display:flex;gap:10px;align-items:center;margin-bottom:10px}.preview header b{flex:1;font-size:13px}.shot-index{font:11px ui-monospace,monospace;color:var(--accent);background:var(--soft);border-radius:6px;padding:5px 7px}.shot-time{font:11px ui-monospace,monospace;color:var(--muted)}.preview article details{margin-top:8px}.preview article summary{font-size:12px;color:var(--muted);min-height:38px;display:flex;align-items:center;gap:6px}.preview article summary::before{content:'›';font-size:17px}.preview article details[open]>summary::before{transform:rotate(90deg)}.preview article details label{margin:10px 0}.preview textarea{font-size:12px;line-height:1.7}.output{background:var(--soft);border:1px solid var(--edge);border-radius:13px;padding:12px;margin-top:12px}.output .primary{width:100%}.export-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:5px}.export-actions button{flex:1;border:0;background:transparent;font-size:12px;padding:6px;min-height:40px}
  .note{font-size:11px;color:var(--muted);margin:18px 0 0;line-height:1.8}.status{font-size:12px;white-space:pre-line;overflow-wrap:anywhere;color:var(--accent);margin:10px 0 0}.status:empty{display:none}
  @container(min-width:980px){.studio-workspace{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:28px}.preview-pane{border-left:1px solid var(--edge);padding-left:28px}.art{height:110px}.preset-copy{display:flex;align-items:center;gap:10px}.preset small{flex:1;margin:0}.preview-empty{min-height:460px}}
  @container(max-width:560px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.art{height:75px}.preset small{display:none}.library>summary{padding:17px 15px;gap:10px}.summary-copy strong{font-size:15px}.summary-copy small{font-size:11px}.mark{width:38px;height:38px}.body{padding:0 15px 16px}.fields{gap:12px}.shot-list{max-height:440px}.step-head small{display:none}}
  @container(max-width:340px){.fields{grid-template-columns:minmax(0,1fr)}.full{grid-column:auto}.body{padding-inline:12px}.summary-copy small{display:none}.summary-copy strong{font-size:14px}.eyebrow{font-size:9px}.shot-list{max-height:none}.draft-heading{flex-wrap:wrap}.draft-heading h4{flex-basis:100%}}
  @media(prefers-reduced-motion:reduce){*{transition:none!important}}@media print{.library{display:none}}
  </style><details class="library"><summary class="library-summary"><span class="mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 9h18M8 4v5m8-5v5m-6 3 5 3-5 3z"/></svg></span><span class="summary-copy"><span class="eyebrow">THE PROMPT STUDIO</span><strong>템플릿으로 기획 · 카메라와 조명 고르기</strong><small>6가지 구성에서 시작하는 나만의 장면</small></span><span class="chevron" aria-hidden="true">›</span></summary><div class="body">
  <div class="step-head"><span class="step-num">01</span><h3>이야기의 출발점</h3><small>템플릿을 골라 주세요</small></div>
  <label class="search">템플릿 검색<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="8" cy="8" r="5.5"/><path d="m12 12 5 5"/></svg><input type="search" data-search placeholder="제품, 음식, 여행, 이야기…"></label>
  <div class="grid" data-presets>${presets.map((p,i)=>`<button type="button" class="preset" data-preset="${p.id}" aria-pressed="${i===0}"><span class="art" style="--art:${palettes[p.id]}">${art(p.id)}</span><span class="preset-copy"><b>${p.label}</b><small>${p.hint}</small></span></button>`).join('')}</div><p class="empty-search" data-empty-search hidden>맞는 템플릿이 없어요. 다른 단어로 검색해 보세요.</p>
  <div class="studio-workspace"><form><div class="step-head"><span class="step-num">02</span><h3>나만의 연출</h3><small>주제와 분위기 설정</small></div><div class="fields"><label class="full">주제·제품·주인공<input name="subject" required value="${presets[0].subject}"></label><label class="full">장소·상황<input name="setting" value="${presets[0].setting}"></label><label>초안 길이 (초)<input name="duration" type="number" min="4" step="1" required value="30"></label><label>화면 비율<select name="ratio" aria-label="화면 비율"><option>9:16</option><option>16:9</option><option>1:1</option></select></label><label>카메라 움직임<select name="camera" aria-label="카메라 움직임">${options(cameras)}</select></label><label>조명<select name="light" aria-label="조명">${options(lights)}</select></label><label class="full">비주얼 스타일<select name="look" aria-label="비주얼 스타일">${options(looks)}</select></label></div><details class="advanced"><summary>첫 문장과 마무리 직접 쓰기</summary><div class="fields"><label class="full">첫 문장 · 훅<input name="hook" value="${presets[0].hook}"></label><label class="full">마지막 문장 · 행동 유도<input name="cta" value="${presets[0].cta}"></label></div></details><div class="actions"><button class="primary" type="submit">새 장면 초안 미리보기</button></div></form>
  <section class="preview-pane" aria-label="장면 초안 검토"><div class="step-head"><span class="step-num">03</span><h3>장면 검토</h3><small>자막과 프롬프트 편집</small></div><div class="preview" data-preview><div class="preview-empty"><svg viewBox="0 0 60 42" fill="none" stroke="currentColor" aria-hidden="true"><rect x="1" y="7" width="18" height="28" rx="3" opacity=".35"/><rect x="21" y="2" width="18" height="38" rx="3"/><rect x="41" y="7" width="18" height="28" rx="3" opacity=".35"/><path d="m27 15 9 6-9 6z"/></svg><b>이야기가 장면이 되는 곳</b><p>연출 설정을 채우고 초안을 미리 확인하세요.</p></div></div><div class="output" data-output hidden><button type="button" class="primary" data-apply>${escape(applyLabel)}</button><div class="export-actions"><button type="button" data-copy>프롬프트 전체 복사</button><button type="button" data-download>콘티 JSON 받기</button></div></div></section></div>
  <p class="note">템플릿 초안은 AI 호출 없이 만들 수 있습니다. 장면을 적용한 뒤 제작 화면에서 이미지·영상 생성을 실행하세요.</p><p role="status" class="status" aria-live="polite"></p></div></details>`;
  const q=s=>shadow.querySelector(s),form=q('form'),status=q('[role=status]');let selected='product';
  q('[data-search]').oninput=event=>{const term=event.target.value.trim().toLowerCase();let visible=0;shadow.querySelectorAll('[data-preset]').forEach(button=>{button.hidden=!button.textContent.toLowerCase().includes(term);if(!button.hidden)visible++;});q('[data-empty-search]').hidden=visible>0;};
  shadow.querySelectorAll('[data-preset]').forEach(button=>button.onclick=()=>{
    const before=choice(presets,selected),next=choice(presets,button.dataset.preset);selected=next.id;
    for(const key of ['subject','setting','hook','cta'])if(!form.elements[key].value.trim()||form.elements[key].value===before[key])form.elements[key].value=next[key];
    shadow.querySelectorAll('[data-preset]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
    status.textContent=next.label+'을 골랐습니다. 새 초안을 미리 확인하세요.';
  });
  form.onsubmit=event=>{
    event.preventDefault();if(!form.reportValidity())return;
    try{
      draft=createDraft({preset:selected,...Object.fromEntries(new FormData(form))});let start=0;
      q('[data-preview]').innerHTML=`<div class="draft-heading"><h4>${escape(draft.title)}</h4><span class="badge">${escape(draft.ratio)}</span></div><div class="timeline" aria-hidden="true">${draft.shots.map(shot=>`<span style="flex:${shot.duration}"></span>`).join('')}</div><p class="draft-meta">${draft.shots.length}장면 · 전체 ${draft.duration}초 · ${escape(draft.style)}</p><div class="shot-list" tabindex="0" aria-label="장면별 자막과 프롬프트">`+draft.shots.map((shot,i)=>{const at=start;start+=shot.duration;return `<article><header><span class="shot-index">${String(i+1).padStart(2,'0')}</span><b>${escape(shot.title)}</b><span class="shot-time">${at}–${start}초</span></header><label>자막<input data-index="${i}" data-field="caption" value="${escape(shot.caption)}"></label><details><summary>이미지·영상 프롬프트 편집</summary>${[['visual','화면과 행동'],['imagePrompt','첫 프레임 이미지'],['videoPrompt','영상 생성 프롬프트'],['negativePrompt','피할 요소']].map(([key,label])=>`<label>${label}<textarea rows="3" data-index="${i}" data-field="${key}">${escape(shot[key])}</textarea></label>`).join('')}</details></article>`;}).join('')+'</div>';
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
