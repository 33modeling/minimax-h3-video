export function mountStudioNavigation(){
 const top=document.querySelector('.top');
 if(!top)return;
 const measure=()=>document.documentElement.style.setProperty('--studio-header-height',top.getBoundingClientRect().height+'px');
 new ResizeObserver(measure).observe(top);measure();
 const connection=document.querySelector('.studio-connection');
 document.querySelector('[data-studio-open]')?.addEventListener('click',()=>{connection.open=false;document.getElementById('openVideoStudio').click();});
 for(const link of document.querySelectorAll('.studio-nav a'))link.addEventListener('click',()=>{connection.open=false;});
 document.addEventListener('click',event=>{if(connection.open&&!connection.contains(event.target))connection.open=false;});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&connection.open){connection.open=false;connection.querySelector('summary').focus();}
  const tab=event.target.closest('[role=tab]');if(!tab||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  const tabs=[...tab.closest('[role=tablist]').querySelectorAll('[role=tab]')],index=tabs.indexOf(tab);
  const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  event.preventDefault();
  const scope=tab.closest('#videoWorkbench')||tab.closest('[role=tablist]');
  const selector=tabs[next].dataset.mode?`[role=tab][data-mode="${tabs[next].dataset.mode}"]`:`[role=tab][data-tab="${tabs[next].dataset.tab}"]`;
  let observer,timer;
  const focus=()=>{const updated=scope.querySelector(selector);if(updated?.getAttribute('aria-selected')!=='true')return;updated.focus();observer?.disconnect();clearTimeout(timer);};
  observer=new MutationObserver(focus);observer.observe(scope,{childList:true,subtree:true,attributes:true,attributeFilter:['aria-selected']});
  timer=setTimeout(()=>observer.disconnect(),31000);tabs[next].click();focus();
 });
}
