// 여러 편 한꺼번에 화면: JSON·zip 여러 개(잘못된 파일 빼기·zip 안 그림) → 편마다 대기열에 넣기(multi 표시·주요 인물 설정) →
// 넣은 편 목록에서 완성 확인, 휴대폰 폭(390px). tests/test_multi.py 가 부른다: node tests/e2e/multi_ui.cjs <웹 UI 주소> <자료 폴더>
'use strict';
const path = require('path');
const {chromium} = require(process.env.H3_PLAYWRIGHT || 'playwright-core');
const [BASE, MEDIA] = process.argv.slice(2);
const errors = [];
function check(ok, what) { if (!ok) throw new Error(what); console.log(`  ok  ${what}`); }
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME || undefined});
  try {
    const page = await browser.newPage({viewport: {width: 1400, height: 1000}});
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(BASE + '/');
    await page.locator('.mode[data-mode="story"]').click();
    await page.locator('#multi-box > summary').click();
    await page.setInputFiles('#multi-drop input[type=file]', [path.join(MEDIA, 'toto.json'), path.join(MEDIA, 'book.zip'), path.join(MEDIA, 'bad.json')]);
    await page.waitForFunction(() => document.querySelectorAll('#multi-list li').length === 3 && !document.querySelector('#multi-list').textContent.includes('확인 중'));
    check(await page.locator('#multi-go').isDisabled(), '잘못된 파일이 있으면 시작할 수 없음');
    await page.getByRole('button', {name: 'bad.json 빼기'}).click();
    const listText = await page.textContent('#multi-list');
    check(/토토의 우산/.test(listText) && /달빛 토끼[\s\S]*zip 그림 2장/.test(listText), 'JSON과 zip(안의 그림)을 편으로 읽음');
    // 모든 편에 쓸 인물 설정
    await page.locator('#cast-box > summary').click();
    await page.click('#cast-new'); await page.keyboard.type('Toto');
    await page.fill('[aria-label="인물 1 목소리"]', '작고 높은 목소리');
    await page.waitForFunction(() => !document.querySelector('#multi-list').textContent.includes('확인 중') && !document.querySelector('#multi-go').disabled);
    const made = [];
    page.on('response', async r => { if (r.url().endsWith('/api/story') && r.request().method() === 'POST') made.push(await r.json()); });
    await page.click('#multi-go');
    await page.waitForFunction(() => /2편을 대기열에 넣었어요/.test(document.querySelector('#multi-msg').textContent), null, {timeout: 20000});
    check(made.length === 2 && made.every(m => /^multi-/.test(m.multi) && m.multi === made[0].multi), '편마다 같은 묶음 표시로 넣음');
    check(made[0].cast?.[0]?.name === 'Toto' && made[0].clips.some(c => c.prompt.includes('Voice of Toto: 작고 높은 목소리')), '주요 인물 설정이 장면 프롬프트에');
    check(made[1].clips.every(c => c.image), 'zip 안의 그림을 첫 장면으로');
    await page.waitForFunction(() => document.querySelectorAll('#multi-sent li').length === 2, null, {timeout: 10000});
    check(await page.locator('#multi-list li').count() === 0, '넣은 편 목록');
    for (let i = 0; i < 60; i++) {
      await page.locator('#multi-box > summary').click(); await page.locator('#multi-box > summary').click();
      await page.waitForTimeout(500);
      if (await page.locator('#multi-sent li.done').count() === 2) break;
    }
    check(await page.locator('#multi-sent li.done').count() === 2, '두 편 모두 완성');
    const phone = await browser.newPage({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true});
    phone.on('pageerror', e => errors.push(e.message));
    await phone.goto(BASE + '/'); await phone.locator('.mode[data-mode="story"]').click(); await phone.locator('#multi-box > summary').click();
    await phone.setInputFiles('#multi-drop input[type=file]', [path.join(MEDIA, 'toto.json'), path.join(MEDIA, 'book.zip')]);
    await phone.waitForFunction(() => document.querySelectorAll('#multi-list li').length === 2);
    check(await phone.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '390px 가로 넘침 없음');
    if (process.env.H3_E2E_OUT) await phone.locator('#multi-box').screenshot({path: path.join(process.env.H3_E2E_OUT, 'video-maker-multi-390.png')});
    check(errors.length === 0, '페이지 오류 없음 ' + errors.join(' | '));
    console.log('여러 편 확인 끝');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
