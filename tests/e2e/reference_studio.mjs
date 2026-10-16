import {chromium} from '/home/kms/dev/crossword/node_modules/playwright/index.mjs';
import fs from 'node:fs';import assert from 'node:assert/strict';import {execFileSync,spawn} from 'node:child_process';import os from 'node:os';import path from 'node:path';
const root=path.resolve(import.meta.dirname,'../..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'h3-reference-e2e-'));
const server=spawn('python3',[path.join(root,'tests/studio_browser_server.py'),temp],{stdio:['ignore','pipe','pipe']});let config,buffer='',stderr='';
server.stdout.on('data',chunk=>{buffer+=chunk;for(const line of buffer.split('\n'))try{const v=JSON.parse(line);if(v.url)config=v;}catch{}});server.stderr.on('data',chunk=>stderr=(stderr+chunk).slice(-3000));
let browser;try{
for(let i=0;i<100&&!config;i++)await new Promise(r=>setTimeout(r,100));assert.ok(config,stderr);
const api=config.url,host=process.env.H3_REF_UI||api+'/',label=process.env.H3_REF_LABEL||'source',report=process.env.H3_REF_EVIDENCE||path.join(root,'test-results/reference-studio');fs.mkdirSync(report,{recursive:true});
const file=path.join(temp,'reference-fixture.mp4');execFileSync('ffmpeg',['-loglevel','error','-y','-f','lavfi','-i',"color=c=0x203f65:s=640x360:r=4:d=2,drawtext=text='HELLO WORLD':fontsize=44:fontcolor=white:x=80:y=70",'-c:v','libx264','-pix_fmt','yuv420p',file]);
browser=await chromium.launch({headless:true});const result=[];
for(const width of [320,390,820,1440]){
 const ctx=await browser.newContext({viewport:{width,height:1100},acceptDownloads:true});await ctx.addInitScript(u=>localStorage.setItem('h3video.server',u),api);
 if(host!==api+'/'){const secret=fs.readFileSync('/home/kms/dev/33modeling-site/_worker.js','utf8').match(/const PASSWORD\s*=\s*"([^"]+)"/)[1];const r=await ctx.request.post(new URL('/',host).href,{form:{pw:secret},maxRedirects:0});const cookie=r.headers()['set-cookie']||'';for(const c of cookie.split(/,(?=\s*[^;,]+=)/)){const pair=c.trim().split(';')[0],i=pair.indexOf('=');if(i>0)await ctx.addCookies([{name:pair.slice(0,i),value:pair.slice(i+1),url:new URL('/',host).href}]);}await ctx.grantPermissions(['local-network-access']);}
 const page=await ctx.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(host,{waitUntil:'networkidle'});await page.locator('#openVideoStudio').click();await page.locator('[data-action=reference]').click();const modal=page.locator('.vr-dialog');await modal.waitFor();
 await modal.locator('[data-ref-field=end]').fill('2');await modal.locator('[data-ref-field=transcribe]').uncheck();await modal.locator('[data-ref-upload]').setInputFiles(file);await modal.locator('[data-ref-prompt]').waitFor({timeout:45000});
 assert.ok((await modal.locator('[data-overlay=text]').inputValue()).includes('HELLO'));
 await modal.locator('[data-overlay=font_family]').fill('Georgia');await modal.locator('[data-overlay-box=x]').fill('.2');await modal.locator('[data-ref-prompt]').fill('수정한 제품 소개 영상');await modal.locator('[data-ref-action=save]').click();await page.waitForTimeout(400);
 const doc=JSON.parse(await modal.locator('[data-ref-json]').inputValue());assert.equal(doc.clips[0].text_overlays[0].font_family,'Georgia');assert.equal(doc.clips[0].text_overlays[0].box.x,.2);
 const downloadPromise=page.waitForEvent('download');await modal.locator('[data-ref-action=zip]').click();const download=await downloadPromise;assert.ok(fs.statSync(await download.path()).size>2000);
 assert.ok(await modal.evaluate(el=>el.scrollWidth<=el.clientWidth+1),'dialog overflow '+width);
 await page.screenshot({path:path.join(report,`${label}-${width}.png`)});
 await modal.locator('[data-ref-action=import]').click();await modal.waitFor({state:'hidden'});await page.locator('[data-clip-field=prompt]').waitFor();const prompt=await page.locator('[data-clip-field=prompt]').inputValue();assert.ok(prompt.startsWith('수정한 제품 소개 영상'));assert.ok(prompt.includes('font Georgia'));assert.ok(prompt.includes('x=0.2'));await page.locator('[data-upscale-engine]').selectOption('qwen-turbo-realesrgan');assert.ok(await page.locator('[data-retouch-prompt]').isVisible());
 await page.reload();await page.locator('#openVideoStudio').click();await page.locator('[data-action=reference]').click();await page.locator('.vr-history [data-ref-action=open]').first().click();assert.equal(JSON.parse(await modal.locator('[data-ref-json]').inputValue()).clips[0].text_overlays[0].font_family,'Georgia');
 assert.deepEqual(errors,[]);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'page overflow '+width);result.push({width,ocr:true,edit:true,zip:true,import:true,qwenOption:true,reopen:true,noErrors:true});await ctx.close();
}
await browser.close();fs.writeFileSync(path.join(report,`${label}-browser.json`),JSON.stringify(result,null,2));console.log(`PASS ${label}: 4 widths; real OCR, font/position edits, ZIP, import, Qwen option, saved restoration`);

}finally{await browser?.close();server.kill("SIGTERM");fs.rmSync(temp,{recursive:true,force:true});}
