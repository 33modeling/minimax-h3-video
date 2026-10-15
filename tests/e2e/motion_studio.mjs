import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {chromium} from 'playwright';

const root=path.resolve(import.meta.dirname,'../..');
const temp=await fs.mkdtemp(path.join(os.tmpdir(),'h3-motion-ui-'));
const report=process.env.H3_MOTION_EVIDENCE||path.join(root,'test-results/hyperframes');
await fs.mkdir(report,{recursive:true});
const server=spawn('python3',[path.join(root,'tests/studio_browser_server.py'),temp],{stdio:['ignore','pipe','pipe']});
let config,buffer='',stderr='',browser;
server.stdout.on('data',data=>{buffer+=data;for(const line of buffer.split('\n'))try{const row=JSON.parse(line);if(row.url)config=row;}catch{}});
server.stderr.on('data',data=>stderr=(stderr+data).slice(-10000));
try{
 for(let n=0;n<200&&!config;n++)await new Promise(r=>setTimeout(r,100));assert.ok(config,stderr);
 browser=await chromium.launch({headless:true,...(process.env.H3_BROWSER_PATH?{executablePath:process.env.H3_BROWSER_PATH}:{})});
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
 await context.addInitScript(url=>localStorage.setItem('h3video.server',url),config.url);
 const host=process.env.H3_MOTION_UI||config.url+'/';
 if(host.startsWith('https://')){assert.ok((await context.request.post(new URL('/',host).href,{form:{pw:'kms'}})).ok());await context.grantPermissions(['local-network-access']);}
 if(host.includes(':4173')){const crypto=await import('node:crypto');await context.addCookies([{name:'local_arcade_gate',value:crypto.createHash('sha256').update('kms33-local-arcade-v1').digest('hex'),domain:'127.0.0.1',path:'/'}]);}
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 page.on('response',r=>{if(r.status()>=400&&/\/hyperframes\//.test(r.url()))errors.push(r.status()+' '+r.url());});
 await page.goto(host);await page.locator('#openVideoStudio').click();
 await page.locator('#videoWorkbench [data-action=motion]').click();
 const work=page.locator('#motionWorkbench');await work.locator('[data-studio]').waitFor();
 const frame=page.frameLocator('[data-studio]');await frame.getByText('Timeline',{exact:true}).waitFor({timeout:45000});
 assert.ok(await frame.getByText('Layers',{exact:true}).isVisible());
 const get=async()=>{const data=await fetch(config.url+'/api/motion/projects').then(r=>r.json());assert.equal(data.projects.length,1);return fetch(config.url+'/api/motion/projects/'+data.projects[0].id).then(r=>r.json());};
 let p=await get();assert.equal(p.scenes.length,2);assert.equal(p.scenes[0].kind,'video');
 let preview;for(let n=0;n<180&&!preview;n++){preview=page.frames().find(f=>f.url().includes('/api/projects/h3-motion/preview'));if(!preview)await page.waitForTimeout(250);}
 assert.ok(preview,'actual upstream preview iframe');await preview.waitForFunction(()=>typeof window.__player?.seek==='function',{},{timeout:45000});
 await preview.evaluate(()=>window.__player.seek(.5));assert.ok(await preview.locator('video').count());
 await work.locator('[data-hf=tab][data-mode=scenes]').click();
 await work.locator('[data-scene-field=title]').first().fill('브라우저에서 수정');await work.locator('[data-hf=apply]').click();
 await page.waitForFunction(()=>!document.querySelector('#motionWorkbench [data-message]').textContent.includes('처리 중'));
 assert.ok((await get()).html.includes('브라우저에서 수정'));
 await work.locator('[data-hf=duplicate]').first().click();await work.locator('[data-hf=apply]').click();
 assert.equal((await get()).scenes.length,3);await work.locator('[data-hf=remove]').last().click();await work.locator('[data-hf=apply]').click();
 await work.locator('[data-media]').setInputFiles(config.image);await page.waitForFunction(()=>document.querySelector('#motionWorkbench [data-scene-field=asset]')?.options.length===4);
 await work.locator('[data-hf=tab][data-mode=html]').click();const html=work.locator('[data-html]');await html.fill((await html.inputValue()).replace('브라우저에서 수정','HTML에서 수정'));
 await work.locator('[data-hf=save]').last().click();assert.ok((await get()).html.includes('HTML에서 수정'));
 const downloading=page.waitForEvent('download');await work.locator('[data-hf=export]').click();const download=await downloading;assert.ok((await fs.stat(await download.path())).size>1000);
 await work.locator('[data-option=fps]').fill('12');let renderRequests=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/render'))renderRequests++;});
 await work.locator('[data-hf=render]').evaluate(el=>{el.click();el.click();});
 for(let n=0;n<600;n++){p=await get();if(['done','error'].includes(p.task?.status))break;await page.waitForTimeout(200);}
 assert.equal(p.task.status,'done',JSON.stringify(p.task));assert.equal(renderRequests,1);await work.locator('.hf-outputs video').waitFor({timeout:10000});
 assert.ok(p.outputs.length);await page.reload();await page.locator('#openMotionStudio').click();assert.ok((await get()).html.includes('HTML에서 수정'));
 for(const width of [1440,820,390,320]){await page.setViewportSize({width,height:1100});await work.scrollIntoViewIfNeeded();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'overflow '+width);await page.screenshot({path:path.join(report,`motion-${width}.png`)});}
 await page.setViewportSize({width:1440,height:1000});await work.locator('[data-hf=tab][data-mode=studio]').click();await frame.getByText('Timeline',{exact:true}).waitFor({timeout:45000});
 await work.screenshot({path:path.join(report,'actual-hyperframes-studio.png')});assert.equal(errors.length,0,errors.slice(0,5).join('\n'));
 await fs.writeFile(path.join(report,'result.json'),JSON.stringify({host,project:p.id,render:p.task,viewports:[1440,820,390,320],errors},null,2));
 console.log('PASS: real Studio/preview, existing clip+audio import, scene/HTML edits, upload, ZIP, real MP4, double click guard, saved reload, desktop/tablet/mobile.');
}finally{
 await browser?.close();server.kill('SIGTERM');await new Promise(resolve=>{if(server.exitCode!==null)return resolve();server.once('exit',resolve);setTimeout(resolve,10000);});await fs.rm(temp,{recursive:true,force:true});
}
