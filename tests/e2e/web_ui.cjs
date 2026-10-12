// 웹 UI 브라우저 확인: 네 가지 만드는 방법, 장면 나누기 안내, 파일 넣기, 작업 카드(재생·명령어·다시 하기·같은 설정으로 다시),
// JSON 한번에 장면 표와 이어 붙인 영상, 휴대폰 폭(390px) 가로 넘침·고정 버튼, 다른 출처(허브)에서 서버 주소로 연결.
// tests/test_web_browser.py 가 모의 서버와 웹 서버를 띄우고 부른다:
//   node tests/e2e/web_ui.cjs <웹 UI 주소> <스크린샷 폴더> <자료 폴더> [<다른 출처에서 연 ui.html 주소>]
// Playwright: H3_PLAYWRIGHT(모듈 경로, 기본 playwright-core), 브라우저는 CHROME(실행 파일, 없으면 Playwright 기본)
'use strict';
const path = require('path');
const fs = require('fs');
const {chromium} = require(process.env.H3_PLAYWRIGHT || 'playwright-core');

const [BASE, OUT, MEDIA, HUB] = process.argv.slice(2);
const DESK = {width: 1400, height: 1000}, PHONE = {width: 390, height: 844};
const errors = [];
let step = '';
const m = n => path.join(MEDIA, n);
fs.mkdirSync(OUT, {recursive: true});

function check(ok, what) {
  if (!ok) throw new Error(`[${step}] ${what}`);
  console.log(`  ok  ${what}`);
}
async function newPage(browser, vp, allowNet = false) {
  const page = await browser.newPage({viewport: vp, deviceScaleFactor: 1});
  page.on('pageerror', e => errors.push(`${step}: ${e.message}`));
  page.on('console', msg => {
    if (msg.type() !== 'error') return;
    if (allowNet && /Failed to load resource|ERR_CONNECTION_REFUSED|Failed to fetch|CORS/i.test(msg.text())) return;
    if (/Failed to load resource: the server responded with a status of 400/.test(msg.text())) return;   // 일부러 낸 잘못된 요청
    errors.push(`${step}: console ${msg.text()}`);
  });
  return page;
}
async function shot(page, name) {
  await page.waitForTimeout(250);
  await page.screenshot({path: path.join(OUT, name + '.png'), fullPage: true});
}
const card = (page, title) => page.locator('#feed article.job', {has: page.locator('h3', {hasText: title})}).first();
async function waitStatus(page, title, st, timeout = 30000) {
  await card(page, title).locator(`.st.${st}`).waitFor({timeout});
}
async function mode(page, name) {
  await page.click(`.mode[data-mode="${name}"]`);
  await page.waitForTimeout(150);
}
const visible = (page, sel) => page.locator(sel).first().isVisible();
// 끌어다 놓기: 진짜 DataTransfer 로 drop 이벤트 (여러 파일·여러 종류를 한꺼번에)
async function dropOn(page, sel, names) {
  const files = names.map(n => ({name: n, b64: fs.readFileSync(m(n)).toString('base64'),
    type: n.endsWith('.png') ? 'image/png' : n.endsWith('.json') ? 'application/json' : n.endsWith('.wav') ? 'audio/wav' : n.endsWith('.mp4') ? 'video/mp4' : n.endsWith('.zip') ? 'application/zip' : ''}));
  await page.evaluate(({sel, files}) => {
    const dt = new DataTransfer();
    for (const f of files) {
      const bin = atob(f.b64), a = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
      dt.items.add(new File([a], f.name, {type: f.type}));
    }
    const el = document.querySelector(sel);
    for (const t of ['dragenter', 'dragover', 'drop']) el.dispatchEvent(new DragEvent(t, {bubbles: true, cancelable: true, dataTransfer: dt}));
  }, {sel, files});
  await page.waitForTimeout(300);
}

