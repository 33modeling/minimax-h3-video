import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir,mkdtemp} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {resolve,extname} from 'node:path';
import net from 'node:net';
net.Server.prototype.listen=()=>{throw Error('Web listeners prohibited');};
const require=createRequire(import.meta.url),{chromium}=require('/home/kms/dev/minimax-h3-video/node_modules/playwright');
const root=process.env.H3_SOURCE||resolve(import.meta.dirname,'../..'),build=process.env.H3_BUILD||root+'/dist-ui',out=process.env.H3_EVIDENCE||'/tmp/h3-ui-audit-20261102/after';
await mkdir(out,{recursive:true});const temp=await mkdtemp('/tmp/h3-ui-fixture-');
execFileSync('python3',['-B',root+'/tests/feature-fixture.py',temp],{env:{...process.env,PYTHONPATH:root+'/src'}});
const {FEATURES}=await import(root+'/src/h3video/studio/features.js');
const fixture=JSON.parse(await readFile(temp+'/fixture.json')),video=await readFile(fixture.video);
const project=structuredClone(fixture.uploaded);project.title='내 영상 교정 · 촬영본과 완성본을 비교하는 편집 프로젝트';
project.clips[0].id='first';project.clips[0].label='아침 주방의 제품 소개';project.clips[0].prompt='인물과 제품을 유지하며 자연스럽게 밝기를 조정한다.';
const second=structuredClone(project.clips[0]);second.id='second';second.label='제품 디테일과 마무리';project.clips.push(second);project.duration=2;project.timeline=[{id:'first',start:0,end:1},{id:'second',start:1,end:2}];project.captions=[{start:0,end:1,text:'원본의 인물과 제품을 유지합니다.'}];
const motion={id:'motion-'+ '1'.repeat(32),title:'장면과 타임라인 점검',ratio:'16:9',fps:30,updated:1793600000,music:'',musicVolume:.2,assets:[],history:[],outputs:[],task:null,html:'<!doctype html><h1>점검용 타임라인</h1>',studioUrl:'/fixture/studio.html',scenes:[{id:'one',title:'첫 장면',text:'제품을 소개합니다.',seconds:4,background:'#101927',color:'#ffffff',motion:'rise',asset:'',kind:'image',fontSize:64,x:8,y:58,trim:0,volume:1}]};
const origin='https://h3-ui.test',prefix=process.env.H3_PROFILE==='local'?'/games/video-maker/':'/video-maker/';let creates=0;const requests=[],apiUnknown=[];let sampleFeed=[];
const browser=await chromium.launch({headless:true,executablePath:'/usr/bin/google-chrome-stable'}),results=[];
try{
 for(const [width,theme] of [[1440,'light'],[820,'light'],[390,'light'],[320,'dark'],[1440,'dark']]){
  const context=await browser.newContext({viewport:{width,height:1000},isMobile:width<600,hasTouch:width<600,colorScheme:theme,locale:'ko-KR',acceptDownloads:true});
  await context.addInitScript(origin=>localStorage.setItem('h3video.server',origin),origin);
  await context.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url()),path=u.pathname;
   if(path.startsWith('/api/')){
    const reply=(data,status=200)=>route.fulfill({status,json:data});
    if(req.method()!=='GET')requests.push({method:req.method(),path});
    if(path==='/api/spec')return reply({model:'MiniMax-H3',sizes:[512,576,640,704,768],tasks:['t2va','fl2va','ref2va'],max_seconds:15,aspect_ratios:['16:9','9:16','1:1']});
    if(path==='/api/health')return reply({fl2va:true,ref2va:true,endpoints:{fl2va:'http://generation.invalid',ref2va:'http://reference.invalid'},hints:{fl2va:null,ref2va:null}});
    if(path==='/api/activity')return reply({running:[],pending:[]});
    if(path==='/api/runtime')return reply({activeCount:0});
    if(path==='/api/feed')return reply({items:sampleFeed,jobs:[],stories:[],studio:{projects:[]},capacity:{},running:0,pending:0});
    if(path==='/api/studio/capabilities')return reply({ffmpeg:true,aiUpscale:true,transcription:true,qwenImage:{model:'fixture'},draftSize:576,draftSteps:20});
    if(path==='/api/studio/references')return req.method()==='GET'?reply({references:[]}):reply({error:'분석 서버에 연결할 수 없습니다. 입력한 자료는 유지됩니다.'},503);
    if(path==='/api/studio/projects')return reply(req.method()==='GET'?{projects:[{id:project.id,title:project.title,clips:2,busy:false,updated:1}]}:structuredClone(project));
    if(path.startsWith('/api/studio/projects/')){
     if(path.endsWith('/settings'))Object.assign(project,req.postDataJSON());
     if(path.endsWith('/captions'))return reply({srt:'/fixture/subtitles.srt',vtt:'/fixture/subtitles.vtt'});
     return reply(project);
    }
    if(path==='/api/motion/capabilities')return reply({templates:[{id:'story',label:'이야기'}],installed:true,version:'fixture'});
    if(path==='/api/motion/projects')return reply(req.method()==='GET'?{projects:[motion]}:motion);
    if(path.startsWith('/api/motion/projects/'))return reply(motion);
    if(path.includes('/plan'))return reply({scenes:[8],max_scene:15});
    apiUnknown.push(path);return reply({ok:true,projects:[],jobs:[],references:[],models:[],providers:[],configured:false});
   }
   if(path==='/fixture/test-video.mp4')return route.fulfill({body:video,contentType:'video/mp4'});
   if(path==='/fixture/studio.html')return route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="ko"><h1>외부 타임라인 테스트 자리</h1><p>외부 편집기 자체의 검증은 포함하지 않습니다.</p></html>'});
   if(u.origin!==origin)return route.abort();
   if(!path.startsWith(prefix))return route.fulfill({status:404,body:'missing'});
   let rel=decodeURIComponent(path.slice(prefix.length))||'index.html';if(!extname(rel))rel+='.html';
   const file=resolve(build,rel);if(!file.startsWith(resolve(build)+'/'))return route.fulfill({status:400});
   try{return route.fulfill({body:await readFile(file),contentType:({'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json'})[extname(file)]||'application/octet-stream'});}catch{return route.fulfill({status:404,body:'missing'});}
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const scans=[];
  async function scan(name,selector){
   if(selector)await page.locator(selector).first().evaluate(e=>e.scrollIntoView({block:'start',behavior:'instant'}));
   const issues=await page.evaluate(()=>{
    const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'&&!e.closest('[hidden],details:not([open])>*:not(summary)');};
    const nodes=[];const collect=root=>{nodes.push(...root.querySelectorAll('button,select,input,textarea,summary'));for(const host of root.querySelectorAll('*'))if(host.shadowRoot)collect(host.shadowRoot);};collect(document);const controls=nodes.filter(visible);
    const tiny=controls.filter(e=>!e.disabled&&!e.matches('input[type=checkbox],input[type=radio],input[type=range],input[type=color],input[type=file]')&&(e.getBoundingClientRect().height<43.5||e.getBoundingClientRect().width<43.5)).map(e=>({name:(e.getAttribute('aria-label')||e.textContent||e.name||e.id).trim().slice(0,45),h:Math.round(e.getBoundingClientRect().height),w:Math.round(e.getBoundingClientRect().width)}));
    const unlabelled=controls.filter(e=>e.matches('input,textarea,select')&&!e.labels?.length&&!e.getAttribute('aria-label')&&!e.getAttribute('aria-labelledby')).map(e=>e.outerHTML.slice(0,160));
    const clipped=controls.filter(e=>e.matches('select')).filter(e=>{const c=document.createElement('canvas').getContext('2d'),s=getComputedStyle(e);c.font=s.font;return c.measureText(e.selectedOptions[0]?.textContent||'').width+35>e.clientWidth;}).map(e=>({field:e.outerHTML.slice(0,110),width:e.clientWidth}));
    const overflow=document.documentElement.scrollWidth>innerWidth+1;
    const outside=[...document.querySelectorAll('dialog[open] *')].filter(visible).filter(e=>{const r=e.getBoundingClientRect(),d=e.closest('dialog').getBoundingClientRect();return r.left<d.left-2||r.right>d.right+2;}).slice(0,8).map(e=>e.outerHTML.slice(0,100));
    return{overflow,tiny,unlabelled,clipped,dialogOutside:outside};
   });
   scans.push({name,...issues});await writeFile(out+'/'+width+'-'+theme+'-scans.json',JSON.stringify({scans,errors},null,2));await page.screenshot({path:out+'/'+width+'-'+theme+'-'+name+'.png',animations:'disabled'});
  }
  await page.goto(origin+prefix,{waitUntil:'domcontentloaded'});await page.locator('#quick-retouch').waitFor();await scan('start','#quick-retouch');
  await page.locator('.studio-nav a[href="#quick-retouch"]').click();
  await page.waitForFunction(()=>document.querySelector('#quick-retouch').getBoundingClientRect().top>=document.querySelector('.top').getBoundingClientRect().bottom-1);
  const contrast=await page.locator('[data-start-retouch]').evaluate(e=>{const colors=[getComputedStyle(e).color,getComputedStyle(e).backgroundColor].map(c=>c.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}));const l=colors.map(([r,g,b])=>.2126*r+.7152*g+.0722*b);return(Math.max(...l)+.05)/(Math.min(...l)+.05);});assert(contrast>=4.5,'Primary button contrast '+contrast);
  await page.locator('.mode[data-mode=text]').focus();await page.keyboard.press('ArrowRight');assert.equal(await page.locator('.mode[aria-selected=true]').getAttribute('data-mode'),'fl');assert.equal(await page.evaluate(()=>document.activeElement.dataset.mode),'fl');
  await page.locator('#feature-catalog').evaluate(e=>e.open=true);await page.locator('[data-category=all]').click();assert.equal(await page.locator('[data-feature-card]:visible').count(),22);
  await page.locator('[data-open-feature=prompts]').click();await page.waitForFunction(()=>document.getElementById('promptLibrary')?.shadowRoot?.querySelector('details')?.open);
  await scan('templates','#promptLibrary');await page.locator('#promptLibrary').locator('form button[type=submit]').click();await page.locator('#promptLibrary').locator('[data-apply]').waitFor();await scan('template-preview','#promptLibrary');
  await page.locator('#promptLibrary').evaluate(e=>e.shadowRoot.querySelector('details').open=false);
  if(width===390){
   for(const f of FEATURES){
    await page.locator('#feature-catalog').evaluate(e=>e.open=true);await page.locator('[data-category=all]').click();await page.locator('[data-open-feature="'+f.id+'"]').click();
    if(f.mode)await page.waitForFunction(mode=>document.querySelector('.mode[aria-selected=true]')?.dataset.mode===mode,f.mode);
    else if(f.id==='retouch')assert(await page.locator('#quick-retouch').isVisible());
    else if(f.action==='prompts'){await page.waitForFunction(()=>document.getElementById('promptLibrary').shadowRoot.querySelector('details').open);await page.locator('#promptLibrary').evaluate(e=>e.shadowRoot.querySelector('details').open=false);}
    else if(f.action==='motion'){await page.locator('#motionWorkbench:not([hidden])').waitFor();await page.locator('#motionWorkbench [data-hf=close]').click();}
    else if(f.action==='reference'){await page.locator('dialog[open]').waitFor();await page.keyboard.press('Escape');}
    else if(f.target){await page.locator('#videoWorkbench '+f.target).first().waitFor();assert(await page.locator('#videoWorkbench '+f.target).first().isVisible(),f.id+' target');}
   }
  }
  await page.locator('#feature-catalog').evaluate(e=>e.open=false);
  for(const mode of ['text','fl','ref','story']){await page.locator('.mode[data-mode='+mode+']').click();await scan('mode-'+mode,'#f');}
  await page.locator('.mode[data-mode=text]').click();await page.locator('#cast-box>summary').click();await page.locator('#cast-new').click();await scan('cast','#cast-box');await page.locator('#cast-box>summary').click();
  await page.locator('#ai-box>summary').click();await scan('providers','#ai-box');for(const provider of ['openai','claude']){await page.locator('input[name=ai-method][value='+provider+']').check();await page.locator('#ai-key-input').waitFor();await scan('provider-'+provider,'#ai-box');}await page.locator('input[name=ai-method][value=local]').check();await page.locator('#ai-box>summary').click();
  await page.locator('#openVideoStudio').click();await page.locator('#videoWorkbench [data-shot=first]').waitFor();
  await page.locator('#videoWorkbench [data-action=tab][data-tab=timeline]').focus();await page.keyboard.press('ArrowRight');await page.waitForFunction(()=>document.querySelector('#videoWorkbench [role=tab][aria-selected=true]')?.dataset.tab==='sound');assert.equal(await page.evaluate(()=>document.activeElement.dataset.tab),'sound','Editor keyboard focus');
  for(const tab of ['timeline','sound','deliver']){await page.locator('#videoWorkbench [data-action=tab][data-tab='+tab+']').click();await scan('editor-'+tab,'#videoWorkbench .vw-tabs');}
  for(const [action,name] of [['batch-edit','batch'],['review','review'],['reference','reference']]){
   if(action!=='reference')await page.locator('#videoWorkbench .vw-project-tools').evaluate(e=>e.open=true);await page.locator('#videoWorkbench [data-action='+action+']').click();await page.locator('dialog[open]').waitFor();await scan(name,'dialog[open]');
   if(action==='reference'){await page.locator('dialog[open] [data-ref-upload]').focus();assert(await page.evaluate(()=>document.activeElement.hasAttribute('data-ref-upload')));await page.locator('[data-ref-field=url]').fill('https://www.youtube.com/watch?v=example');await page.locator('[data-ref-action=analyze]').click();await page.locator('[data-ref-error]').filter({hasText:'분석 서버에 연결할 수 없습니다.'}).waitFor();assert.equal(await page.locator('[data-ref-field=url]').inputValue(),'https://www.youtube.com/watch?v=example');assert(await page.locator('[data-ref-error]').evaluate(e=>document.activeElement===e));}
   await page.keyboard.press('Escape');
  }
  await page.locator('#videoWorkbench [data-action=tab][data-tab=timeline]').click();await page.locator('#videoWorkbench [data-action=edit-shot]').first().click();await scan('scene-dialog','dialog[open]');await page.keyboard.press('Escape');
  await page.locator('#openMotionStudio').click();await page.locator('#motionWorkbench [data-hf=tab]').first().waitFor();
  for(const tab of ['scenes','html','studio']){await page.locator('#motionWorkbench [data-hf=tab][data-mode='+tab+']').click();await page.waitForFunction(tab=>document.querySelector('#motionWorkbench [data-hf=tab].active')?.dataset.mode===tab,tab);await scan('motion-'+tab,'#motionWorkbench .hf-tabs');}
  await page.locator('#motionWorkbench [data-hf=close]').click();
  const job={kind:'job',task:'t2va',prompt:'제품을 소개하는 영상',created:1793600000,total_seconds:8,aspect_ratio:'16:9',seed:0,cli:'h3video gen example -s 8',elapsed:10,scenes:[]};
  sampleFeed=[{...job,id:'ui-running',title:'아침 주방에서 제품을 소개하고 인물과 글자를 유지하는 밝기 교정',status:'running',scenes:[{index:0,duration:8,status:'in_progress',progress:.4}]},{...job,id:'ui-complete',title:'완성한 제품 소개',status:'completed',video_url:'/fixture/test-video.mp4'},{...job,id:'ui-failed',title:'연결을 확인할 작업',status:'failed',error:'fixture connection error',error_ko:'서버 연결을 확인하세요.'},{...job,id:'ui-paused',title:'원본을 보관하고 이어 만들 영상',status:'paused'}];
  await page.evaluate(()=>poll());await page.locator('#feed [data-id=ui-running]').waitFor();
  for(const group of ['working','complete','unfinished'])await scan('results-'+group,'#feed [data-feed-group='+group+']');
  await page.locator('[data-live-select]').selectOption('jobs:ui-paused');await page.locator('[data-live-action=recovery]').click();await page.locator('.video-resume-dialog[open]').waitFor();await scan('resume-dialog','.video-resume-dialog[open]');await page.keyboard.press('Escape');
  await page.locator('#serverControls>details').evaluate(e=>e.open=true);await scan('server-connection','#serverControls');
  sampleFeed=[];
  await page.goto(origin+prefix+'studio/h3-cli',{waitUntil:'domcontentloaded'});await page.locator('#guide-search').waitFor();await scan('guide','.h3-hero');
  await page.locator('#guide-search').fill('--ref-gpus');await scan('guide-search','#gpu-layout');
  results.push({width,theme,scans,errors,contrast,featureLinks:width===390?22:0,negativeReferenceError:true,keyboardTabs:true,externalTimeline:'fixture; upstream editor not measured'});await context.close();
 }
 await writeFile(out+'/result.json',JSON.stringify({results,requests,apiUnknown:[...new Set(apiUnknown)],media:fixture.video,modelInference:'not invoked; API transport mocked'},null,2));
 for(const r of results){assert.deepEqual(r.errors,[]);for(const s of r.scans){assert.equal(s.overflow,false,s.name);assert.deepEqual(s.tiny,[],s.name+' tap targets');assert.deepEqual(s.unlabelled,[],s.name+' labels');assert.deepEqual(s.clipped,[],s.name+' selects');assert.deepEqual(s.dialogOutside,[],s.name+' dialog bounds');}}
 console.log(JSON.stringify(results.map(r=>({width:r.width,theme:r.theme,errors:r.errors,screens:r.scans.length,issues:r.scans.filter(s=>s.overflow||s.tiny.length||s.unlabelled.length||s.clipped.length||s.dialogOutside.length).map(s=>s.name)}))));
}finally{await browser.close();}
