import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {chromium} from '../../node_modules/playwright/index.mjs';
const tmp=await fs.mkdtemp(path.join(os.tmpdir(),'video-activity-'));
const child=spawn('python3',['tests/activity_browser_server.py',tmp],{stdio:['ignore','pipe','pipe']});let config,buffer='',stderr='';
child.stdout.on('data',data=>{buffer+=data;for(const line of buffer.split('\n'))try{const row=JSON.parse(line);if(row.url)config=row;}catch{}});child.stderr.on('data',data=>stderr=(stderr+data).slice(-3000));
const browser=await chromium.launch({headless:true});
try{
 for(let n=0;n<600&&!config;n++){if(child.exitCode!==null)break;await new Promise(r=>setTimeout(r,100));}assert.ok(config,stderr);
 const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(config.url);
 await page.locator('[data-active-job]').filter({hasText:'Current video'}).waitFor();await page.locator('[data-queued-job]').filter({hasText:'Next video'}).waitFor();
 await page.locator('[data-feed-group=complete] [data-id="'+config.complete+'"]').waitFor();await page.locator('[data-feed-group=unfinished] [data-id="'+config.paused+'"]').waitFor();
 await page.locator('[data-feed-group=working] [data-id="'+config.active+'"]').waitFor();
 for(const width of [320,390,820,1440]){await page.setViewportSize({width,height:900});await page.evaluate(()=>scrollTo(0,0));assert.ok(await page.locator('[data-maker-activity]').evaluate(el=>el.scrollWidth<=el.clientWidth+1),'status overflow '+width);}
 await page.request.post(config.url+'/test-release');
 await page.locator('[data-feed-group=complete] [data-id="'+config.active+'"]').waitFor({timeout:30000});
 await page.locator('[data-feed-group=complete] [data-id="'+config.queued+'"]').waitFor();await page.locator('[data-activity-refresh]').click();await page.waitForFunction(()=>!document.querySelector('[data-active-job],[data-queued-job]'));
 await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:'../video-activity.png',fullPage:true});
 await page.route('**/api/activity',route=>route.abort());await page.route('**/api/runtime',route=>route.abort());await page.locator('[data-activity-refresh]').click();await page.locator('[data-activity-title]').filter({hasText:'연결 끊김'}).waitFor();assert.deepEqual(errors,[]);
 console.log('PASS video live task + queue, separate completed/paused groups, completion movement, offline state, four widths. GPU inference mocked.');
}finally{await browser.close();child.kill('SIGTERM');await new Promise(r=>child.exitCode!==null?r():child.once('exit',r));await fs.rm(tmp,{recursive:true,force:true});}
