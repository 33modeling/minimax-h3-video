const sections=[...document.querySelectorAll('.h3-section')],search=document.querySelector('#guide-search');
const cards=[...document.querySelectorAll('[data-guide-feature]')],count=document.querySelector('#guide-count');
let category='edit';
function filter(){
  const terms=search.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  let features=0,technical=0;
  for(const section of sections){const feature=section.dataset.category;const match=terms.every(t=>section.textContent.toLocaleLowerCase().includes(t));section.hidden=feature?!match||!(category==='all'||category===feature):terms.length?!match:false;if(!section.hidden){if(feature)features++;else technical++;}}
  for(const card of cards){const section=document.getElementById('feature-'+card.dataset.guideFeature);card.hidden=section.hidden;}
  count.textContent=`${features}개 기능${terms.length?` · 설치·운영 ${technical}개 항목`:''}`;
  document.querySelector('#guide-empty').hidden=features+ (terms.length?technical:0)>0;
  const advanced=document.querySelector('#installation');advanced.hidden=Boolean(terms.length&&!technical);if(terms.length&&technical)advanced.open=true;
  for(const b of document.querySelectorAll('[data-guide-category]'))b.setAttribute('aria-pressed',String(b.dataset.guideCategory===category));
}
search.addEventListener('input',()=>{if(search.value.trim())category='all';filter();});
document.querySelectorAll('[data-guide-category]').forEach(button=>button.addEventListener('click',()=>{category=button.dataset.guideCategory;filter();}));
document.querySelector('#guide-open').onclick=()=>sections.filter(s=>!s.hidden).forEach(s=>{s.open=true;s.querySelectorAll('details').forEach(d=>d.open=true);});
document.querySelector('#guide-close').onclick=()=>sections.forEach(s=>{s.open=false;s.querySelectorAll('details').forEach(d=>d.open=false);});
function reveal(){let id;try{id=decodeURIComponent(location.hash.slice(1));}catch{return;}const target=document.getElementById(id);if(!target)return;search.value='';if(target.dataset.category)category=target.dataset.category;else if(target.closest('#installation'))document.querySelector('#installation').open=true;filter();for(let p=target;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;target.scrollIntoView({block:'start'});}
window.addEventListener('hashchange',reveal);
for(const a of document.querySelectorAll('a[href^="#"]'))a.addEventListener('click',()=>{if(a.hash===location.hash)reveal();});
for(const pre of document.querySelectorAll('pre')){const button=document.createElement('button');button.className='h3-copy';button.type='button';button.textContent='복사';button.setAttribute('aria-label','예제 명령·프롬프트 복사');button.onclick=async()=>{try{await navigator.clipboard.writeText(pre.querySelector('code').textContent);button.textContent='복사됨';}catch{const selection=getSelection(),range=document.createRange();range.selectNodeContents(pre.querySelector('code'));selection.removeAllRanges();selection.addRange(range);button.textContent='선택됨 · 직접 복사';}setTimeout(()=>button.textContent='복사',2400);};pre.append(button);}
filter();if(location.hash)reveal();
