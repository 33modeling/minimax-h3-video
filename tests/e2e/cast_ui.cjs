// 주요 인물 설정 화면: 예시·빈 인물, 저장·기본값, 글로 만들기 요청에 이름이 나온 인물 설정, JSON 안의 인물 불러오기,
// 인물을 고치면 장면 표(영상 프롬프트) 다시 받기, JSON 한번에 요청의 cast, 휴대폰 폭(390px).
// tests/test_cast.py 가 모의 서버와 웹 서버를 띄우고 부른다: node tests/e2e/cast_ui.cjs <웹 UI 주소> <자료 폴더>
'use strict';
const path = require('path');
const {chromium} = require(process.env.H3_PLAYWRIGHT || 'playwright-core');
const [BASE, MEDIA] = process.argv.slice(2);
const errors = [];
let step = '';
function check(ok, what) { if (!ok) throw new Error(`[${step}] ${what}`); console.log(`  ok  ${what}`); }
const LOOK = '인물 1 영상용 영어 고정 문구 (선택, 적으면 그대로 씀)';

(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME || undefined});
  try {
    const page = await browser.newPage({viewport: {width: 1400, height: 1000}});
    page.on('pageerror', e => errors.push(`${step}: ${e.message}`));
    await page.goto(BASE + '/');
    await page.locator('.mode[data-mode="text"]').click();

    step = '편집기';
    check(await page.locator('#cast-box').isVisible() && await page.textContent('#cast-count') === '없음', '글로 만들기에서 인물 칸이 보이고 비어 있음');
    await page.locator('#cast-box > summary').click();
    await page.selectOption('#cast-preset', '1');
    check(await page.inputValue('[aria-label="인물 1 이름"]') === '민준', '예시 인물(가게 주인 민준)을 더함');
    await page.click('#cast-new');
    check(await page.evaluate(() => document.activeElement?.getAttribute('aria-label') === '인물 2 이름'), '빈 인물을 더하면 이름 칸으로');
    await page.keyboard.type('지우'); await page.fill('[aria-label="인물 2 목소리"]', '밝고 부드러운 목소리');
    check(await page.textContent('#cast-count') === '2명' && await page.textContent('#cast-list .cast-card:nth-child(2) summary b') === '지우', '인물 수·이름 표시');
    await page.reload(); await page.locator('#cast-box > summary').click();
    check(await page.inputValue('[aria-label="인물 2 목소리"]') === '밝고 부드러운 목소리', '새로 고쳐도 남음');
    await page.click('#cast-save-default');
    await page.locator('.cast-card').nth(1).getByRole('button', {name: '빼기'}).click();
    await page.locator('.cast-card').nth(0).getByRole('button', {name: '빼기'}).click();
    check(await page.textContent('#cast-count') === '없음', '모두 빼기');
    await page.click('#cast-load-default');
    check(await page.textContent('#cast-count') === '2명', '기본값 불러오기');
    await page.getByLabel('인물 2 위로').click();
    check(await page.inputValue('[aria-label="인물 1 이름"]') === '지우', '순서 바꾸기');
    await page.getByLabel('인물 2 위로').click();

    step = '글로 만들기';
    await page.fill('#prompt', '빈 골목 카페의 아침');
    check(/인물 이름\(민준, 지우\)/.test(await page.textContent('#cast-use')), '이름이 없으면 쓰는 법 안내');
    await page.fill('#prompt', '민준이 커피를 내린다');
    check(/민준의 인물 설정이 함께/.test(await page.textContent('#cast-use')), '글에 나온 인물 안내');
    const [req] = await Promise.all([page.waitForRequest(r => r.url().endsWith('/api/jobs') && r.method() === 'POST'), page.click('#go')]);
    const sent = req.postDataBuffer().toString('utf8');
    for (const v of ['민준이 커피를 내린다', 'Character (민준): a man in his 40s with short black hair', 'Personality of 민준: 말수가 적고 꼼꼼하다.', 'Voice of 민준: 낮고 따뜻한 목소리, 느린 속도.']) check(sent.includes(v), `보낸 글에 ${v.slice(0, 30)}`);
    check(!sent.includes('Voice of 지우'), '글에 없는 인물은 붙이지 않음');

    step = 'JSON 한번에';
    await page.locator('.mode[data-mode="story"]').click();
    await page.setInputFiles('.drop[data-zone="json"] input[type=file]', path.join(MEDIA, 'toto.json'));
    await page.locator('.plan-head').waitFor();
    check(/주요 인물 1명\(Toto\)/.test(await page.textContent('#cast-status')) && await page.textContent('#cast-count') === '1명', 'JSON 안의 인물로 바뀜');
    check(/인물 설정 1명 반영/.test(await page.textContent('.plan-head')), '장면 표에 반영 표시');
    const prompts = () => page.$$eval('#plan .sp', ds => ds.map(d => d.textContent));
    check((await prompts())[0].includes('a tiny hedgehog in a green raincoat'), '장면 프롬프트에 영어 고정 문구');
    await page.fill(`[aria-label="${LOOK}"]`, 'a hedgehog with a blue hat');
    await page.waitForFunction(() => document.querySelector('#plan .sp')?.textContent.includes('blue hat'), null, {timeout: 8000});
    check(true, '인물을 고치면 장면 표를 다시 받음');
    const [story] = await Promise.all([page.waitForResponse(r => r.url().endsWith('/api/story') && r.request().method() === 'POST'), page.click('#go')]);
    const made = await story.json();
    check(made.cast?.[0]?.lookEn === 'a hedgehog with a blue hat' && made.clips.filter(c => c.prompt.includes('Toto')).every(c => c.prompt.includes('blue hat')), '만들기 요청에 고친 인물, 서버 장면 프롬프트에 반영');
    await page.locator('.mode[data-mode="text"]').click();
    check(await page.locator('#cast-box').isVisible(), '모드를 바꿔도 인물 칸 유지');

    step = '휴대폰';
    const phone = await browser.newPage({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true});
    phone.on('pageerror', e => errors.push(`${step}: ${e.message}`));
    await phone.goto(BASE + '/');
    await phone.locator('#cast-box > summary').click(); await phone.selectOption('#cast-preset', '3'); await phone.selectOption('#cast-preset', '5');
    check(await phone.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '390px 가로 넘침 없음');
    if (process.env.H3_E2E_OUT) await phone.locator('#cast-box').screenshot({path: path.join(process.env.H3_E2E_OUT, 'video-maker-cast-390.png')});
    check(errors.length === 0, '페이지 오류 없음 ' + errors.join(' | '));
    console.log('인물 설정 확인 끝');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
