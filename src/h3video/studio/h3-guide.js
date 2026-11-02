const sections=[...document.querySelectorAll('.h3-section')],search=document.querySelector('#guide-search');
const count=document.querySelector('#guide-count');
function filter(){const terms=search.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);let n=0;for(const s of sections){s.hidden=!terms.every(t=>s.textContent.toLocaleLowerCase().includes(t));if(!s.hidden)n++;}count.textContent=`${n} / ${sections.length}개 항목`;document.querySelector('#guide-empty').hidden=!!n;}
search.addEventListener('input',filter);filter();
document.querySelector('#guide-open').onclick=()=>sections.filter(s=>!s.hidden).forEach(s=>{s.open=true;s.querySelectorAll('details').forEach(d=>d.open=true);});
document.querySelector('#guide-close').onclick=()=>sections.forEach(s=>{s.open=false;s.querySelectorAll('details').forEach(d=>d.open=false);});
function reveal(){const section=sections.find(s=>'#'+s.id===location.hash);if(section){search.value='';filter();section.open=true;section.scrollIntoView({block:'start'});}}
window.addEventListener('hashchange',reveal);reveal();
for(const pre of document.querySelectorAll('pre')){const button=document.createElement('button');button.className='h3-copy';button.type='button';button.textContent='복사';button.setAttribute('aria-label','예제 명령·내용 복사');button.onclick=async()=>{try{await navigator.clipboard.writeText(pre.querySelector('code').textContent);button.textContent='복사됨';}catch{const selection=getSelection(),range=document.createRange();range.selectNodeContents(pre.querySelector('code'));selection.removeAllRanges();selection.addRange(range);button.textContent='선택됨 · 직접 복사';}setTimeout(()=>button.textContent='복사',2400);};pre.append(button);}

for(const a of document.querySelectorAll('.h3-nav a'))a.addEventListener('click',()=>{const target=sections.find(s=>'#'+s.id===a.hash);if(target){search.value='';filter();target.open=true;target.scrollIntoView({block:'start'});}});
