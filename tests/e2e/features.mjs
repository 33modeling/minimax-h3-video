import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile,mkdtemp,rm} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {resolve,extname} from 'node:path';
import {tmpdir} from 'node:os';
import net from 'node:net';
import {FEATURES} from '../../src/h3video/studio/features.js';
net.Server.prototype.listen=()=>{throw Error('Web listeners prohibited');};
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_MODULE||'/home/kms/dev/minimax-h3-video/node_modules/playwright');
const root=resolve(import.meta.dirname,'../..'),build=resolve(process.env.H3_BUILD||root+'/dist-ui'),out=process.env.H3_EVIDENCE||root+'/test-results/features';
const temporary=await mkdtemp(tmpdir()+'/h3-features-');
execFileSync('python3',['-B',root+'/tests/feature-fixture.py',temporary],{env:{...process.env,PYTHONPATH:root+'/src'}});
const fixture=JSON.parse(await readFile(temporary+'/fixture.json','utf8')),video=await readFile(fixture.video);
const browser=await chromium.launch({headless:true,executablePath:'/usr/bin/google-chrome-stable'});
await mkdir(out,{recursive:true});
const profiles=process.env.H3_PROFILE?[process.env.H3_PROFILE]:['pages','local'];
const results=[];
try {
 for(const profile of profiles){
  const origin='https://h3-feature.test',prefix=profile==='local'?'/games/video-maker/':'/video-maker/';
  const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true,locale:'ko-KR'});
  await context.addInitScript(origin=>localStorage.setItem('h3video.server',origin),origin);
  let projects=new Map([[fixture.uploaded.id,structuredClone(fixture.uploaded)]]),createCalls=0,uploads=0,upscales=0,failNext=true,createdId=null;
  const original=JSON.stringify(projects.get(fixture.uploaded.id));
  const requests=[];
  await context.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url()),path=u.pathname;
   if(u.origin!==origin)return route.abort();
   if(path.startsWith('/api/')){
    const reply=(data,status=200)=>route.fulfill({status,json:data});
    if(path==='/api/spec')return reply({model:'MiniMax-H3',sizes:[512,576,640,704,768],tasks:['t2va','fl2va','ref2va'],max_seconds:15,aspect_ratios:['16:9','9:16','1:1']});
    if(path==='/api/health')return reply({fl2va:true,ref2va:true,endpoints:{fl2va:'http://generation.invalid',ref2va:'http://reference.invalid'},hints:{fl2va:null,ref2va:null}});
    if(path==='/api/feed')return reply({items:[],jobs:[],stories:[],studio:{projects:[]},capacity:{},running:0,pending:0});
    if(path==='/api/studio/capabilities')return reply({ffmpeg:true,aiUpscale:true,transcription:true,qwenImage:{model:'fixture'},draftSize:576,draftSteps:20});
    if(path==='/api/studio/references')return reply({references:[]});
    if(path==='/api/studio/projects'){
     if(req.method()==='GET')return reply({projects:[...projects.values()].map(p=>({id:p.id,title:p.title,clips:p.clips.length,busy:p.busy,updated:1}))});
     createCalls++;const body=req.postDataJSON(),p=structuredClone(fixture.empty);p.id='edit-'+String(createCalls).padStart(32,'0');p.title=body.title||'새 프로젝트';createdId=p.id;projects.set(p.id,p);requests.push({path,method:'POST',body});return reply(p);
    }
    const m=path.match(/^\/api\/studio\/projects\/(edit-[a-f0-9]{32})(?:\/(\w+))?$/);
    if(m){const p=projects.get(m[1]);if(!p)return reply({error:'missing fixture'},404);if(!m[2])return reply(p);
     if(m[2]==='upload'){
      uploads++;const body=req.postDataBuffer().toString('latin1');assert(body.includes('name="kind"\r\n\r\nvideo'));assert(body.includes('test-video.mp4'));
      const c=p.clips[0],v=structuredClone(fixture.uploaded.clips[0].variants[0]);c.selected=v.id;c.variants=[v];c.seconds=1;return reply(p);
     }
     if(m[2]==='upscale'){
      upscales++;requests.push({path,method:'POST',body:req.postDataJSON()});
      if(failNext){failNext=false;return reply({error:'교정 서버 연결을 확인하세요.'},503);}
      p.busy=true;p.task={status:'queued',operation:'upscale',progress:0,message:'대기 중'};return reply(p);
     }
     if(m[2]==='settings'){const data=req.postDataJSON();Object.assign(p,data);return reply(p);}
    }
    if(path.includes('plan'))return reply({scenes:[8],max_scene:15});
    return reply({jobs:[],stories:[],projects:[],references:[],providers:[],models:[],configured:false,ok:true});
   }
   if(path==='/fixture/test-video.mp4')return route.fulfill({body:video,contentType:'video/mp4'});
   if(!path.startsWith(prefix))return route.fulfill({status:404,body:'missing'});
   let rel=decodeURIComponent(path.slice(prefix.length))||'index.html';if(!extname(rel))rel+='.html';
   const file=resolve(build,rel);if(!file.startsWith(build+'/'))return route.fulfill({status:400});
   try{return route.fulfill({body:await readFile(file),contentType:({'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json'})[extname(file)]||'application/octet-stream'});}catch{return route.fulfill({status:404,body:'missing'});}
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.stack||e.message));
  await page.goto(origin+prefix+'studio/h3-cli');await page.screenshot({path:out+'/'+profile+'-guide-start.png'});await page.locator('[data-guide-category="all"]').click();
  assert.equal(await page.locator('[data-guide-feature]:visible').count(),22);
  assert.equal(await page.locator('.h3-section[data-category]').count(),22);
  assert.equal(await page.locator('#installation .h3-section').count(),16);
  for(const f of FEATURES){const section=page.locator('#feature-'+f.id);assert.equal(await section.locator('ol li').count(),f.steps.length);assert.match(await section.textContent(),/준비할 것.*사용 조건.*완료하면/s);assert.equal(await section.locator('a.hf-use').getAttribute('href'),'../?feature='+f.id);}
  await page.fill('#guide-search','없는기능__');assert(await page.locator('#guide-empty').isVisible());
  await page.fill('#guide-search','--ref-gpus');assert(await page.locator('#gpu-layout').isVisible());assert(await page.locator('#installation').evaluate(e=>e.open));
  await page.fill('#guide-search','');await page.locator('.h3-nav a[href="#resume"]').click();await page.waitForFunction(()=>document.querySelector('#resume').open);
  await page.goto(origin+prefix+'studio/h3-cli#feature-retouch');
  for(const width of [1440,820,390,320]){await page.setViewportSize({width,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'guide overflow '+width);await page.screenshot({path:out+'/'+profile+'-guide-'+width+'.png'});}
  await page.locator('.hf-guide-start>a').click();await page.locator('#quick-retouch').waitFor();
  assert.equal(createCalls,0,'Navigation must not create projects or start inference');assert.equal(upscales,0);
  await page.locator('[data-example="0"]').click();assert.match(await page.locator('#quick-retouch textarea').inputValue(),/인물의 얼굴/);
  for(const width of [1440,820,390,320]){await page.setViewportSize({width,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'studio overflow '+width);await page.screenshot({path:out+'/'+profile+'-studio-'+width+'.png'});}
  await page.emulateMedia({colorScheme:'dark'});await page.screenshot({path:out+'/'+profile+'-dark.png'});await page.emulateMedia({colorScheme:'light'});
  await page.locator('#quick-retouch input[type=file]').setInputFiles(fixture.video);
  const prompt='원본 얼굴과 글자는 유지하고 밝기만 자연스럽게 교정해 줘.';await page.locator('#quick-retouch textarea').fill(prompt);
  await page.locator('[data-start-retouch]').evaluate(b=>{b.click();b.click();});
  await page.locator('[data-quick-status][data-error=true]').waitFor();
  assert.equal(createCalls,1);assert.equal(uploads,1);assert.equal(upscales,1);
  assert.equal(await page.locator('#quick-retouch textarea').inputValue(),prompt);
  assert.equal(await page.locator('#quick-retouch input[type=file]').evaluate(e=>e.files[0].name),'test-video.mp4');
  await page.locator('[data-start-retouch]').click();await page.waitForFunction(()=>document.querySelector('[data-quick-status]').textContent.startsWith('교정을 시작했습니다.'));
  assert.equal(createCalls,1,'Retry must reuse the prepared project');assert.equal(uploads,1,'Retry must preserve and reuse the uploaded original');assert.equal(upscales,2);
  const sent=requests.filter(x=>x.path.endsWith('/upscale')).at(-1).body;
  assert.equal(sent.retouchPrompt,prompt);assert.equal(sent.engine,'qwen-realesrgan');assert.equal(sent.scale,2);assert.equal(sent.model,'photo');
  assert.equal(JSON.stringify(projects.get(fixture.uploaded.id)),original,'Existing project unchanged');
  assert.equal(projects.get(createdId).clips[0].variants.length,1,'Original variant remains');
  await page.locator('[data-start-retouch]').click();await page.locator('[data-quick-status][data-error=true]').waitFor();assert.equal(createCalls,1);assert.equal(upscales,2,'Busy work must not be submitted twice');
  await page.locator('#feature-catalog>summary').click();await page.fill('#feature-search','자막');assert(await page.locator('[data-feature-card="captions"]').isVisible());await page.locator('[data-open-feature="captions"]').click();await page.waitForFunction(()=>document.querySelector('#videoWorkbench [data-action="tab"][data-tab="sound"]')?.classList.contains('active'));
  assert.deepEqual(errors,[]);
  results.push({profile,features:22,installationSections:16,widths:[1440,820,390,320],dark:true,uploadToPromptRequest:true,createCalls,uploads,upscales,originalPreserved:true,retryReusesProject:true,noURLSideEffects:true,transport:'browser routes; real backend project/view schema and real1sfixture; no GPU/model invocation',errors});
  await context.close();
 }
 await writeFile(out+'/result.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results));
}finally{await browser.close();await rm(temporary,{recursive:true,force:true});}
