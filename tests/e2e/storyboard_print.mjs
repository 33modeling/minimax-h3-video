// 스토리보드 PDF: 실제 편집 API(모의 생성 서버) + 인쇄 레이아웃. 1440·390px 에서 버튼과 PDF 시트를 확인한다.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {chromium} from '/home/kms/dev/ai-essential/node_modules/playwright/index.mjs';
const root=path.resolve(import.meta.dirname,'../..'),temp=await fs.mkdtemp(path.join(os.tmpdir(),'h3-storyboard-'));
const server=spawn('python3',[path.join(root,'tests/studio_browser_server.py'),temp],{stdio:['ignore','pipe','pipe']});
let config,buffer='',stderr='';server.stdout.on('data',d=>{buffer+=d;for(const line of buffer.split('\n'))try{const row=JSON.parse(line);if(row.url)config=row;}catch{}});server.stderr.on('data',d=>stderr=(stderr+d).slice(-4000));
let browser;
try{
 for(let n=0;n<150&&!config;n++)await new Promise(r=>setTimeout(r,100));assert.ok(config,stderr);
 const api=config.url+'/api/studio/projects/'+config.project,project=await fetch(api).then(r=>r.json());
 project.clips[0].text='첫 자막 <확인>';project.clips[1].prompt='두 번째 장면 프롬프트';
 const saved=await fetch(api+'/settings',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({title:project.title,clips:project.clips,audio:project.audio,delivery:project.delivery})});assert.ok(saved.ok,await saved.text());
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME||'/usr/bin/google-chrome'});
 const report=process.env.H3_STORYBOARD_EVIDENCE||path.join(root,'test-results/storyboard');await fs.mkdir(report,{recursive:true});
 for(const width of [1440,390]){
  const context=await browser.newContext({viewport:{width,height:1000}});await context.addInitScript(url=>{localStorage.setItem('h3video.server',url);window.__prints=0;window.print=()=>{window.__prints++;};},config.url);
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(config.url+'/');
  await page.locator('#openVideoStudio').click();const work=page.locator('#videoWorkbench');await work.locator('[data-shot="first"]').waitFor();
  const button=work.locator('[data-action="storyboard"]');const box=await button.boundingBox();assert.ok(box&&box.height>=44,'storyboard button below 44px at '+width);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'horizontal overflow '+width);
  await button.click();await page.waitForFunction(()=>window.__prints===1&&document.querySelector('.vw-storyboard-print'));
  const sheet=page.locator('.vw-storyboard-print');assert.equal(await sheet.locator('[data-storyboard-scene]').count(),2);
  assert.equal(await sheet.locator('img[src^="data:image/jpeg"]').count(),2,'video frame thumbnails missing');
  const text=await sheet.textContent();for(const t of ['장면 1','장면 2','1초','a moving scene','두 번째 장면 프롬프트','첫 자막 <확인>','장면 2개'])assert.ok(text.includes(t),'missing '+t);
  assert.equal(await sheet.evaluate(el=>getComputedStyle(el).display),'none','sheet must be hidden on screen');
  const pageTitle=await page.evaluate(()=>document.title);assert.equal(pageTitle,project.title+' 스토리보드','PDF file name should follow the project title');
  await page.emulateMedia({media:'print'});assert.equal(await sheet.evaluate(el=>getComputedStyle(el).display),'block');assert.equal(await page.locator('#videoWorkbench').evaluate(el=>el.offsetParent===null),true,'editor must be hidden when printing');
  if(width===1440){const pdf=path.join(report,'storyboard.pdf');await page.pdf({path:pdf,format:'A4',printBackground:true});const head=(await fs.readFile(pdf)).subarray(0,5).toString();assert.equal(head,'%PDF-');await page.screenshot({path:path.join(report,'storyboard-print-1440.png'),fullPage:true});}
  await page.evaluate(()=>dispatchEvent(new Event('afterprint')));assert.notEqual(await page.evaluate(()=>document.title),project.title+' 스토리보드','page title restored after print');await page.emulateMedia({media:'screen'});assert.equal(await page.locator('.vw-storyboard-print').count(),0,'sheet not removed after print');
  await page.screenshot({path:path.join(report,`storyboard-editor-${width}.png`)});
  assert.deepEqual(errors,[]);await context.close();
 }
 console.log('PASS: storyboard PDF sheet with video thumbnails, scene number, duration, prompt and caption at 1440/390px.');
}finally{await browser?.close();server.kill('SIGTERM');await fs.rm(temp,{recursive:true,force:true});}
