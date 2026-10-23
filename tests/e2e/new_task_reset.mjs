import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {chromium} from '../../node_modules/playwright/index.mjs';
// "＋ 새 작업" must start from an empty form even after "같은 설정으로 다시" filled it from earlier work.
const root=path.resolve(import.meta.dirname,'../..'),temp=await fs.mkdtemp(path.join(os.tmpdir(),'video-new-task-'));
const server=spawn('python3',[path.join(root,'tests/studio_browser_server.py'),temp],{stdio:['ignore','pipe','pipe']});let config,buffer='',stderr='';server.stdout.on('data',data=>{buffer+=data;for(const line of buffer.split('\n'))try{const row=JSON.parse(line);if(row.url)config=row;}catch{}});server.stderr.on('data',data=>stderr=(stderr+data).slice(-3000));
const browser=await chromium.launch({headless:true});
try{
 for(let n=0;n<100&&!config;n++)await new Promise(r=>setTimeout(r,100));assert.ok(config,stderr);
 const context=await browser.newContext();await context.addInitScript(url=>localStorage.setItem('h3video.server',url),config.url);const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(config.url+'/');await page.locator('#prompt').waitFor();
 const defaults=await page.evaluate(()=>Object.fromEntries(['#seconds','#aspect','#size'].map(id=>[id,document.querySelector(id).value])));
 await page.evaluate(()=>{document.querySelector('#prompt').value='earlier work prompt';document.querySelector('#title').value='earlier title';document.querySelector('#seed').value='77';document.querySelector('#negative').value='blur';document.querySelector('#raw').checked=true;document.querySelector('#more').open=true;localStorage.setItem('h3video.draft','earlier work prompt');});
 await page.evaluate(()=>nativeWorkspaceAction('new'));
 const after=await page.evaluate(()=>({prompt:document.querySelector('#prompt').value,title:document.querySelector('#title').value,seed:document.querySelector('#seed').value,negative:document.querySelector('#negative').value,raw:document.querySelector('#raw').checked,more:document.querySelector('#more').open,draft:localStorage.getItem('h3video.draft')||'',values:Object.fromEntries(['#seconds','#aspect','#size'].map(id=>[id,document.querySelector(id).value]))}));
 assert.deepEqual(after,{prompt:'',title:'',seed:'',negative:'',raw:false,more:false,draft:'',values:defaults});
 await page.reload();await page.locator('#prompt').waitFor();assert.equal(await page.locator('#prompt').inputValue(),'','the earlier draft does not come back after reload');
 assert.deepEqual(errors,[]);console.log('PASS video new task: earlier prompt, settings, files and saved draft are cleared');
}finally{await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));await fs.rm(temp,{recursive:true,force:true});}
