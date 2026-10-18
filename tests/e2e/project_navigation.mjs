import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {chromium} from '../../node_modules/playwright/index.mjs';
const root=path.resolve(import.meta.dirname,'../..'),temp=await fs.mkdtemp(path.join(os.tmpdir(),'video-navigation-'));
const server=spawn('python3',[path.join(root,'tests/studio_browser_server.py'),temp],{stdio:['ignore','pipe','pipe']});let config,buffer='',stderr='';server.stdout.on('data',data=>{buffer+=data;for(const line of buffer.split('\n'))try{const row=JSON.parse(line);if(row.url)config=row;}catch{}});server.stderr.on('data',data=>stderr=(stderr+data).slice(-3000));
const browser=await chromium.launch({headless:true});
try{
 for(let n=0;n<100&&!config;n++)await new Promise(r=>setTimeout(r,100));assert.ok(config,stderr);
 const context=await browser.newContext();await context.addInitScript(url=>localStorage.setItem('h3video.server',url),config.url);const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const host=process.env.H3_NAVIGATION_UI||config.url+'/';if(process.env.H3_NAVIGATION_UI){const local=process.env.H3_NAVIGATION_PROFILE==='local',source=await fs.readFile(local?'/home/kms/dev/33modeling-local-arcade/server.mjs':'/home/kms/dev/33modeling-site/_worker.js','utf8'),pw=source.match(local?/AUTH_PASSWORD = process.env.ARCADE_PASSWORD \|\| '([^']+)'/:/const PASSWORD = "([^"]+)"/)[1];assert.ok((await context.request.post(new URL('/',host).href,{form:{pw}})).ok());await context.grantPermissions(['local-network-access']);}
 await page.goto(host);await page.locator('#openVideoStudio').click();const work=page.locator('#videoWorkbench');await work.locator('[data-title]').waitFor();
 let posts=0;page.on('request',req=>{if(req.method()==='POST'&&new URL(req.url()).pathname==='/api/studio/projects')posts++;});
 const accepted=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/studio/projects');await work.locator('[data-action="new"]').evaluate(button=>{button.click();button.click();});const fresh=await(await accepted).json();await page.waitForFunction(()=>!document.querySelector('#videoWorkbench [data-title]')?.disabled);await page.waitForTimeout(400);assert.equal(posts,1,'double click must create only one project');
 const title=await work.locator('[data-title]').inputValue(),key='h3video.activeEditor:'+config.url;
 const match=config.url+'/api/studio/projects/'+config.project;await page.route(match,r=>r.fulfill({status:503,json:{error:'open rejected for fixture'}}));await work.locator('[data-action="open"][data-id="'+config.project+'"]').click();await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('open rejected'));
 assert.equal(await work.locator('[data-title]').inputValue(),title);assert.equal(await page.evaluate(key=>localStorage.getItem(key),key),fresh.id,'failed open must not change restore target');await page.unroute(match);
 let release,held;const waiting=new Promise(r=>held=r);await page.route(match,async r=>{const response=await r.fetch();held();await new Promise(resolve=>release=resolve);await r.fulfill({response});});await work.locator('[data-action="open"][data-id="'+config.project+'"]').click();await waiting;assert.ok(await work.locator('[data-title]').isDisabled(),'editing is locked while switching projects');assert.ok(await work.locator('[data-action="new"]').isDisabled());release();await page.waitForFunction(()=>document.querySelector('#videoWorkbench [data-title]')?.value==='영상 작업실 검증');assert.deepEqual(errors,[]);
 await page.unroute(match);
 const saved=await(await fetch(match)).json();
 await page.evaluate(async({saved,key})=>{const {draftSettings}=await import(new URL('./studio/draft.js',location.href).href);const settings=draftSettings(saved);settings.title='Recovered legacy draft';localStorage.removeItem(key);localStorage.setItem('h3video.activeEditor:',saved.id);localStorage.setItem('h3video.editorDraft::'+saved.id,JSON.stringify({id:saved.id,at:Date.now(),settings}));},{saved,key});
 await page.reload();await work.locator('[data-action="restore-draft"]').waitFor();await work.locator('[data-action="restore-draft"]').click();assert.equal(await work.locator('[data-title]').inputValue(),'Recovered legacy draft');
 await work.locator('[data-action="save"]').click();await page.waitForFunction(key=>localStorage.getItem(key)===null,'h3video.editorDraft::'+config.project);assert.equal((await(await fetch(match)).json()).title,'Recovered legacy draft');assert.equal(await page.evaluate(key=>localStorage.getItem(key),key),config.project);
 assert.deepEqual(errors,[]);console.log('PASS video navigation: one create per double click; failed open retains project and restore target; pending switch locks editing; server-scoped storage and legacy draft migration.');
}finally{await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));await fs.rm(temp,{recursive:true,force:true});}
