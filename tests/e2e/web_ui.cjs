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
    await page.fill('#seconds', '5');
    await page.waitForFunction(() => document.querySelector('#split').textContent.includes('한 번에'));
    await page.click('#go');
    await card(page, 'e2e 글 영상').waitFor();
    await waitStatus(page, 'e2e 글 영상', 'completed');
    const c1 = card(page, 'e2e 글 영상');
    check(await c1.locator('video').count() === 1, '완성되면 영상이 카드 안에서 재생된다');
    check(await c1.locator('a[download]').count() === 1, '받기 링크');
    await c1.locator('[data-act="cmd"]').click();
    const cmd = await c1.locator('pre.code').first().textContent();
    check(cmd.startsWith('h3video gen ') && cmd.includes('-s 5') && /--seed \d+/.test(cmd), '명령어로 보기: ' + cmd.slice(0, 60));
    check(!/--seed 0\b/.test(cmd), '시드를 비우면 무작위');

    step = '그림으로 시작';
    await mode(page, 'fl');
    await page.click('#go');
    check((await page.textContent('#msg')).includes('그림을 한 장 이상'), '그림이 없으면 알려 준다');
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
    await page.setInputFiles('.drop[data-zone="pages"] input[type=file]', [m('page-01.png'), m('page-02.png')]);
    await page.setInputFiles('.drop[data-zone="json"] input[type=file]', m('toto.json'));
    await page.waitForSelector('.plan .srow');
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'story 장면 표: 가로 넘침 없음');
    await page.locator('.plan').scrollIntoViewIfNeeded();
    await page.screenshot({path: path.join(OUT, 'phone-story-plan.png')});
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
      await page.fill('#base', BASE + '/');
      await page.click('#base-save');
      await page.waitForSelector('#feed article.job', {timeout: 15000});
      await page.waitForSelector('#pill-base.ok');
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
