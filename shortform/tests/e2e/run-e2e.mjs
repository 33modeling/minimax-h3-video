// 웹 e2e: 빌드 결과를 vite preview 로 띄우고 헤드리스 크롬(google-chrome)으로 실제 화면을 끝까지 돌린다.
// 결과 영상은 ffprobe 로 해상도·fps·길이·오디오를 확인하고, 확인용 프레임은 .tmp/e2e/ 에 남긴다.
// AI 서버·Claude 는 tests/e2e/fake-servers.mjs 의 가짜 서버로 대신한다.
// 사용: npm run build && npm run e2e  [-- --only templates,phone,...]
import { spawn, execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';
import { startH3video, startSglang, startAnthropic, jsonReply } from './fake-servers.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const OUT = join(ROOT, '.tmp/e2e');
const MEDIA = join(ROOT, '.tmp/media');
const arg = (name, def) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : def;
};
const ONLY = arg('only', '');
const PORT = Number(arg('port', 4290));
const CHROME = process.env.CHROME || '/usr/bin/google-chrome';
const VP = { desktop: { width: 1280, height: 900 }, phone: { width: 390, height: 844 }, narrow: { width: 320, height: 640 } };
const media = (...names) => names.map((n) => join(MEDIA, n));

mkdirSync(OUT, { recursive: true });
execFileSync('bash', [join(ROOT, 'tests/fixtures/make_media.sh'), MEDIA], { stdio: 'ignore' });
const GEN = join(MEDIA, 'gen.mp4');
if (!existsSync(GEN)) {
  execFileSync('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=orange:s=432x768:r=24:d=4,drawbox=x=116:y=284:w=200:h=200:color=black:t=fill',
    '-f', 'lavfi', '-i', 'sine=f=523:r=32000:d=4', '-ac', '2', '-shortest', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', GEN]);
}
const genMp4 = readFileSync(GEN);
if (!existsSync(join(ROOT, 'dist/index.html'))) execFileSync('npx', ['vite', 'build'], { cwd: ROOT, stdio: 'inherit' });

// vite preview 는 npx 아래 손자 프로세스로 뜬다 → 프로세스 그룹째 끈다
const server = spawn('npx', ['vite', 'preview', '--port', String(PORT), '--strictPort'], {
  cwd: ROOT,
  detached: true,
  stdio: ['ignore', 'pipe', 'pipe'],
  env: { ...process.env, NO_COLOR: '1', FORCE_COLOR: '0' },
});
const killServer = () => {
  try {
    process.kill(-server.pid, 'SIGTERM');
  } catch {
    /* 이미 끝남 */
  }
};
process.on('exit', killServer);
await new Promise((res, rej) => {
  const t = setTimeout(() => rej(new Error('preview 서버가 뜨지 않음')), 20000);
  server.stdout.on('data', (d) => {
    if (String(d).replace(/\x1b\[[0-9;]*m/g, '').includes(`:${PORT}`)) {
      clearTimeout(t);
      res();
    }
  });
});
const BASE = `http://localhost:${PORT}/`;

const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
const failures = [];
const results = [];
const check = (ok, msg) => {
  if (!ok) failures.push(msg);
  return ok;
};

function probe(file) {
  const j = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_type,codec_name,width,height,r_frame_rate:format=duration', '-of', 'json', file]).toString());
  const v = j.streams.find((s) => s.codec_type === 'video') || {};
  const a = j.streams.find((s) => s.codec_type === 'audio');
  const [fn, fd] = String(v.r_frame_rate || '0/1').split('/').map(Number);
  return { w: v.width, h: v.height, vcodec: v.codec_name, acodec: a && a.codec_name, fps: Math.round((fn / fd) * 100) / 100, dur: Number(j.format.duration) };
}

async function newPage(tag, { vp = 'desktop', query = '', tour = false, allow = [] } = {}) {
  const ctx = await browser.newContext({ viewport: VP[vp], acceptDownloads: true, deviceScaleFactor: 1 });
  if (!tour) await ctx.addInitScript(() => localStorage.setItem('shorts.tourSeen.v1', '1'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => {
    if (m.type() === 'error' && !allow.some((a) => m.text().includes(a))) errors.push(m.text());
  });
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  await page.goto(BASE + query);
  return {
    page,
    done: async () => {
      check(errors.length === 0, `${tag}: 콘솔 오류 ${errors.length}개 — ${errors.slice(0, 3).join(' | ')}`);
      await ctx.close();
    },
  };
}

async function loadJob(page, tag, job, files = []) {
  const p = join(OUT, `job-${tag}.json`);
  writeFileSync(p, JSON.stringify(job, null, 2));
  await page.setInputFiles('#jsonFile', p);
  if (files.length) await page.setInputFiles('#mediaFiles', files);
}

async function waitReady(page, tag) {
  try {
    await page.waitForFunction(() => !document.getElementById('makeBtn').disabled, null, { timeout: 30000 });
  } catch {
    throw new Error(`${tag}: 만들기 버튼이 켜지지 않음 — ${await page.locator('#messages').innerText()}`);
  }
}

async function makeAndDownload(page, tag, timeout = 180000) {
  const t0 = Date.now();
  const [dl] = await Promise.all([
    page.waitForEvent('download', { timeout }).catch(async () => {
      const st = await page.evaluate(() => [document.getElementById('progressText').textContent, document.getElementById('messages').innerText, document.getElementById('failText').textContent]);
      throw new Error(`${tag}: 다운로드 없음 — ${st.join(' | ')}`);
    }),
    page.click('#makeBtn'),
  ]);
  const file = join(OUT, `${tag}.${dl.suggestedFilename().split('.').pop()}`);
  await dl.saveAs(file);
  const info = probe(file);
  results.push(`${tag}: ${info.vcodec} ${info.w}x${info.h} ${info.fps}fps + ${info.acodec || '오디오 없음'} · ${info.dur.toFixed(2)}초 · ${((Date.now() - t0) / 1000).toFixed(1)}초`);
  return { file, info };
}

const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const frame = (file, t, out) => execFileSync('ffmpeg', ['-y', '-v', 'error', '-ss', String(t), '-i', file, '-frames:v', '1', '-vf', 'scale=240:-2', out]);

function composeJob(template, extra = {}) {
  const job = {
    template,
    fit: 'blur',
    title: `${template} 템플릿 확인`,
    captions: ['첫 번째 자막입니다', { text: '두 번째 자막', start: 3, end: 5 }, '끝까지 보세요'],
    bgm: 'bgm.m4a',
    bgm_volume: 0.25,
    output: `e2e-${template}.mp4`,
    ...extra,
  };
  if (template === 'montage') job.sources = ['src1.mp4', { path: 'src2.mp4', start: 0.5, end: 2.5 }, 'src3.mp4'];
  else {
    job.base = 'base.mp4';
    job.sources = ['src1.mp4', { path: 'src2.mp4', start: 0.5, end: 2.5 }];
  }
  return job;
}
const composeFiles = (template) => (template === 'montage' ? media('src1.mp4', 'src2.mp4', 'src3.mp4', 'bgm.m4a') : media('base.mp4', 'src1.mp4', 'src2.mp4', 'bgm.m4a'));

const scenarios = {
  // 템플릿 4종(데스크톱): MP4 H.264+AAC 720x1280, 3.5초 프레임을 한 줄로 모아 둔다
  async templates() {
    const frames = [];
    for (const t of ['cutaway', 'split', 'pip', 'montage']) {
      const { page, done } = await newPage(`templates-${t}`);
      await loadJob(page, t, composeJob(t), composeFiles(t));
      await waitReady(page, t);
      const { file, info } = await makeAndDownload(page, `desktop-${t}`);
      check(info.vcodec === 'h264' && info.acodec === 'aac' && info.w === 720 && info.h === 1280 && Math.abs(info.dur - 8) < 0.2, `${t}: 결과 형식 이상 ${JSON.stringify(info)}`);
      const f = join(OUT, `f-${t}.png`);
      frame(file, 3.5, f);
      frames.push(f);
      check((await page.locator('#statusBox li.done').count()) >= 4, `${t}: 단계 표시에 완료 체크가 없음`);
      if (t === 'cutaway') await page.screenshot({ path: join(OUT, 'desktop-done.png') });
      await done();
    }
    execFileSync('ffmpeg', ['-y', '-v', 'error', ...frames.flatMap((f) => ['-i', f]), '-filter_complex', `hstack=${frames.length}`, join(OUT, 'templates-strip.png')]);
  },

  // 폰 390: 업로드→만들기→다운로드 + 가로 넘침. 320: 패널을 다 연 상태에서 넘침
  async phone() {
    const { page, done } = await newPage('phone', { vp: 'phone' });
    await loadJob(page, 'phone', composeJob('cutaway'), composeFiles('cutaway'));
    await waitReady(page, 'phone');
    const { info } = await makeAndDownload(page, 'phone-cutaway');
    check(info.w === 720 && info.h === 1280 && info.acodec, `phone: 결과 이상 ${JSON.stringify(info)}`);
    await page.evaluate(() => document.querySelectorAll('details').forEach((d) => (d.open = true)));
    check((await overflow(page)) <= 0, `phone 390: 가로 넘침 ${await overflow(page)}px`);
    await page.screenshot({ path: join(OUT, 'phone-done.png'), fullPage: true });
    await done();
    const n = await newPage('narrow', { vp: 'narrow' });
    await loadJob(n.page, 'narrow', composeJob('pip'), composeFiles('pip'));
    await waitReady(n.page, 'narrow');
    await n.page.evaluate(() => document.querySelectorAll('details').forEach((d) => (d.open = true)));
    await n.page.selectOption('#setResolution', 'custom');
    await n.page.selectOption('#setFit', 'crop');
    await n.page.check('input[name=aiMode][value=sglang]');
    await n.page.waitForTimeout(200);
    check((await overflow(n.page)) <= 0, `narrow 320: 가로 넘침 ${await overflow(n.page)}px`);
    await n.done();
  },

  // 해상도 프리셋·직접 입력 + fps·품질 선택이 JSON 과 결과에 반영되는지
  async presets() {
    const { page, done } = await newPage('presets');
    await loadJob(page, 'presets', composeJob('split', { output: 'square.mp4' }), composeFiles('split'));
    await waitReady(page, 'presets');
    await page.selectOption('#setResolution', '1080x1080');
    await page.selectOption('#setFps', '24');
    await page.selectOption('#setQuality', 'low');
    await waitReady(page, 'presets');
    const txt = await page.inputValue('#jsonText');
    check(/"resolution": "1080x1080"/.test(txt) && /"fps": 24/.test(txt) && /"quality": "low"/.test(txt), 'presets: 화면 설정이 JSON 에 안 들어감');
    const a = await makeAndDownload(page, 'preset-1080x1080');
    check(a.info.w === 1080 && a.info.h === 1080 && Math.abs(a.info.fps - 24) < 0.1, `presets: 1080x1080@24 아님 ${JSON.stringify(a.info)}`);
    await page.selectOption('#setResolution', 'custom');
    await page.fill('#setResolutionCustom', '600 x 1000');
    await page.press('#setResolutionCustom', 'Enter');
    await page.locator('#setFps').focus();
    await waitReady(page, 'presets-custom');
    const b = await makeAndDownload(page, 'preset-600x1000');
    check(b.info.w === 600 && b.info.h === 1000, `presets: 직접 입력 600x1000 아님 ${JSON.stringify(b.info)}`);
    await page.selectOption('#setResolution', 'custom');
    await page.fill('#setResolutionCustom', '541x960');
    await page.press('#setResolutionCustom', 'Enter');
    await page.locator('#setFps').focus();
    await page.waitForTimeout(300);
    check(/짝수/.test(await page.locator('#messages').innerText()), 'presets: 홀수 해상도 오류 문구 없음');
    await done();
  },

  // 취소 버튼: 인코딩 중 취소 → 다운로드 없음, 다시 만들 수 있음
  async cancel() {
    const { page, done } = await newPage('cancel');
    await loadJob(page, 'cancel', composeJob('cutaway', { resolution: '1080x1920' }), composeFiles('cutaway'));
    await waitReady(page, 'cancel');
    let downloaded = false;
    page.on('download', () => (downloaded = true));
    await page.click('#makeBtn');
    await page.waitForFunction(() => /프레임/.test(document.getElementById('progressText').textContent), null, { timeout: 30000 });
    await page.click('#cancelBtn');
    await page.waitForFunction(() => !document.getElementById('makeBtn').disabled, null, { timeout: 15000 });
    await page.waitForTimeout(500);
    const msg = await page.locator('#messages').innerText();
    check(!downloaded && /취소/.test(msg), `cancel: 취소가 안 됨 (다운로드 ${downloaded}, ${msg})`);
    await done();
  },

  // 잘못된 JSON → 한국어 오류
  async invalid() {
    const { page, done } = await newPage('invalid');
    await page.click('#jsonDetails summary');
    await page.fill('#jsonText', '{ "base": "base.mp4", ');
    await page.waitForTimeout(700);
    check(/JSON 문법 오류/.test(await page.locator('#messages').innerText()), 'invalid: 문법 오류 문구 없음');
    await page.fill('#jsonText', '{ "base": "base.mp4", "template": "zoom", "tittle": "x" }');
    await page.waitForTimeout(700);
    const m = await page.locator('#messages').innerText();
    check(/중 하나여야 합니다/.test(m) && /혹시 'title'/.test(m), `invalid: 스키마 오류 문구 이상 — ${m}`);
    await page.fill('#jsonText', '{ "base": "base.mp4" }');
    await page.waitForTimeout(700);
    check(/파일 칸 2에서 함께 골라/.test(await page.locator('#messages').innerText()), 'invalid: 빠진 파일 안내 없음');
    await done();
  },

  // 설정 내보내기 → 새 화면에서 불러오기 왕복
  async roundtrip() {
    const a = await newPage('roundtrip-a');
    await loadJob(a.page, 'roundtrip', composeJob('cutaway'), composeFiles('cutaway'));
    await waitReady(a.page, 'roundtrip');
    await a.page.selectOption('#setTemplate', 'pip');
    await a.page.selectOption('#setFit', 'crop');
    await a.page.selectOption('#setResolution', '1080x1350');
    const [dl] = await Promise.all([a.page.waitForEvent('download'), a.page.click('#exportBtn')]);
    const p = join(OUT, 'exported.json');
    await dl.saveAs(p);
    const ex = JSON.parse(readFileSync(p, 'utf8'));
    check(ex.template === 'pip' && ex.fit === 'crop' && ex.resolution === '1080x1350' && ex.base === 'base.mp4' && ex.captions.length === 3, `roundtrip: 내보낸 JSON 이상 ${JSON.stringify(ex).slice(0, 200)}`);
    await a.done();
    const b = await newPage('roundtrip-b');
    await b.page.setInputFiles('#importFile', p);
    await b.page.waitForTimeout(300);
    const v = await b.page.evaluate(() => [document.getElementById('setTemplate').value, document.getElementById('setFit').value, document.getElementById('setResolution').value]);
    check(v.join() === 'pip,crop,1080x1350', `roundtrip: 불러온 설정 이상 ${v}`);
    await b.done();
  },

  // AI: h3video 웹 서버(진행률 있음) → 생성 → 합성 → 다운로드, 같은 명세 다시 만들기는 생성 재사용
  async ai_h3video() {
    const fake = await startH3video(genMp4);
    const { page, done } = await newPage('ai-h3');
    const job = { prompt: 'A cat jumps over a fence', duration: 4, ratio: '9:16', title: 'AI 고양이', captions: ['노을', '점프!'], backend: 'h3video', server: fake.url, poll: 0.2, output: 'ai-cat.mp4' };
    await loadJob(page, 'ai-h3', job);
    await waitReady(page, 'ai-h3');
    await page.evaluate(() => {
      window.__seen = new Set();
      new MutationObserver(() => {
        document.querySelectorAll('#statusBox li.now .lbl').forEach((x) => window.__seen.add(x.textContent));
        if (document.querySelector('.sc-bar:not(.indeterminate) > div[style*="40%"]')) window.__seen.add('bar40');
        if (/⏳ \d+% 생성 중/.test(document.title)) window.__seen.add('title');
      }).observe(document.getElementById('statusBox'), { subtree: true, childList: true, characterData: true, attributes: true });
    });
    const { info } = await makeAndDownload(page, 'ai-h3video');
    check(info.w === 720 && info.h === 1280 && info.acodec, `ai_h3video: 결과 이상 ${JSON.stringify(info)}`);
    const seen = await page.evaluate(() => [...window.__seen]);
    const sub = fake.log.find((x) => x.kind === 'submit');
    const f = Object.fromEntries(sub.fields.map((x) => [x.name, x.value]));
    check(f.prompt === job.prompt && f.seconds === '4' && f.aspect_ratio === '9:16', `ai_h3video: 요청 필드 이상 ${JSON.stringify(f)}`);
    check(seen.some((s) => s.startsWith('대기열')) && seen.some((s) => s.startsWith('생성 중')) && seen.includes('bar40') && seen.includes('title'), `ai_h3video: 단계·진행률 표시 이상 ${seen}`);
    check((await page.locator('.sc-id code').innerText()) === 'job1', 'ai_h3video: 작업 ID 표시 없음');
    check(/완료/.test(await page.locator('.scene-card .badge').innerText()), 'ai_h3video: 장면 카드가 완료로 안 바뀜');
    await page.screenshot({ path: join(OUT, 'ai-done.png') });
    const before = fake.log.filter((x) => x.kind === 'submit').length;
    await makeAndDownload(page, 'ai-h3video-again');
    check(fake.log.filter((x) => x.kind === 'submit').length === before, 'ai_h3video: 다시 만들 때 생성을 또 요청함');
    await done();
    fake.close();
  },

  // JSON 한번에: 동화책 콘티 JSON(숏폼 명세 아님) + 쪽 그림 → 장면 수·길이를 알아서 → 쪽마다 첫 프레임으로 생성 → 합성
  async ai_story() {
    const fake = await startH3video(genMp4);
    const { page, done } = await newPage('ai-story');
    for (const [n, c] of [['page-01', 'red'], ['page-02', 'green'], ['page-03', 'blue'], ['extra-99', 'white']]) {
      const f = join(MEDIA, `${n}.png`);
      if (!existsSync(f)) execFileSync('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', `color=c=${c}:s=320x240`, '-frames:v', '1', f]);
    }
    await page.locator('#aiPanel summary').click();
    await page.fill('#aiServer', fake.url);
    await page.locator('#aiServer').dispatchEvent('change');
    const conti = { guide: 'g', opts: { ratio: '4:3' }, book: { title: '토토의 우산', style: { prompt: 'watercolor' }, characters: [{ name: 'Toto', prompt: 'a hedgehog' }],
      cover: { scene: 'Toto waves' }, pages: [
        { page: 1, text: '숲 가장자리에 아기 고슴도치 토토가 살았어요.\n토토는 늘 혼자 놀았어요.', shot: 'wide', characters: ['Toto'], scene: 'Toto sits alone' },
        { page: 2, text: '같이 쓰자!', characters: ['Toto'], scene: 'Toto smiles' },
        { page: 3, text: '', characters: [], scene: 'A rainbow' }] } };
    await loadJob(page, 'ai-story', conti, media('extra-99.png', 'page-03.png', 'page-01.png', 'page-02.png'));
    await waitReady(page, 'ai-story');
    const msg = await page.locator('#messages').innerText();
    check(/동화책 콘티 → 숏폼: 토토의 우산 · 장면 3개 · 합계 21초\(쪽 글 읽는 시간\) · 그림 3장 연결 · 쓰지 않는 그림: extra-99\.png/.test(msg), `ai_story: 안내 이상 ${msg}`);
    const spec = JSON.parse(await page.locator('#jsonText').inputValue());
    check(spec.scenes.map((x) => `${x.image}:${x.duration}`).join(',') === 'page-01.png:10,page-02.png:5,page-03.png:6' && spec.ratio === '4:3', `ai_story: 명세 이상 ${JSON.stringify(spec.scenes)}`);
    check(!/extra-99/.test(await page.locator('#fileList').innerText()), 'ai_story: 안 쓰는 그림이 파일 목록(참조)에 남음');
    const list = await page.locator('#fileList').innerText();
    check(/page-01\.png\s*장면 1 첫 프레임/.test(list) && /page-03\.png\s*장면 3 첫 프레임/.test(list), `ai_story: 파일 목록 역할 이상 ${list}`);
    await page.screenshot({ path: join(OUT, 'ai-story-ready.png') });
    const { info } = await makeAndDownload(page, 'ai-story', 240000);
    check(info.w === 720 && info.h === 1280 && info.acodec, `ai_story: 결과 이상 ${JSON.stringify(info)}`);
    const subs = fake.log.filter((x) => x.kind === 'submit').map((x) => Object.fromEntries(x.fields.map((f) => [f.name, f.filename || f.value])));
    check(subs.map((f) => `${f.first_image}:${f.seconds}:${f.aspect_ratio}`).join(',') === 'page-01.png:10:4:3,page-02.png:5:4:3,page-03.png:6:4:3', `ai_story: 요청 이상 ${JSON.stringify(subs.map((f) => [f.first_image, f.seconds, f.aspect_ratio]))}`);
    check(subs.every((f) => !f.ref_images) && /<d>\[Korean\] 숲 가장자리에/.test(subs[0].prompt), 'ai_story: 참조가 섞이거나 내레이션이 없음');
    await done();
    fake.close();
  },

  // AI: 진행률 없음 + 상태 조회 503 한 번(재시도 표시) → 결국 완료
  async ai_flaky() {
    const fake = await startH3video(genMp4);
    const { page, done } = await newPage('ai-flaky', { allow: ['503'] });
    await loadJob(page, 'ai-flaky', { prompt: 'NOPROG FLAKY dog runs', duration: 4, backend: 'h3video', server: fake.url, poll: 0.2 });
    await waitReady(page, 'ai-flaky');
    await page.evaluate(() => {
      window.__seen = new Set();
      new MutationObserver(() => {
        if (document.querySelector('.sc-bar.indeterminate')) window.__seen.add('indeterminate');
        const r = document.querySelector('.sc-retry')?.textContent;
        if (r) window.__seen.add(r);
      }).observe(document.getElementById('statusBox'), { subtree: true, childList: true, characterData: true, attributes: true });
    });
    await makeAndDownload(page, 'ai-flaky');
    const seen = await page.evaluate(() => [...window.__seen]);
    check(seen.includes('indeterminate') && seen.includes('재시도 중(1/5)'), `ai_flaky: 불확정 막대·재시도 표시 없음 ${seen}`);
    await done();
    fake.close();
  },

  // AI: 서버 생성 실패 → 한국어 설명 + 다시 시도 버튼
  async ai_fail() {
    const fake = await startH3video(genMp4);
    const { page, done } = await newPage('ai-fail');
    await loadJob(page, 'ai-fail', { prompt: 'FAIL please', duration: 4, backend: 'h3video', server: fake.url, poll: 0.2 });
    await waitReady(page, 'ai-fail');
    await page.click('#makeBtn');
    await page.waitForSelector('#failBox:not([hidden])', { timeout: 20000 });
    const t = await page.locator('#failText').innerText();
    check(/CUDA out of memory/.test(t) && /다시 시도하세요/.test(t), `ai_fail: 실패 설명 이상 — ${t}`);
    check((await page.locator('#statusBox li.fail').count()) === 1 && (await page.locator('#retryBtn').isVisible()), 'ai_fail: 실패 단계·다시 시도 버튼 없음');
    check(/실패/.test(await page.title()), 'ai_fail: 문서 제목에 실패 표시 없음');
    await done();
    fake.close();
  },

  // AI: SGLang 직접 — 소스 있으면 ref2va 주소로(data: URI 참조), 없으면 fl2va 주소로. 취소하면 DELETE.
  async ai_sglang() {
    const fl = await startSglang(genMp4);
    const ref = await startSglang(genMp4);
    const { page, done } = await newPage('ai-sglang');
    await loadJob(page, 'ai-sg-ref', { prompt: 'Use <Video 1> as motion reference, neon rooftop', sources: ['src1.mp4'], duration: 4, backend: 'sglang', server: fl.url, ref_server: ref.url, poll: 0.2, gen_size: 576 }, media('src1.mp4'));
    await waitReady(page, 'ai-sg-ref');
    await makeAndDownload(page, 'ai-sglang-ref');
    const sub = ref.log.find((x) => x.kind === 'submit');
    check(sub && sub.body.task === 'ref2va' && sub.body.conditions[0].type === 'video' && sub.body.conditions[0].uri.startsWith('data:video/mp4;base64') && sub.body.target.short_edge === 576 && !fl.log.length,
      `ai_sglang: ref2va 라우팅·요청 이상 ${JSON.stringify(sub)} / fl=${fl.log.length}`);
    await page.setInputFiles('#mediaFiles', []);
    await loadJob(page, 'ai-sg-t2v', { prompt: 'a quiet lake at dawn', duration: 4, backend: 'sglang', server: fl.url, ref_server: ref.url, poll: 0.5 });
    await waitReady(page, 'ai-sg-t2v');
    await page.click('#makeBtn');
    await page.waitForSelector('.sc-id:not([hidden])', { timeout: 10000 });
    await page.click('#cancelBtn');
    await page.waitForFunction(() => !document.getElementById('makeBtn').disabled, null, { timeout: 10000 });
    await page.waitForTimeout(300);
    const s2 = fl.log.find((x) => x.kind === 'submit');
    check(s2 && s2.body.task === 't2va' && s2.body.conditions.length === 0, `ai_sglang: t2va 요청 이상 ${JSON.stringify(s2)}`);
    check(fl.log.some((x) => x.kind === 'delete'), 'ai_sglang: 취소 때 DELETE 를 안 보냄');
    await done();
    fl.close();
    ref.close();
  },

  // AI: JSON 에 server 만 있고 backend 가 없으면(examples/scenes.json) CLI 처럼 서버에 물어 판별 → SGLang 이면 /v1/videos
  async ai_auto() {
    const fl = await startSglang(genMp4);
    // 판별용 GET /api/spec 의 404 는 브라우저가 콘솔에 남긴다(SGLang 에는 그 경로가 없음 — ai_flaky 의 503 과 같은 경우)
    const { page, done } = await newPage('ai-auto', { allow: ['404'] });
    await loadJob(page, 'ai-auto', { scenes: [{ prompt: 'Coffee pours into a cup', duration: 4 }], ratio: '9:16', server: fl.url, poll: 0.2, output: 'auto.mp4' });
    await waitReady(page, 'ai-auto');
    await makeAndDownload(page, 'ai-auto');
    check(fl.log.some((x) => x.kind === 'submit' && x.body.task === 't2va'), `ai_auto: SGLang 에 요청이 안 감 ${JSON.stringify(fl.log)}`);
    await done();
    fl.close();
  },

  // Claude 기획: 가짜 엔드포인트, 1차 응답이 검증 실패 → 오류를 붙여 1회 재요청 → 성공 (구조화 출력, CLI 와 같은 요청)
  async claude() {
    const bad = jsonReply({ prompt: 'x', template: 'zoom', captions: ['a'] });
    const good = jsonReply({ scenes: [{ prompt: 'Coffee pours into a cup, morning light', duration: 5 }], ratio: '9:16', title: '아침 커피', captions: ['커피를 내리고'], template: 'montage' });
    const fake = await startAnthropic([bad, good]);
    const { page, done } = await newPage('claude', { query: `?anthropic_base=${encodeURIComponent(fake.url)}` });
    await page.click('#claudePanel summary');
    await page.fill('#idea', '아침 커피 루틴 15초');
    await page.fill('#apiKey', 'sk-ant-test-123');
    await page.setInputFiles('#mediaFiles', media('src1.mp4'));
    await page.click('#planBtn');
    await page.waitForFunction(() => /채웠습니다|실패|오류|연결/.test(document.getElementById('planOut').textContent), null, { timeout: 30000 });
    const out = await page.locator('#planOut').innerText();
    const txt = await page.inputValue('#jsonText');
    check(/시도 2회/.test(out) && /아침 커피/.test(txt), `claude: 결과 이상 — ${out}`);
    const [r1, r2] = fake.log;
    check(r1 && r1.headers['anthropic-dangerous-direct-browser-access'] === 'true' && r1.headers['x-api-key'] === 'sk-ant-test-123' && r1.body.model === 'claude-opus-5-5' &&
        r1.body.output_config.format.type === 'json_schema' && !r1.body.tools && !r1.body.tool_choice && r1.body.fallbacks === 'default' &&
        r1.headers['anthropic-beta'] === 'server-side-fallback-2026-07-01',
      'claude: 요청 헤더·모델·구조화 출력 이상');
    check(r1 && r1.body.messages[0].content.some((b) => b.type === 'image'), 'claude: 소스 프레임 이미지가 안 감');
    const last = r2 && r2.body.messages.at(-1);
    check(last && last.role === 'user' && last.content[0].type === 'text' && /검증에 실패/.test(last.content[0].text) && r2.body.messages.at(-2).role === 'assistant',
      'claude: 재요청에 오류 문장이 안 붙음');
    check((await page.evaluate(() => localStorage.getItem('shorts.anthropicKey'))) === 'sk-ant-test-123', 'claude: 키가 localStorage 에 저장 안 됨');
    await page.click('#keyClear');
    check((await page.evaluate(() => localStorage.getItem('shorts.anthropicKey'))) === null && (await page.inputValue('#apiKey')) === '', 'claude: 키 지우기 안 됨');
    await done();
    fake.close();
  },

  // 입력 칸 3·4: 첫 프레임 이미지 → JSON image, 참조 이미지·영상 → JSON sources (CLI --image / --ref 와 같음)
  async slots() {
    const { page, done } = await newPage('slots');
    await page.click('#jsonDetails summary');
    await page.fill('#jsonText', JSON.stringify({ prompt: 'a cat jumps over a fence', duration: 6 }));
    await page.dispatchEvent('#jsonText', 'input');
    await page.waitForTimeout(600);
    const [img] = media('first.png');
    await page.setInputFiles('#firstImage', img);
    await page.setInputFiles('#refFiles', media('src1.mp4', 'src2.mp4'));
    await page.waitForTimeout(400);
    const j = JSON.parse(await page.inputValue('#jsonText'));
    check(j.image === 'first.png', `slots: JSON image ${j.image}`);
    check(JSON.stringify(j.sources) === JSON.stringify(['src1.mp4', 'src2.mp4']), `slots: JSON sources ${JSON.stringify(j.sources)}`);
    const roles = await page.$$eval('#fileList li', (ls) => ls.map((l) => l.textContent));
    check(roles.some((r) => /src1\.mp4.*AI 참조/.test(r)), `slots: 파일 목록 역할 ${roles.join(' / ')}`);
    await done();
  },

  // 둘러보기(320 폭): 말풍선이 화면 안, 키보드 조작, Esc, 다시 안 뜸 + 도움말 예시 불러오기
  async tour() {
    const { page, done } = await newPage('tour', { vp: 'narrow', tour: true });
    await page.waitForSelector('.tour-box', { timeout: 5000 });
    for (let i = 0; i < 7; i++) {
      await page.waitForTimeout(80);
      const r = await page.evaluate(() => {
        const b = document.querySelector('.tour-box').getBoundingClientRect();
        return { l: b.left, r: b.right, t: b.top, b: b.bottom, vw: document.documentElement.clientWidth, vh: innerHeight, n: document.querySelector('.tour-count').textContent };
      });
      check(r.l >= 0 && r.r <= r.vw && r.t >= 0 && r.b <= r.vh, `tour: ${r.n} 말풍선이 화면 밖 ${JSON.stringify(r)}`);
      if (i === 0) await page.screenshot({ path: join(OUT, 'tour-320.png') });
      if (i < 6) await page.keyboard.press('ArrowRight');
    }
    await page.keyboard.press('Escape');
    check((await page.locator('.tour-box').count()) === 0, 'tour: Esc 로 안 닫힘');
    await page.reload();
    await page.waitForTimeout(800);
    check((await page.locator('.tour-box').count()) === 0, 'tour: 한 번 본 뒤에도 다시 뜸');
    await page.click('#helpBtn');
    await page.locator('#helpExamples .example').nth(1).click();
    await page.waitForTimeout(300);
    check(/tabby cat/.test(await page.inputValue('#jsonText')), 'tour: 도움말 예시 불러오기 안 됨');
    check((await overflow(page)) <= 0, `tour: 320 가로 넘침 ${await overflow(page)}px`);
    await done();
  },

  // WebCodecs 없는 브라우저 대체 경로(강제): MediaRecorder 실시간 녹화
  async recorder() {
    const { page, done } = await newPage('recorder', { query: '?engine=recorder' });
    await loadJob(page, 'recorder', composeJob('cutaway', { output: 'rec.mp4' }), composeFiles('cutaway'));
    await waitReady(page, 'recorder');
    check(/실시간 녹화/.test(await page.locator('#engineNote').innerText()), 'recorder: 대체 경로 안내 문구 없음');
    const { info } = await makeAndDownload(page, 'recorder-cutaway', 60000);
    check(info.w === 720 && info.h === 1280 && info.acodec && Math.abs(info.dur - 8) < 0.5, `recorder: 결과 이상 ${JSON.stringify(info)}`);
    await done();
  },
};

try {
  for (const [name, fn] of Object.entries(scenarios)) {
    if (ONLY && !ONLY.split(',').includes(name)) continue;
    const t0 = Date.now();
    const before = failures.length;
    try {
      await fn();
    } catch (e) {
      failures.push(`${name}: ${e.message.split('\n')[0]}`);
    }
    console.log(`${failures.length > before ? '✗' : '·'} ${name} (${((Date.now() - t0) / 1000).toFixed(1)}초)`);
  }
} finally {
  await browser.close();
  killServer();
}
console.log(results.join('\n'));
if (failures.length) {
  console.error(`실패 ${failures.length}건:\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('e2e 통과');
process.exit(0);
