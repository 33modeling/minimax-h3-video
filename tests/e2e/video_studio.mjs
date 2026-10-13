import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {chromium} from '/home/kms/dev/crossword/node_modules/playwright/index.mjs';
const root=path.resolve(import.meta.dirname,'../..'),temp=await fs.mkdtemp(path.join(os.tmpdir(),'h3-studio-browser-'));
const server=spawn('python3',[path.join(root,'tests/studio_browser_server.py'),temp],{stdio:['ignore','pipe','pipe']});
let config,buffer='';server.stdout.on('data',data=>{buffer+=data;for(const line of buffer.split('\n'))try{const row=JSON.parse(line);if(row.url)config=row;}catch{}});let stderr='';server.stderr.on('data',data=>stderr=(stderr+data).slice(-6000));
let browser;
try{
 for(let n=0;n<100&&!config;n++)await new Promise(r=>setTimeout(r,100));assert.ok(config,stderr);
 const host=process.env.H3_STUDIO_UI||config.url+'/';
 browser=await chromium.launch({headless:true});const context=await browser.newContext({acceptDownloads:true,viewport:{width:1440,height:1000}});
 await context.addInitScript(url=>localStorage.setItem('h3video.server',url),config.url);
 if(process.env.H3_STUDIO_UI){const worker=await fs.readFile('/home/kms/dev/33modeling-site/_worker.js','utf8'),pw=worker.match(/const PASSWORD = "([^"]+)"/)[1];assert.ok((await context.request.post(new URL('/',host).href,{form:{pw}})).ok());await context.grantPermissions(['local-network-access']);}
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(host);
 await page.locator('#openVideoStudio').click();const work=page.locator('#videoWorkbench');await work.locator('[data-shot="first"]').waitFor();
 const get=()=>fetch(config.url+'/api/studio/projects/'+config.project).then(r=>r.json());
 const settle=async()=>{await page.waitForFunction(()=>!document.querySelector('#videoWorkbench [data-status-text]')?.textContent.includes('작업을 등록하고 있습니다'));for(let n=0;n<2400;n++){const p=await get();if(!p.busy){assert.notEqual(p.task?.status,'error',p.task?.error);await page.waitForTimeout(1500);return p;}await page.waitForTimeout(100);}throw Error('editor timed out');};
 await work.locator('[data-action="move"][data-id="second"][data-direction="-1"]').click();await page.waitForTimeout(1000);assert.equal((await get()).clips[0].id,'second');
 await work.locator('[data-clip-field="transition"]').selectOption('fade');await work.locator('[data-clip-field="trimIn"]').fill('.1');await work.locator('[data-action="save"]').click();await page.waitForTimeout(1000);
 await work.locator('[data-action="animatic"]').click();let p=await settle();assert.ok(p.outputs.some(o=>o.kind==='preview'));await work.locator('[data-output-player] video').waitFor();
 await work.locator('[data-action="generate"]').click();p=await settle();let selected=p.clips.find(c=>c.id==='first');assert.equal(selected.variants.length,2);assert.equal(selected.pendingCandidates[0].phase,'draft');
 const original=selected.variants[0].id;
 await work.locator('[data-compare]').nth(0).check();await work.locator('[data-compare]').nth(1).check();assert.equal(await work.locator('[data-comparison] video').count(),2);await work.locator('[data-action="compare-play"]').click();await work.locator('[data-action="compare-play"]').click();
 await work.locator('[data-color="brightness"]').evaluate(el=>{el.value='.1';el.dispatchEvent(new Event('input',{bubbles:true}));});await work.locator('[data-action="save"]').click();await page.waitForTimeout(1000);
 await work.locator('[data-action="upscale"]').click();await work.locator('[data-action="pause"]').click();p=await settle();assert.equal(p.task.status,'paused');await work.locator('[data-action="resume"]').click();p=await settle();selected=p.clips.find(c=>c.id==='first');const enhanced=selected.variants.find(v=>v.id===selected.selected);assert.equal(enhanced.operation,'ai-upscale');assert.equal(enhanced.width,192);assert.equal(enhanced.bakedCorrections.brightness,.1);assert.ok(selected.variants.find(v=>v.id===original));
 await work.locator('[data-action="tab"][data-tab="sound"]').click();
 await work.locator('[data-upload="narration"]').setInputFiles('/home/kms/.local/share/h3video/studio/jfk.flac');await page.waitForTimeout(1000);
 await work.locator('[data-audio="musicGain"]').evaluate(el=>{el.value='.25';el.dispatchEvent(new Event('input',{bubbles:true}));});await work.locator('[data-action="save"]').click();await page.waitForTimeout(800);
 await work.locator('[data-asr-language]').selectOption('en');await work.locator('[data-action="transcribe"]').click();p=await settle();assert.ok(p.transcription.engine.includes('faster-whisper'));
 await work.locator('[data-action="add-caption"]').click();await work.locator('[data-caption="text"]').last().fill('추가한 한글 자막');await work.locator('[data-action="save"]').click();await page.waitForTimeout(1000);assert.ok((await get()).captions.some(c=>c.text==='추가한 한글 자막'));
 await work.locator('[data-action="tab"][data-tab="deliver"]').click();await work.locator('[data-delivery-ratio="9:16"]').check();await work.locator('[data-delivery-ratio="1:1"]').check();await work.locator('[data-focus-ratio]').selectOption('9:16');await work.locator('[data-focus="x"]').evaluate(el=>{el.value='.3';el.dispatchEvent(new Event('input',{bubbles:true}));});await work.locator('[data-action="save"]').click();await page.waitForTimeout(800);
 await work.locator('[data-action="inspect"]').click();p=await settle();assert.ok(p.inspection);
 let renderRequests=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/render'))renderRequests++;});const registering=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/render'));await work.locator('[data-action="render"]').evaluate(el=>{el.click();el.click();});assert.ok((await registering).ok());p=await settle();assert.equal(renderRequests,1,'Rapid double clicks must register exactly one finishing job');assert.equal(p.outputs.filter(o=>o.kind==='render').length,3);assert.equal(p.outputs.at(-1).kind,'bundle');
 const downloading=page.waitForEvent('download');await work.locator('.vw-download').first().click();const download=await downloading;assert.ok((await fs.stat(await download.path())).size>1000);
 await page.reload();await page.locator('#openVideoStudio').click();await work.locator('[data-shot]').first().waitFor();assert.equal((await get()).clips[0].id,'second');
 await work.locator('[data-action="tab"][data-tab="deliver"]').click();const report=process.env.H3_STUDIO_EVIDENCE||path.join(root,'test-results/video-studio');await fs.mkdir(report,{recursive:true});
 for(const width of [1920,820,390,320]){await page.setViewportSize({width,height:1100});await work.scrollIntoViewIfNeeded();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'horizontal overflow '+width);await page.screenshot({path:path.join(report,`editor-${width}.png`)});}
 assert.deepEqual(errors,[]);console.log('PASS: all eight video features, real speech and AI upscale, pause/resume, original preservation, saved reopening, all output ratios and desktop/tablet/mobile.');
}finally{await browser?.close();server.kill('SIGTERM');await fs.rm(temp,{recursive:true,force:true});}