(async () => {
  const browser = await chromium.launch(process.env.CHROME ? {executablePath: process.env.CHROME} : {});
  try {
    // ---------- 넓은 화면 ----------
    step = '넓은 화면: 처음';
    let page = await newPage(browser, DESK);
    await page.goto(BASE, {waitUntil: 'domcontentloaded'});
    await page.waitForSelector('#pill-fl.ok', {timeout: 15000});
    check(await page.locator('.mode').count() === 4, '만드는 방법 버튼 4개');
    check((await page.textContent('.empty')).includes('아직 만든 영상이 없어요'), '빈 목록 안내');
    check(await page.locator('#conn').isHidden(), '이 서버가 준 화면이면 서버 주소 칸이 없다');
    await page.click('#info summary');
    check((await page.textContent('#spec')).includes('참고 자료 한도'), '모델 정보가 목록으로 나온다');
    const fields = {
      text: {'#prompt': true, '.drop[data-zone="first"]': false, '.drop[data-zone="ref"]': false, '.drop[data-zone="json"]': false, '#seconds': true},
      fl: {'#prompt': true, '.drop[data-zone="first"]': true, '.drop[data-zone="ref"]': false, '.drop[data-zone="json"]': false},
      ref: {'#prompt': true, '.drop[data-zone="first"]': false, '.drop[data-zone="ref"]': true, '.drop[data-zone="json"]': false},
      story: {'#prompt': false, '#seconds': false, '.drop[data-zone="json"]': true, '.drop[data-zone="pages"]': true, '#more': false},
    };
    for (const [md, want] of Object.entries(fields)) {
      step = `넓은 화면: ${md} 칸`;
      await mode(page, md);
      for (const [sel, v] of Object.entries(want)) check(await visible(page, sel) === v, `${md}: ${sel} ${v ? '보임' : '숨김'}`);
      await shot(page, `desk-${md}-empty`);
    }

    step = '글로 만들기';
    await mode(page, 'text');
    await page.fill('#prompt', '');
    await page.click('#go');
    check((await page.textContent('#msg')).includes('글로 적어'), '글이 없으면 쉬운 말로 알려 준다');
    await page.fill('#prompt', 'e2e 글 영상: 비 오는 서울 밤거리');
    await page.fill('#seed', 'abc');
    await page.click('#go');
    check((await page.textContent('#msg')).includes('시드는 숫자만'), '시드가 숫자가 아니면 알려 준다');
    await page.fill('#seed', '');
    await page.fill('#seconds', '40');
    await page.waitForFunction(() => document.querySelector('#split').textContent.includes('장면 4개'));
    check((await page.textContent('#split')).includes('10·10·10·10'), '40초 → 장면 4개 안내');
    check((await page.textContent('#go')).includes('장면 4개'), '만들기 버튼에도 장면 수');
    await shot(page, 'desk-text-40s');
    await page.fill('#seconds', '600');
    await page.waitForFunction(() => document.querySelector('#split').textContent.includes('장면 60개'));
    const long = await page.textContent('#split');
    check(long.includes('10초씩') && !long.includes('10·10·10·10·10·10·10'), '긴 영상은 장면 길이를 다 늘어놓지 않는다: ' + long);
    await page.fill('#seconds', '5');
    await page.waitForFunction(() => document.querySelector('#split').textContent.includes('한 번에'));
    await page.click('#go');
    await card(page, 'e2e 글 영상').waitFor();
    await waitStatus(page, 'e2e 글 영상', 'completed');
    const c1 = card(page, 'e2e 글 영상');
    check(await c1.locator('video').count() === 1, '완성되면 영상이 카드 안에서 재생된다');
    check(await c1.locator('a[download]').count() === 1, '받기 링크');
    check((await c1.locator('a[download]').getAttribute('href')).endsWith('?download=1'), '받기는 내려받기로 (?download=1)');
    await c1.locator('[data-act="cmd"]').click();
    const cmd = await c1.locator('pre.code').first().textContent();
    check(cmd.startsWith('h3video gen ') && cmd.includes('-s 5') && /--seed \d+/.test(cmd), '명령어로 보기: ' + cmd.slice(0, 60));
    check(!/--seed 0\b/.test(cmd), '시드를 비우면 무작위');

    step = '그림으로 시작';
    await mode(page, 'fl');
    await page.click('#go');
    check((await page.textContent('#msg')).includes('그림을 한 장 이상'), '그림이 없으면 알려 준다');
    await dropOn(page, '.drop[data-zone="first"]', ['first.png', 'face.png']);
    check((await page.textContent('.drop[data-zone="first"] .nm')).includes('first.png') && (await page.textContent('.drop[data-zone="last"] .nm')).includes('face.png'),
      '첫 장면 칸에 그림 두 장을 놓으면 첫·끝 장면으로 나눠 넣는다');
    await page.click('.drop[data-zone="last"] .x');
    check(await page.locator('.drop[data-zone="last"] img').count() === 0, '끝 장면 빼기');
    await page.setInputFiles('.drop[data-zone="first"] input[type=file]', m('first.png'));
    await page.waitForSelector('.drop[data-zone="first"] img');
    await page.fill('#prompt', 'e2e 그림 영상: 아이가 웃는다');
    await shot(page, 'desk-fl-filled');
    await page.click('#go');
    await card(page, 'e2e 그림 영상').waitFor();
    await waitStatus(page, 'e2e 그림 영상', 'completed');
    const c2 = card(page, 'e2e 그림 영상');
    check((await c2.locator('.tag').textContent()).includes('그림에서 시작'), '카드에 만든 방법');
    check(await c2.locator('.thumbs img').count() === 1, '카드에 넣은 그림 미리보기');

    step = '참고 자료로';
    await mode(page, 'ref');
    await page.setInputFiles('.drop[data-zone="ref"] input[type=file]', [m('face.png'), m('style.png'), m('voice.wav'), m('clip.mp4')]);
    await page.waitForFunction(() => document.querySelector('#counts-ref').textContent.includes('사진 2/9'));
    const counts = await page.textContent('#counts-ref');
    check(counts.includes('소리 1/3') && counts.includes('영상 1/3') && counts.includes('합계 4/12'), '종류별 개수와 한도: ' + counts);
    check((await page.locator('#tiles-ref .badge').allTextContents()).join(',') === '사진 1,사진 2,소리 1,영상 1', '넣은 순서대로 번호');
    await page.waitForFunction(() => document.querySelector('#warns-ref').textContent.includes('2~15초'));
    check(true, '1초짜리 영상은 2~15초가 좋다고 알려 준다');
    await page.locator('#tiles-ref .tile').nth(3).locator('.x').click();
    check((await page.textContent('#counts-ref')).includes('합계 3/12'), '빼기 버튼');
    await page.fill('#prompt', 'e2e 참고 영상: 1번 사진 사람이 걷는다');
    await shot(page, 'desk-ref-filled');
    await page.click('#go');
    await card(page, 'e2e 참고 영상').waitFor();
    await waitStatus(page, 'e2e 참고 영상', 'completed');
    check((await card(page, 'e2e 참고 영상').locator('.tag').textContent()).includes('참고 자료'), '참고 자료 카드');

    step = '꺼진 서버로는 보내지 않는다';
    await mode(page, 'text');
    const nCards = await page.locator('#feed article.job').count();
    await page.route('**/api/health', r => r.fulfill({contentType: 'application/json', body: JSON.stringify(
      {fl2va: false, ref2va: true, queue: 0, current: null, endpoints: {fl2va: 'http://x:1', ref2va: 'http://x:2'},
       hints: {fl2va: '글·그림 서버가 꺼져 있어요 → bash scripts/up.sh', ref2va: null}})}));
    await page.fill('#prompt', 'e2e 꺼진 서버');
    await page.click('#go');
    await page.waitForFunction(() => document.querySelector('#msg').textContent.includes('보내지 않았어요'));
    check(await page.locator('#feed article.job').count() === nCards, '꺼진 서버면 작업을 만들지 않고 알려 준다');
    await page.unroute('**/api/health');

    step = '실패와 다시 하기';
    await mode(page, 'text');
    await page.fill('#prompt', 'e2e 실패 FAILME');
    await page.fill('#seconds', '4');
    await page.click('#go');
    await waitStatus(page, 'e2e 실패 FAILME', 'failed');
    const c3 = card(page, 'e2e 실패 FAILME');
    check((await c3.locator('.err-box').textContent()).length > 5, '실패하면 쉬운 말로');
    await c3.locator('[data-act="retry"]').click();
    await page.waitForFunction(() => [...document.querySelectorAll('#feed article.job h3')].filter(h => h.textContent.includes('e2e 실패 FAILME')).length === 2);
    await page.waitForFunction(() => [...document.querySelectorAll('#feed article.job')].some(a => a.querySelector('h3').textContent.includes('e2e 실패 FAILME') && a.querySelector('.st.completed')), null, {timeout: 30000});
    check(true, '다시 하기로 새 작업이 생겨 완성된다');

    step = '같은 설정으로 다시';
    await card(page, 'e2e 그림 영상').locator('[data-act="again"]').click();
    await page.waitForSelector('.drop[data-zone="first"] img');
    check(await page.getAttribute('.mode[data-mode="fl"]', 'aria-selected') === 'true', '그림으로 시작으로 바뀐다');
    check((await page.inputValue('#prompt')).includes('e2e 그림 영상'), '글과 그림을 다시 채운다');

    step = 'JSON 한번에';
    await mode(page, 'story');
    check(await page.locator('#go').isDisabled(), 'JSON 을 넣기 전에는 만들기 버튼이 꺼져 있다');
    check((await page.textContent('#go')).includes('JSON 파일을 넣어'), '버튼이 할 일을 알려 준다');
    await page.setInputFiles('.drop[data-zone="pages"] input[type=file]', [m('page-01.png'), m('page-02.png')]);
    await page.setInputFiles('.drop[data-zone="json"] input[type=file]', m('toto.json'));
    await page.waitForSelector('.plan .srow');
    check(await page.locator('.plan .srow').count() === 3, '장면 표: 3장면');
    check(await page.locator('.plan .srow img').count() === 2, '장면마다 맞춘 그림 미리보기');
    check((await page.textContent('#plan')).includes('그림 없는 장면 1개'), '그림 없는 장면 경고');
    check((await page.textContent('.plan-foot')).includes('21초'), '합계 길이');
    check((await page.textContent('#go')).includes('장면 3개'), '만들기 버튼에 장면 수');
    await shot(page, 'desk-story-plan');
    await page.locator('#plan .warns').scrollIntoViewIfNeeded();
    await page.evaluate(() => window.scrollBy(0, 120));
    await page.screenshot({path: path.join(OUT, 'desk-story-plan-view.png')});
    await page.click('#go');
    await card(page, '토토의 우산').waitFor();
    await waitStatus(page, '토토의 우산', 'completed', 60000);
    const c4 = card(page, '토토의 우산');
    check(await c4.locator('video').count() === 1, '이어 붙인 영상');
    check(await c4.locator('.sli').count() === 3, '장면별 진행 목록');
    await c4.locator('[data-act="cmd"]').click();
    check((await c4.locator('.cmd').textContent()).includes('h3video json --resume'), 'JSON 한번에 명령어');
    await page.evaluate(() => window.scrollTo(0, 0));
    await shot(page, 'desk-feed');
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), '넓은 화면 가로 넘침 없음');
    await page.close();

    // ---------- 휴대폰 ----------
    page = await newPage(browser, PHONE);
    step = '휴대폰';
    await page.goto(BASE, {waitUntil: 'domcontentloaded'});
    await page.waitForSelector('#pill-fl.ok', {timeout: 15000});
    await page.waitForSelector('#feed article.job');
    for (const md of ['text', 'fl', 'ref', 'story']) {
      await mode(page, md);
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${md}: 가로 넘침 없음`);
      if (md !== 'story') {
        const box = await page.locator('#go').boundingBox();
        check(box && box.y + box.height <= PHONE.height && box.y > PHONE.height - 140, `${md}: 만들기 버튼이 화면 아래에 붙어 있다`);
      }
      await page.screenshot({path: path.join(OUT, `phone-${md}.png`)});
    }
    await mode(page, 'story');
    await dropOn(page, '.drop[data-zone="json"]', ['toto.json', 'page-01.png', 'page-02.png']);   // 한꺼번에 놓아도 제자리로
    await page.waitForSelector('.plan .srow');
    check(await page.locator('#tiles-pages .tile').count() === 2 && await page.locator('.plan .srow img').count() === 2, 'JSON 과 쪽 그림을 한 칸에 같이 놓아도 나눠 넣는다');
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'story 장면 표: 가로 넘침 없음');
    await page.locator('.plan').scrollIntoViewIfNeeded();
    await page.screenshot({path: path.join(OUT, 'phone-story-plan.png')});
    step = '동화책 만들기 zip';
    await mode(page, 'text');
    await dropOn(page, 'main', ['book.zip']);   // 글로 만들기 화면 아무 데나 놓아도 JSON 한번에로
    await page.waitForFunction(() => document.querySelectorAll('.plan .srow').length === 2 && document.querySelector('.plan-head').textContent.includes('달빛 토끼'));
    check(await page.getAttribute('.mode[data-mode="story"]', 'aria-selected') === 'true', 'zip 을 놓으면 JSON 한번에로 바뀐다');
    check((await page.textContent('.drop[data-zone="json"] .nm')).includes('book.json') && await page.locator('#tiles-pages .tile').count() === 3, 'zip 안의 book.json 과 그림을 칸에 나눠 넣는다');
    check(await page.locator('#tiles-pages .tile.unused').count() === 1, '쓰지 않는 그림(캐릭터 시트)은 흐리게');
    check((await page.textContent('#toast-t')).includes('book.zip에서 4개를 꺼냈어요 (쓰지 않는 1개는 뺌)'), 'zip 안내: ' + await page.textContent('#toast-t'));
    await page.screenshot({path: path.join(OUT, 'phone-zip.png')});
    await mode(page, 'text');
    await shot(page, 'phone-full');
    await page.close();

    // ---------- 다른 출처(허브)에서 연 화면 ----------
    if (HUB) {
      step = '허브에서 연 화면';
      page = await newPage(browser, DESK, true);
      await page.goto(HUB, {waitUntil: 'domcontentloaded'});
      await page.waitForSelector('#conn:not([hidden])');
      check(true, '서버 주소 칸이 보인다');
      await page.waitForSelector('#conn-msg.bad');
      check(await page.locator('#aspect option').count() === 7 && await page.locator('#size option').count() === 5, '연결 전에도 화면비·크기 칸이 차 있다');
      check((await page.textContent('#banners')).trim() === '', '같은 안내를 두 번 띄우지 않는다');
      await page.fill('#base', BASE + '/');
      await page.click('#base-save');
      await page.waitForSelector('#feed article.job', {timeout: 15000});
      await page.waitForSelector('#pill-base.ok');
      check(await page.locator('#conn').isHidden(), '연결되면 서버 주소 칸을 닫는다');
      check(await page.evaluate(() => localStorage.getItem('h3video.server')) === BASE, '서버 주소를 저장한다');
      const v = await page.locator('#feed video').first().getAttribute('src');
      check(v.startsWith(BASE + '/files/'), '영상도 그 서버 주소로');
      await shot(page, 'hub-desk');
      await page.reload({waitUntil: 'domcontentloaded'});
      await page.waitForSelector('#feed article.job', {timeout: 15000});
      check(true, '다시 열어도 저장한 주소로 바로 연결');
      await page.close();
    }
  } catch (e) {
    errors.push(e.message);
  } finally {
    await browser.close();
  }
  if (errors.length) {
    console.error('실패:\n' + errors.map(e => '  ' + e).join('\n'));
    process.exit(1);
  }
  console.log('웹 UI 확인 끝');
})();
