// 2026-10-26 영상 편집실 점검 회귀: 끝 장면 이동 버튼, 자막 줄 추가가 영상 끝을 넘지 않음, 빈 자막 줄은 SRT 에 없음,
// 생성 중이 아니면 '현재 생성 장면 보기' 끔, 잘못된 수정본 JSON 은 한국어 안내, 출력 배치 글자 잘림,
// 터치 화면(390px)의 누름 칸 44px·일괄 편집 닫기 한 줄. 모의 생성 서버만 쓴다(GPU 없음).
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {chromium} from '/home/kms/dev/ai-essential/node_modules/playwright/index.mjs';
const root=path.resolve(import.meta.dirname,'../..'),temp=await fs.mkdtemp(path.join(os.tmpdir(),'h3-editor-bughunt-'));
const server=spawn('python3',[path.join(root,'tests/studio_browser_server.py'),temp],{stdio:['ignore','pipe','pipe']});
let config,buffer='',stderr='';server.stdout.on('data',d=>{buffer+=d;for(const line of buffer.split('\n'))try{const row=JSON.parse(line);if(row.url)config=row;}catch{}});server.stderr.on('data',d=>stderr=(stderr+d).slice(-4000));
const smallTargets=page=>page.evaluate(()=>[...document.querySelectorAll('button,select,summary,input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=file]):not([type=color])')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&e.offsetParent!==null&&(r.height<43.5||r.width<43.5);}).map(e=>`${e.tagName} ${(e.getAttribute('aria-label')||e.textContent||'').trim().slice(0,24)} ${Math.round(e.getBoundingClientRect().width)}x${Math.round(e.getBoundingClientRect().height)}`));
let browser;
try{
 for(let n=0;n<300&&!config;n++)await new Promise(r=>setTimeout(r,100));assert.ok(config,stderr);
 const api=config.url+'/api/studio/projects/'+config.project;
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME||'/usr/bin/google-chrome'});
 for(const phone of [false,true]){
  const context=await browser.newContext(phone?{viewport:{width:390,height:844},isMobile:true,hasTouch:true,deviceScaleFactor:2,acceptDownloads:true}:{viewport:{width:1440,height:1000},acceptDownloads:true});
  await context.addInitScript(url=>localStorage.setItem('h3video.server',url),config.url);
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await page.goto(config.url+'/');const work=page.locator('#videoWorkbench');
  if(phone){await page.waitForTimeout(1200);assert.deepEqual(await smallTargets(page),[],'main page touch targets below 44px');}
  await page.locator('#openVideoStudio').click();await work.locator('[data-shot="first"]').waitFor();await page.waitForTimeout(500);
  const first=work.locator('[data-shot]').first(),last=work.locator('[data-shot]').last();
  assert.equal(await first.locator('[data-action=move][data-direction="-1"]').isDisabled(),true,'first scene cannot move earlier');
  assert.equal(await last.locator('[data-action=move][data-direction="1"]').isDisabled(),true,'last scene cannot move later');
  assert.equal(await work.locator('[data-action=current-shot]').isDisabled(),true,'no scene is generating');
  if(phone){assert.deepEqual(await smallTargets(page),[],'editor touch targets below 44px');
   await work.locator('[data-action=batch-edit]').click();const close=page.locator('dialog[open] .vr-head>button');await close.waitFor();const box=await close.boundingBox();assert.ok(box.height<=60&&box.width>=44,'batch dialog close button wraps '+JSON.stringify(box));await page.keyboard.press('Escape');}
  else{await work.locator('[data-action=tab][data-tab=deliver]').click();const fit=work.locator('[data-delivery=fit]');assert.ok(await fit.evaluate(s=>{const c=document.createElement('canvas').getContext('2d');const st=getComputedStyle(s);c.font=`${st.fontSize} ${st.fontFamily}`;return c.measureText(s.selectedOptions[0].text).width+40<=s.clientWidth;}),'delivery fit option is cut off');}
  await work.locator('[data-action=tab][data-tab=sound]').click();
  const before=(await fetch(api).then(r=>r.json())).captions.length;
  await work.locator('[data-action=add-caption]').click();await work.locator('[data-action=add-caption]').click();
  await page.locator('#toast',{hasText:'영상 끝까지 자막이 있습니다'}).waitFor();
  await work.locator('[data-caption=text]').first().fill('첫 줄 자막');
  await work.locator('[data-action=save]').click();await page.waitForTimeout(800);
  const saved=await fetch(api).then(r=>r.json());assert.equal(saved.captions.length,before+1);for(const c of saved.captions)assert.ok(c.end<=saved.duration+1e-6&&c.end>c.start);
  const urls=await fetch(api+'/captions',{method:'POST'}).then(r=>r.json());const srt=await fetch(config.url+urls.srt).then(r=>r.text());
  assert.doesNotMatch(srt,/-->[^\n]*\n\n/,'SRT has an empty cue');
  await work.locator('[data-action=tab][data-tab=timeline]').click();
  const bad=path.join(temp,'bad.json');await fs.writeFile(bad,'{not json');await work.locator('[data-import-draft]').setInputFiles(bad);
  await page.locator('#toast',{hasText:'수정본 파일을 읽을 수 없습니다'}).waitFor();
  // 다음 너비를 위해 자막을 비운다
  await fetch(api+'/settings',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({title:saved.title,clips:saved.clips,audio:saved.audio,delivery:saved.delivery,captions:[]})});
  assert.deepEqual(errors,[]);await context.close();
 }
 console.log('PASS: editor bug-hunt regressions at 1440 and 390 touch (move edges, caption end, SRT cues, idle current-shot, draft error, tap targets, delivery select).');
}finally{await browser?.close();server.kill('SIGTERM');await fs.rm(temp,{recursive:true,force:true});}
