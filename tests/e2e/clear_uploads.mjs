import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {chromium} from '../../node_modules/playwright/index.mjs';
const root=path.resolve(import.meta.dirname,'../..'),temp=await fs.mkdtemp(path.join(os.tmpdir(),'video-clear-'));
const server=spawn('python3',[path.join(root,'tests/studio_browser_server.py'),temp],{stdio:['ignore','pipe','pipe']});let config,buffer='',stderr='';
server.stdout.on('data',data=>{buffer+=data;for(const line of buffer.split('\n'))try{const row=JSON.parse(line);if(row.url)config=row;}catch{}});server.stderr.on('data',data=>stderr=(stderr+data).slice(-3000));
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome-stable'});let release;
try{
 for(let n=0;n<100&&!config;n++)await new Promise(resolve=>setTimeout(resolve,100));assert(config,stderr);
 const host=process.env.H3_UPLOAD_UI||config.url+'/',context=await browser.newContext({viewport:{width:375,height:812}});await context.addInitScript(base=>localStorage.setItem('h3video.server',base),config.url);
 if(host.startsWith('https:'))await context.grantPermissions(['local-network-access']);
 if(process.env.H3_UPLOAD_UI){const local=process.env.H3_UPLOAD_PROFILE==='local',source=await fs.readFile(local?'/home/kms/dev/33modeling-local-arcade/server.mjs':'/home/kms/dev/33modeling-site/_worker.js','utf8'),pw=source.match(local?/AUTH_PASSWORD = process.env.ARCADE_PASSWORD \|\| (["'])(.*?)\1/:/const PASSWORD = (["'])(.*?)\1;/)[2];assert((await context.request.post(new URL('/',host).href,{form:{pw}})).ok());}
 const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));await page.goto(host);await page.locator('#openVideoStudio:enabled').waitFor();
 const json={name:'story.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({title:'Clear uploads',clips:[{prompt:'A peaceful forest',seconds:4}]}))};
 await page.click('[data-mode="story"]');await page.setInputFiles('[data-zone="json"] input',json);await page.locator('#plan .plan').waitFor();
 await page.setInputFiles('[data-zone="pages"] input',[{name:'scene.png',mimeType:'image/png',buffer:await fs.readFile(config.image)},{name:'extra.png',mimeType:'image/png',buffer:await fs.readFile(config.image)}]);
 await page.waitForFunction(()=>document.querySelectorAll('#tiles-pages .tile').length===2);
 await page.click('#clear-json-file');assert.equal(await page.locator('#plan .plan').count(),0);assert.equal(await page.locator('#tiles-pages .tile').count(),2);
 let held,delivered;const ready=new Promise(resolve=>held=resolve),done=new Promise(resolve=>delivered=resolve);
 await page.route(config.url+'/api/story/plan',async route=>{const response=await route.fetch();held();await new Promise(resolve=>release=resolve);await route.fulfill({response});delivered();});
 await page.setInputFiles('[data-zone="json"] input',json);await ready;await page.click('#clear-json-file');release();await done;await page.unroute(config.url+'/api/story/plan');
 assert.equal(await page.locator('#plan .plan').count(),0);assert.equal(await page.locator('[data-zone="json"].has').count(),0);
 await page.click('#clear-all-files');assert.equal(await page.locator('#tiles-pages .tile').count(),0);
 await page.click('[data-mode="ref"]');await page.setInputFiles('[data-zone="ref"] input',[config.image,config.video]);await page.waitForFunction(()=>document.querySelectorAll('#tiles-ref .tile').length===2);
 await page.click('[data-clear-zone="ref"]');assert.equal(await page.locator('#tiles-ref .tile').count(),0);
 await page.click('[data-mode="fl"]');await page.setInputFiles('[data-zone="first"] input',config.image);await page.setInputFiles('[data-zone="last"] input',config.image);
 await page.click('#clear-all-files');assert.equal(await page.locator('.drop.has').count(),0);
 await page.click('[data-mode="story"]');await page.locator('#multi-box > summary').click();
 await page.setInputFiles('#multi-drop input',[json,{...json,name:'second.json'}]);await page.waitForFunction(()=>!document.querySelector('#multi-go').disabled);
 await page.click('#multi-clear-files');assert.equal(await page.locator('#multi-list li').count(),0);assert(await page.locator('#multi-go').isDisabled());
 await page.setInputFiles('#multi-drop input',[json,{...json,name:'second.json'}]);await page.waitForFunction(()=>!document.querySelector('#multi-go').disabled);
 let createHeld,createdDelivery;const created=new Promise(resolve=>createHeld=resolve),createDone=new Promise(resolve=>createdDelivery=resolve);let posts=0;
 await page.route(config.url+'/api/story',async route=>{posts++;const response=await route.fetch();createHeld();await new Promise(resolve=>release=resolve);await route.fulfill({response});createdDelivery();});
 await page.click('#multi-go');await created;
 await page.locator('#multi-box > summary').click();await page.click('[data-mode="fl"]');
 for(const width of [320,375,820,1440]){
  await page.setViewportSize({width,height:812});await page.locator('#multi-stop').waitFor({state:'visible'});
  assert(await page.locator('#multi-stop').evaluate(button=>{const r=button.getBoundingClientRect(),bar=document.querySelector('#liveJobControls');return r.width>=44&&r.height>=44&&r.top>=0&&r.bottom<=innerHeight&&(!bar.offsetHeight||r.bottom<=bar.getBoundingClientRect().top)&&button.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}),'multi stop must remain reachable outside collapsed details and the story tab');
 }
 await page.click('#multi-stop');release();await createDone;await page.unroute(config.url+'/api/story');
 await page.waitForFunction(()=>document.querySelector('#multi-msg').textContent.includes('전체 중지')&&document.querySelectorAll('#multi-list li').length===1);
 assert.equal(posts,1,'stop during a pending upload must prevent the next video from being submitted');
 await page.click('[data-mode="story"]');await page.locator('#multi-box > summary').click();await page.click('#multi-clear-files');
 const sent=await page.evaluate(()=>JSON.parse(localStorage.getItem('h3video.multi'))[0]);
 const stored=await (await context.request.get(config.url+'/api/story/'+sent.id)).json();assert.equal(stored.paused,true,'pending upload stop must reach the returned story id');
 // The story API has no top-level status. Exercise reload recovery with its real schema.
 let restoredPaused=false;
 await page.route(config.url+'/api/story/'+sent.id,async route=>route.fulfill({json:{...stored,output:null,paused:restoredPaused,multi:sent.tag,done:0,total:1,failed:0,clips:[{...stored.clips[0],output:null,error:null,status:restoredPaused?'paused':'running'}]}}));
 await page.click('[data-mode="fl"]');await page.reload();await page.locator('#multi-stop').waitFor({state:'visible'});
 assert.equal(await page.locator('#multi-box').evaluate(el=>el.open),false);
 for(const width of [320,375,820,1440]){await page.setViewportSize({width,height:812});assert(await page.locator('#multi-stop').isVisible());}
 const stopped=page.waitForResponse(response=>response.url()===config.url+'/api/story/'+sent.id+'/stop'&&response.request().method()==='POST');
 await page.click('#multi-stop');assert((await stopped).ok());restoredPaused=true;
 await page.locator('#multi-stop').waitFor({state:'hidden',timeout:10000});
 await page.unroute(config.url+'/api/story/'+sent.id);await page.reload();assert.equal(await page.locator('.drop.has,#tiles-pages .tile,#tiles-ref .tile,#multi-list li').count(),0);
 for(const width of [320,375,820,1440]){await page.setViewportSize({width,height:812});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));}
 assert.deepEqual(errors,[]);await context.close();console.log('PASS video uploads: JSON only removal preserves images · delayed plan cannot restore cleared JSON · media/group/all clear · multi JSON clear · stop pending multi upload prevents next video · fixed stop across tabs/sizes · raw story state reload recovery · reload empty · 320/375/820/1440');
}finally{release?.();await browser.close();server.kill('SIGTERM');await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));await fs.rm(temp,{recursive:true,force:true});}
