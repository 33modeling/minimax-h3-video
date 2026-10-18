import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {chromium} from '/home/kms/dev/crossword/node_modules/playwright/index.mjs';

const root=path.resolve(import.meta.dirname,'../..'),temp=await fs.mkdtemp(path.join(os.tmpdir(),'h3-scene-prompt-'));
const server=spawn('python3',[path.join(root,'tests/studio_browser_server.py'),temp],{stdio:['ignore','pipe','pipe']});
let config,buffer='',stderr='',browser;
server.stdout.on('data',data=>{buffer+=data;for(const line of buffer.split('\n'))try{const row=JSON.parse(line);if(row.url)config=row;}catch{}});
server.stderr.on('data',data=>stderr=(stderr+data).slice(-6000));
try{
 for(let n=0;n<100&&!config;n++)await new Promise(r=>setTimeout(r,100));assert.ok(config,stderr);
 const host=process.env.H3_STUDIO_UI||config.url+'/',report=process.env.H3_STUDIO_EVIDENCE||path.join(root,'test-results/scene-prompt');await fs.mkdir(report,{recursive:true});
 browser=await chromium.launch({headless:true});const context=await browser.newContext({viewport:{width:1440,height:1100}});
 await context.addInitScript(url=>localStorage.setItem('h3video.server',url),config.url);
 if(process.env.H3_STUDIO_UI){const local=process.env.H3_STUDIO_PROFILE==='local',source=await fs.readFile(local?'/home/kms/dev/33modeling-local-arcade/server.mjs':'/home/kms/dev/33modeling-site/_worker.js','utf8'),pw=source.match(local?/AUTH_PASSWORD = process.env.ARCADE_PASSWORD \|\| '([^']+)'/:/const PASSWORD = "([^"]+)"/)[1];assert.ok((await context.request.post(new URL('/',host).href,{form:{pw}})).ok());await context.grantPermissions(['local-network-access']);}
 const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));await page.goto(host);await page.locator('#openVideoStudio').click();const work=page.locator('#videoWorkbench'),dialog=page.locator('.vs-scene-dialog:not(#recovery-dialog)');
 const get=()=>fetch(config.url+'/api/studio/projects/'+config.project).then(response=>response.json());const before=await get();
 await work.locator('[data-action="edit-shot"][data-id="second"]').click();await dialog.waitFor();assert.match(await dialog.textContent(),/2번 장면.*둘째 장면/);assert.equal(await dialog.locator('[data-scene-prompt]').inputValue(),'a second scene');
 const prompt='A red fox walks beside the river.',instructions='인물과 배경은 유지하고 카메라만 천천히 가까워지게.';
 await dialog.locator('[data-scene-prompt]').fill(prompt);await dialog.locator('[data-scene-instructions]').fill(instructions);
 for(const width of [1440,820,390,320]){await page.setViewportSize({width,height:1100});const box=await dialog.boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width+1,'dialog overflow '+width);assert.ok(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1),'content overflow '+width);assert.ok(await dialog.locator('[data-scene-prompt]').isVisible());await page.screenshot({path:path.join(report,'scene-prompt-'+width+'.png')});}
 await page.route('**/api/studio/projects/*/settings',route=>route.fulfill({status:503,json:{error:'테스트 저장 연결 실패'}}),{times:1});
 await dialog.locator('[value="save"]').click();await dialog.locator('[data-scene-error]').filter({hasText:'테스트 저장 연결 실패'}).waitFor();assert.equal(await dialog.locator('[data-scene-prompt]').inputValue(),prompt);assert.equal(await dialog.locator('[data-scene-instructions]').inputValue(),instructions);assert.equal(await dialog.locator('[value="save"]').isEnabled(),true);
 await page.waitForTimeout(1500);assert.equal(await dialog.locator('[data-scene-prompt]').inputValue(),prompt);
 await dialog.locator('[value="save"]').click();await dialog.waitFor({state:'detached'});let current=await get();const expected=prompt+'\n\n수정 지시:\n'+instructions;
 assert.equal(current.clips[1].prompt,expected);assert.equal(current.clips[1].selected,before.clips[1].selected);assert.deepEqual(current.clips[0],before.clips[0]);
 await page.reload();await page.locator('#openVideoStudio').click();await work.locator('[data-action="edit-shot"][data-id="second"]').click();assert.equal(await dialog.locator('[data-scene-prompt]').inputValue(),expected);
 await dialog.locator('[data-scene-prompt]').fill('   ');await dialog.locator('[value="save"]').click();await dialog.locator('[data-scene-error]').filter({hasText:'영상 생성 프롬프트를 입력하세요.'}).waitFor();assert.equal((await get()).clips[1].prompt,expected);
 const revised='A red fox looks toward the sunrise.';await dialog.locator('[data-scene-prompt]').fill(revised);await dialog.locator('[data-scene-instructions]').fill('배경은 그대로 두고 시선만 바꿔 줘.');
 let generationRequests=0;page.on('request',request=>{if(request.method()==='POST'&&request.url().endsWith('/candidates'))generationRequests++;});
 await page.route('**/api/studio/projects/*/candidates',route=>route.fulfill({status:503,json:{error:'테스트 생성 연결 실패'}}),{times:1});
 await dialog.locator('[value="generate"]').evaluate(el=>{el.click();el.click();});await dialog.locator('[data-scene-error]').filter({hasText:'테스트 생성 연결 실패'}).waitFor();assert.equal(generationRequests,1);assert.match(await dialog.locator('[data-scene-feedback]').textContent(),/프롬프트는 저장/);assert.equal(await dialog.locator('[data-scene-instructions]').inputValue(),'배경은 그대로 두고 시선만 바꿔 줘.');
 const registered=page.waitForResponse(response=>response.request().method()==='POST'&&response.url().endsWith('/candidates'));
 await dialog.locator('[value="generate"]').evaluate(el=>{el.click();el.click();});const response=await registered;assert.ok(response.ok());assert.deepEqual(response.request().postDataJSON().clips,['second']);assert.equal(generationRequests,2);await dialog.waitFor({state:'detached'});
 for(let n=0;n<200;n++){current=await get();if(!current.busy)break;await page.waitForTimeout(100);}assert.equal(current.busy,false);
 const changed=current.clips[1],job=await(await fetch(config.url+'/api/jobs/'+changed.pendingCandidates.at(-1).job)).json();assert.ok(job.prompt.startsWith(revised+'\n\n수정 지시:\n배경은 그대로 두고 시선만 바꿔 줘.'));assert.equal(changed.variants.length,2);assert.ok(changed.variants.some(item=>item.id===before.clips[1].selected));assert.deepEqual(current.clips[0],before.clips[0]);
 const original=before.clips[1].variants[0];assert.deepEqual(await(await fetch(config.url+original.url)).arrayBuffer(),await fs.readFile(config.video).then(data=>data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength)));
 await work.locator('[data-action="edit-shot"][data-id="second"]').click();await dialog.locator('[data-scene-prompt]').fill('취소하면 적용하지 않는 수정');await dialog.locator('[data-scene-close]').click();assert.equal((await get()).clips[1].prompt,changed.prompt);
 await work.locator('[data-clip-field="locked"]').check();await work.locator('[data-action="save"]').click();await work.locator('[data-action="edit-shot"][data-id="second"]').click();assert.equal(await dialog.locator('[value="generate"]').isDisabled(),true);assert.equal(await dialog.locator('[value="save"]').isEnabled(),true);await dialog.locator('[data-scene-close]').click();
 assert.deepEqual(errors,[]);await fs.writeFile(path.join(report,'result.json'),JSON.stringify({selectedScene:'second',generationRequests,prompt:job.prompt,originalPreserved:true,otherSceneUnchanged:true,widths:[1440,820,390,320],pageErrors:errors},null,2));console.log('PASS: scene prompt dialog, added instructions reach model job, save and generation failure retry, double-submit guard, selected scene only, original preservation, saved reopening, cancel, locked scene and four screen sizes.');
}finally{await browser?.close();server.kill('SIGTERM');await fs.rm(temp,{recursive:true,force:true});}
