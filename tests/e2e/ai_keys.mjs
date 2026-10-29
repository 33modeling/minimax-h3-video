// 생성 방식(키) 브라우저 점검: 실제 웹 서버(127.0.0.1:4561)와 가짜 영상 서버를 띄우고, api.openai.com·api.anthropic.com 은 가로채 가짜 응답을 준다.
//  1) 키 없음: 지금처럼 로컬 서버(/api/jobs)로만 보내고 공급자 API 는 부르지 않는다
//  2) OpenAI 키: 글은 OpenAI(Responses API)가 쓰고, 영상 작업은 로컬 서버로 간다(Sora 영상 API 는 2026-09-24 종료)
//  3) Claude 키: 미리 다듬기·보내기·장면 수정 지시 반영, 오류(401·429) 안내, 키 지우기
//     키는 저장하지 않는다: 넣기·글쓰기·새로고침 뒤에도 sessionStorage·localStorage 에 키가 없고, 새로고침하면 키 칸이 빈다(예전 판 키 칸도 지운다)
//     OpenAI 틀린 키: 실제 OpenAI 는 POST /v1/responses 에 CORS 머리글 없는 401 을 돌려줘 브라우저에는 연결 실패로만 보인다(abort 로 흉내) → 모델 조회로 401 을 알린다
//     키로 글 쓰는 동안 Ctrl+Enter 를 두 번 눌러도 공급자 요청·작업은 한 번
//  4) 휴대폰 390px: 가로 넘침 없음, 누름 대상 44px
// 실행: node tests/e2e/ai_keys.mjs   (Chrome: CHROME 또는 /usr/bin/google-chrome)
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
const root = path.resolve(import.meta.dirname, '../..');
const {chromium} = createRequire(path.join(root, 'package.json'))('playwright');
const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'h3-ai-keys-'));
const server = spawn('python3', [path.join(root, 'tests/ai_keys_browser_server.py'), temp], {stdio: ['ignore', 'pipe', 'pipe'], env: {...process.env, CUDA_VISIBLE_DEVICES: ''}});
let config, buffer = '', stderr = '';
server.stdout.on('data', d => { buffer += d; for (const line of buffer.split('\n')) try { const row = JSON.parse(line); if (row.url) config = row; } catch { /* 다음 줄 */ } });
server.stderr.on('data', d => { stderr = (stderr + d).slice(-6000); });
const KEY_O = 'sk-test-openai-e2e-0123456789', KEY_C = 'sk-ant-test-claude-e2e-0123456789';
const OPENAI_TEXT = 'OPENAI PROMPT: A wide night shot of a rainy Seoul street, neon reflections, slow dolly forward, rain and distant traffic.';
const CLAUDE_TEXT = 'CLAUDE PROMPT: Close-up of a cat yawning by a sunny window, slow push-in, soft purring and birdsong.';
const CLAUDE_REVISED = 'CLAUDE REVISED: Close-up of a cat yawning by a sunny window, brighter morning light, slow push-in.';
const ok = what => console.log('  ok  ' + what);
const field = (body, name) => (new RegExp(`name="${name}"\\r\\n\\r\\n([\\s\\S]*?)\\r\\n--`).exec(body || '') || [])[1];
let browser, failed = false;
try {
  for (let n = 0; n < 150 && !config; n++) await new Promise(r => setTimeout(r, 100));
  assert.ok(config, '웹 서버가 뜨지 않았습니다\n' + stderr);
  const url = config.url;
  browser = await chromium.launch({headless: true, executablePath: process.env.CHROME || '/usr/bin/google-chrome'});
  const context = await browser.newContext({viewport: {width: 1400, height: 1000}});
  const provider = [], local = [], errors = [];
  let claudeFail = 0, openaiWrongKey = false, openaiSlow = 0;
  const cors = {'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': 'POST, OPTIONS'};
  await context.route(/^https:\/\/api\.(openai|anthropic)\.com\//, async route => {
    const req = route.request();
    if (req.method() === 'OPTIONS') return route.fulfill({status: 204, headers: cors});
    const body = req.postDataJSON();
    provider.push({url: req.url(), headers: await req.allHeaders(), body});
    if (req.url().startsWith('https://api.openai.com/')) {
      if (openaiWrongKey && req.url() === 'https://api.openai.com/v1/models/gpt-6.1-terra')
        return route.fulfill({status: 401, headers: cors, contentType: 'application/json', body: JSON.stringify({error: {message: 'Incorrect API key provided: sk-test-****6789.', type: 'invalid_request_error', code: 'invalid_api_key'}})});
      assert.equal(req.url(), 'https://api.openai.com/v1/responses');
      if (openaiWrongKey) return route.abort('failed');
      if (openaiSlow) await new Promise(r => setTimeout(r, openaiSlow));
      return route.fulfill({status: 200, headers: cors, contentType: 'application/json', body: JSON.stringify({id: 'resp_e2e', object: 'response', status: 'completed',
        output: [{type: 'reasoning', id: 'rs_1', summary: []}, {type: 'message', id: 'msg_1', role: 'assistant', status: 'completed', content: [{type: 'output_text', text: OPENAI_TEXT, annotations: []}]}]})});
    }
    assert.equal(req.url(), 'https://api.anthropic.com/v1/messages');
    if (claudeFail) { const status = claudeFail; claudeFail = 0;
      return route.fulfill({status, headers: cors, contentType: 'application/json', body: JSON.stringify({type: 'error', error: {type: status === 401 ? 'authentication_error' : 'rate_limit_error', message: 'invalid x-api-key sk-ant-test-claude-e2e-0123456789'}})}); }
    const revise = /edit instruction/i.test(body.system);
    return route.fulfill({status: 200, headers: cors, contentType: 'application/json', body: JSON.stringify({id: 'msg_e2e', type: 'message', role: 'assistant', model: body.model,
      stop_reason: 'end_turn', content: [{type: 'thinking', thinking: 'plan', signature: 'sig'}, {type: 'text', text: revise ? CLAUDE_REVISED : CLAUDE_TEXT}]})});
  });
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error' && !/status of (401|429)|net::ERR_FAILED/.test(m.text())) errors.push('console ' + m.text()); });
  page.on('request', r => { if (r.url().startsWith(url)) local.push({url: r.url(), method: r.method(), body: r.postData() || '', headers: r.headers()}); });
  await page.goto(url + '/');
  await page.locator('#ai-box:not([hidden])').waitFor();
  await page.locator('#pill-fl.ok').waitFor({timeout: 15000});
  const submitJob = async text => {
    await page.fill('#prompt', text);
    const sent = page.waitForRequest(r => r.url() === url + '/api/jobs' && r.method() === 'POST', {timeout: 60000});
    await page.click('#go');
    return (await sent).postData();
  };
  // 두 저장소 어디에든 키(값)나 예전 키 칸 이름이 남아 있으면 그 목록
  const storedKeys = p => p.evaluate(keys => [sessionStorage, localStorage].flatMap(s => Object.keys(s).filter(k => /remember|openaiKey|claudeKey|anthropicKey/.test(k) || keys.some(key => (s.getItem(k) || '').includes(key)))), [KEY_O, KEY_C]);
  const card = title => page.locator('#feed article.job', {has: page.locator('h3', {hasText: title})}).first();

  // 1) 키 없음 = 지금 그대로
  assert.equal(await page.isChecked('input[name=ai-method][value=local]'), true);
  assert.equal(await page.textContent('#ai-current'), '로컬 서버');
  assert.equal(await page.evaluate(() => document.querySelector('#ai-box').open), false);
  assert.equal(await page.isHidden('[data-ai-key]'), true);
  assert.match(await page.textContent('[data-ai-desc]'), /로컬 서버가 글 다듬기와 영상 만들기를 모두/);
  assert.equal(await page.isHidden('#ai-write-row'), true);
  assert.match(await page.textContent('#prompt-help'), /서버가 영상용 글로 다듬어서/);
  let body = await submitJob('로컬 테스트 바닷가 노을');
  assert.equal(field(body, 'prompt'), '로컬 테스트 바닷가 노을');
  assert.equal(field(body, 'title'), undefined);
  await card('로컬 테스트 바닷가 노을').locator('.st.completed').waitFor({timeout: 60000});
  assert.equal(provider.length, 0);
  ok('키 없음: 로컬 서버(/api/jobs)로만 보내고 완성, 공급자 API 호출 0회');

  // 2) OpenAI 키: 키를 넣기 전에는 로컬, 넣은 뒤에는 글은 OpenAI·영상은 로컬 서버
  await page.click('#ai-box > summary');
  await page.check('input[name=ai-method][value=openai]');
  assert.equal(await page.textContent('#ai-current'), 'OpenAI 키 · 키 없음, 로컬 서버');
  assert.equal(await page.isVisible('#ai-key-input'), true);
  assert.match(await page.textContent('[data-ai-desc]'), /2026년 9월 24일에 영상 API\(Sora 2\)를 닫아서, OpenAI 키로는 영상용 글만 쓰고 영상은 로컬 서버가 만들어요/);
  assert.match(await page.textContent('[data-ai-note]'), /키 주인의 OpenAI 계정에 청구돼요/);
  assert.match(await page.textContent('[data-ai-status]'), /키를 넣기 전에는 지금처럼 로컬 서버가/);
  body = await submitJob('키 없는 오픈에이아이 선택');
  assert.equal(field(body, 'prompt'), '키 없는 오픈에이아이 선택');
  assert.equal(provider.length, 0);
  ok('OpenAI를 골라도 키가 없으면 로컬 서버 그대로');
  await page.fill('#ai-key-input', KEY_O);
  assert.deepEqual(await storedKeys(page), []);
  assert.match(await page.textContent('[data-ai-nostore]'), /^키는 저장하지 않습니다\. 새로고침하면 다시 붙여 넣어야 합니다\.$/);
  assert.equal(await page.locator('#ai-method input[type=checkbox]').count(), 0, '이 기기에 저장 칸은 없다');
  assert.match(await page.textContent('[data-ai-status]'), /글은 GPT-6\.1 Terra, 영상은 로컬 서버/);
  assert.equal(await page.textContent('#ai-current'), 'OpenAI 키 · 글은 OpenAI, 영상은 로컬 서버');
  await page.press('#ai-key-input', 'Enter');
  await page.waitForTimeout(300);
  assert.equal(local.filter(r => r.url === url + '/api/jobs' && r.method === 'POST').length, 2, '키 칸의 Enter 는 영상 만들기를 누르지 않는다');
  assert.match(await page.textContent('#prompt-help'), /OpenAI가 영상용 글로 다듬은 뒤 로컬 서버가 만들어요/);
  body = await submitJob('오픈에이아이 테스트 비 오는 서울 밤거리');
  assert.equal(provider.length, 1);
  const o = provider[0];
  assert.equal(o.headers.authorization, 'Bearer ' + KEY_O);
  assert.equal(o.body.model, 'gpt-6.1-terra'); assert.equal(o.body.store, false);
  assert.match(JSON.stringify(o.body.input), /오픈에이아이 테스트 비 오는 서울 밤거리/);
  assert.match(JSON.stringify(o.body.input), /Duration: 8 seconds/);
  assert.equal(field(body, 'prompt'), OPENAI_TEXT);
  assert.equal(field(body, 'title'), '오픈에이아이 테스트 비 오는 서울 밤거리');
  await card('오픈에이아이 테스트 비 오는 서울 밤거리').locator('.st.completed').waitFor({timeout: 60000});
  assert.deepEqual(await storedKeys(page), []);
  ok('OpenAI 키: Responses API로 글을 쓰고 그 글로 로컬 서버 작업 완성');

  // 3) Claude 키: 미리 다듬기·보내기 (키는 저장하지 않음)
  await page.check('input[name=ai-method][value=claude]');
  assert.match(await page.textContent('[data-ai-desc]'), /Claude는 영상을 만들지 못해서, Claude 키로는 영상용 글만 쓰고 영상은 로컬 서버가 만들어요/);
  assert.equal(await page.inputValue('#ai-key-input'), '');
  await page.fill('#ai-key-input', KEY_C);
  assert.deepEqual(await storedKeys(page), []);
  ok('OpenAI·Claude 키를 넣어도 sessionStorage·localStorage 어디에도 저장하지 않음');
  await page.fill('#prompt', '클로드 테스트 고양이가 창가에서 하품한다');
  assert.equal(await page.textContent('#ai-write'), 'Claude로 미리 다듬기');
  await page.click('#ai-write');
  await page.waitForFunction(text => document.querySelector('#prompt').value === text, CLAUDE_TEXT);
  assert.equal(provider.length, 2);
  const c = provider[1];
  assert.equal(c.headers['x-api-key'], KEY_C); assert.equal(c.headers['anthropic-dangerous-direct-browser-access'], 'true'); assert.equal(c.headers['anthropic-version'], '2023-06-01');
  assert.equal(c.body.model, 'claude-opus-5-5');
  assert.match(JSON.stringify(c.body.messages), /클로드 테스트 고양이가 창가에서 하품한다/);
  body = await submitJob(CLAUDE_TEXT);
  assert.equal(provider.length, 2, '미리 다듬은 글은 다시 다듬지 않는다');
  assert.equal(field(body, 'prompt'), CLAUDE_TEXT);
  assert.equal(field(body, 'title'), '클로드 테스트 고양이가 창가에서 하품한다');
  await card('클로드 테스트 고양이가 창가에서 하품한다').locator('.st.completed').waitFor({timeout: 60000});
  assert.deepEqual(await storedKeys(page), []);
  ok('Claude 키: 미리 다듬기 → 그 글 그대로 로컬 서버 작업 완성');

  // 오류: 429·401 은 쉬운 말로, 작업은 보내지 않는다
  const jobsBefore = local.filter(r => r.url === url + '/api/jobs' && r.method === 'POST').length;
  claudeFail = 429; await page.fill('#prompt', '한도 테스트'); await page.click('#go');
  await page.waitForFunction(() => /요청 한도에 걸렸어요\(429\)/.test(document.querySelector('#msg').textContent));
  claudeFail = 401; await page.click('#ai-write');
  await page.waitForFunction(() => /Claude API 키가 맞지 않아요\(401\)/.test(document.querySelector('#msg').textContent));
  assert.doesNotMatch(await page.textContent('#msg'), /sk-ant/);
  assert.equal(local.filter(r => r.url === url + '/api/jobs' && r.method === 'POST').length, jobsBefore);
  ok('429·401 오류는 한국어로 알리고 작업을 보내지 않음, 키는 화면에 안 나옴');

  // 장면 수정: 수정 지시를 Claude가 프롬프트에 반영해 저장
  const done = card('클로드 테스트 고양이가 창가에서 하품한다');
  await done.locator('[data-recovery="edit"]').click();
  await page.locator('#recovery-dialog[open]').waitFor();
  assert.match(await page.textContent('#recovery-instructions-note'), /Claude가 위 프롬프트에 반영합니다/);
  await page.fill('#recovery-instructions', '아침 햇빛처럼 더 밝게');
  const edit = page.waitForRequest(r => /\/api\/jobs\/[^/]+\/edit$/.test(r.url()) && r.method() === 'POST');
  await page.click('#recovery-form button[value="save"]');
  const patch = JSON.parse((await edit).postData());
  assert.equal(patch.prompt, CLAUDE_REVISED);
  assert.equal(provider.length, 5);
  assert.match(provider[4].body.system, /edit instruction/i);
  assert.match(JSON.stringify(provider[4].body.messages), /아침 햇빛처럼 더 밝게/);
  await page.locator('#recovery-dialog[open]').waitFor({state: 'detached'}).catch(() => {});
  await page.waitForFunction(() => !document.querySelector('#recovery-dialog').open);
  ok('장면 수정: 수정 지시를 Claude가 반영한 프롬프트로 저장');

  // OpenAI 틀린 키: 브라우저에는 연결 실패로만 보여도 모델 조회(GET /v1/models/…)로 키가 틀렸다고 알리고 작업은 보내지 않는다
  await page.check('input[name=ai-method][value=openai]');
  assert.equal(await page.inputValue('#ai-key-input'), KEY_O);
  const jobsBeforeWrong = local.filter(r => r.url === url + '/api/jobs' && r.method === 'POST').length;
  openaiWrongKey = true;
  await page.fill('#prompt', '틀린 오픈에이아이 키'); await page.click('#go');
  await page.waitForFunction(() => /OpenAI API 키가 맞지 않아요\(401\)/.test(document.querySelector('#msg').textContent));
  openaiWrongKey = false;
  assert.equal(provider.length, 7);
  assert.equal(provider[6].url, 'https://api.openai.com/v1/models/gpt-6.1-terra');
  assert.equal(provider[6].headers.authorization, 'Bearer ' + KEY_O);
  assert.doesNotMatch(await page.textContent('#msg'), /sk-/);
  assert.equal(local.filter(r => r.url === url + '/api/jobs' && r.method === 'POST').length, jobsBeforeWrong);
  ok('OpenAI 틀린 키(CORS 없는 401 → 연결 실패): 모델 조회로 키가 틀렸다고 알리고 작업은 보내지 않음');

  // 두 번 누르기: 키로 글을 쓰는 동안(10~40초) Ctrl+Enter 를 또 눌러도 키 요금·작업은 한 번만
  const jobsBeforeDouble = local.filter(r => r.url === url + '/api/jobs' && r.method === 'POST').length, providerBeforeDouble = provider.length;
  openaiSlow = 1500;
  await page.fill('#prompt', '두 번 누르기 오픈에이아이');
  const doubleSent = page.waitForRequest(r => r.url() === url + '/api/jobs' && r.method() === 'POST', {timeout: 60000});
  await page.focus('#prompt'); await page.keyboard.press('Control+Enter'); await page.waitForTimeout(200);
  assert.equal(await page.isDisabled('#go'), true);
  await page.keyboard.press('Control+Enter');
  await doubleSent; await page.waitForTimeout(1500);
  openaiSlow = 0;
  assert.equal(provider.length - providerBeforeDouble, 1);
  assert.equal(local.filter(r => r.url === url + '/api/jobs' && r.method === 'POST').length - jobsBeforeDouble, 1);
  assert.equal(await page.isDisabled('#go'), false);
  ok('키로 글 쓰는 중 Ctrl+Enter 를 두 번 눌러도 OpenAI 요청·작업은 한 번');

  // 키 지우기
  await page.click('#ai-clear');
  assert.deepEqual(await storedKeys(page), []);
  assert.equal(await page.inputValue('#ai-key-input'), '');
  assert.match(await page.textContent('[data-ai-status]'), /OpenAI·Claude 키를 지웠어요/);
  assert.equal(await page.isHidden('#ai-write-row'), true);
  await page.check('input[name=ai-method][value=claude]');
  assert.equal(await page.inputValue('#ai-key-input'), '');
  await page.check('input[name=ai-method][value=openai]');
  ok('키 지우기: 두 키를 메모리에서 지우고 키 칸이 빔');

  // 새로고침: 키 칸은 비고(예전 판이 저장한 키 칸도 지운다), 고른 방식은 남고, 키가 없으니 로컬 서버가 맡는다
  await page.fill('#ai-key-input', KEY_O);
  await page.evaluate(([o, c]) => { for (const s of [sessionStorage, localStorage]) { s.setItem('h3video.ai.remember', '1'); s.setItem('h3video.ai.openaiKey', o); s.setItem('h3video.ai.claudeKey', c); } }, [KEY_O, KEY_C]);
  await page.reload();
  await page.locator('#ai-box:not([hidden])').waitFor();
  await page.locator('#pill-fl.ok').waitFor({timeout: 15000});
  assert.deepEqual(await storedKeys(page), []);
  assert.equal(await page.isChecked('input[name=ai-method][value=openai]'), true);
  await page.click('#ai-box > summary');
  assert.equal(await page.inputValue('#ai-key-input'), '');
  await page.check('input[name=ai-method][value=claude]');
  assert.equal(await page.inputValue('#ai-key-input'), '');
  assert.equal(await page.textContent('#ai-current'), 'Claude 키 · 키 없음, 로컬 서버');
  const providerBeforeReload = provider.length;
  body = await submitJob('새로고침 뒤 키 없음');
  assert.equal(field(body, 'prompt'), '새로고침 뒤 키 없음');
  assert.equal(provider.length, providerBeforeReload);
  await card('새로고침 뒤 키 없음').locator('.st.completed').waitFor({timeout: 60000});
  assert.deepEqual(await storedKeys(page), []);
  ok('새로고침: 키 칸이 비고 두 저장소에 키 없음, 고른 방식은 남고 키가 없으니 로컬 서버로 완성');

  // 우리 서버로는 키가 가지 않는다
  for (const r of local) for (const key of [KEY_O, KEY_C]) {
    assert.ok(!r.url.includes(key) && !r.body.includes(key) && !JSON.stringify(r.headers).includes(key), '로컬 서버 요청에 키가 들어감: ' + r.url);
  }
  for (const r of provider) for (const key of [KEY_O, KEY_C]) assert.ok(!r.url.includes(key));
  ok(`로컬 서버 요청 ${local.length}개·공급자 요청 ${provider.length}개 모두 주소·본문에 키 없음`);

  // 4) 휴대폰 390px
  const phone = await browser.newContext({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true, deviceScaleFactor: 2});
  const mobile = await phone.newPage();
  mobile.on('pageerror', e => errors.push('mobile ' + e.message));
  await mobile.goto(url + '/');
  await mobile.locator('#ai-box:not([hidden])').waitFor();
  await mobile.locator('#pill-fl.ok').waitFor({timeout: 15000});
  const go = await mobile.locator('#go').boundingBox();
  assert.ok(go && go.y + go.height <= 844 && go.y > 844 - 140, `만들기 버튼이 화면 아래에 붙어 있지 않음 ${JSON.stringify(go)}`);
  await mobile.click('#ai-box > summary');
  assert.ok((await mobile.locator('#ai-box > summary').boundingBox()).height >= 44);
  await mobile.check('input[name=ai-method][value=openai]');
  await mobile.locator('#ai-key-input').waitFor();
  const overflow = await mobile.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  assert.ok(overflow <= 0, `가로 넘침 ${overflow}px`);
  for (const sel of ['.ai-opt', '#ai-key-input', '#ai-model', '#ai-clear']) {
    for (const box of await mobile.locator('#ai-method ' + sel).evaluateAll(els => els.map(e => e.getBoundingClientRect().toJSON()))) {
      assert.ok(box.height >= 44, `${sel} 높이 ${box.height}`); assert.ok(box.right <= 390 && box.left >= 0, `${sel} 화면 밖 ${box.left}~${box.right}`);
    }
  }
  assert.equal(await mobile.evaluate(() => getComputedStyle(document.querySelector('#ai-key-input')).fontSize), '16px');
  await mobile.screenshot({path: path.join(temp, 'ai-method-390.png'), fullPage: false});
  await phone.close();
  ok('휴대폰 390px: 만들기 버튼은 그대로 화면 아래, 가로 넘침 없음, 누름 대상 44px 이상, 입력 글자 16px');

  assert.deepEqual(errors, []);
  console.log('생성 방식(키) 브라우저 점검 끝 · 스크린샷 ' + path.join(temp, 'ai-method-390.png'));
} catch (error) {
  failed = true;
  console.error(error);
  console.error(stderr);
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  await new Promise(resolve => { if (server.exitCode !== null) resolve(); else server.once('exit', resolve); setTimeout(resolve, 5000); });
}
process.exit(failed ? 1 : 0);
