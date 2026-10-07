// 웹 e2e: 빌드 결과를 vite preview 로 띄우고, 헤드리스 크롬에서 파일 2칸 → 만들기 → 다운로드까지 돌린다.
// 결과는 ffprobe 로 해상도·길이·오디오 트랙을 확인하고, 프레임 몇 장을 PNG 로 뽑아 둔다(.tmp/e2e/).
// 사용: npm run build && node tests/e2e/run-e2e.mjs [--templates cutaway,split,pip,montage] [--viewports desktop,phone] [--engine recorder]
import { spawn, execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const OUT = join(ROOT, '.tmp/e2e');
const MEDIA = join(ROOT, '.tmp/media');
const arg = (name, def) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : def;
};
const TEMPLATES = arg('templates', 'cutaway,split,pip,montage').split(',');
const VIEWPORTS = arg('viewports', 'desktop,phone').split(',');
const ENGINE = arg('engine', '');
const PORT = Number(arg('port', 4290));
const CHROME = process.env.CHROME || '/usr/bin/google-chrome';
const SIZES = { desktop: { width: 1280, height: 900 }, phone: { width: 390, height: 844 }, narrow: { width: 320, height: 640 } };

mkdirSync(OUT, { recursive: true });
execFileSync('bash', [join(ROOT, 'tests/fixtures/make_media.sh'), MEDIA], { stdio: 'inherit' });
if (!existsSync(join(ROOT, 'dist/index.html'))) execFileSync('npx', ['vite', 'build'], { cwd: ROOT, stdio: 'inherit' });

function jobFor(template) {
  const job = {
    template,
    fit: 'blur',
    title: `${template} 템플릿 확인`,
    captions: ['첫 번째 자막입니다', { text: '두 번째 자막', start: 3, end: 5 }, '끝까지 보세요'],
    bgm: 'bgm.m4a',
    bgm_volume: 0.25,
    output: `e2e-${template}.mp4`,
  };
  if (template === 'montage') job.sources = ['src1.mp4', { path: 'src2.mp4', start: 0.5, end: 2.5 }, 'src3.mp4'];
  else {
    job.base = 'base.mp4';
    job.sources = ['src1.mp4', { path: 'src2.mp4', start: 0.5, end: 2.5 }];
  }
  return job;
}

const probe = (file) =>
  JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_type,codec_name,width,height:format=duration', '-of', 'json', file]).toString());

const server = spawn('npx', ['vite', 'preview', '--port', String(PORT), '--strictPort'], { cwd: ROOT, stdio: ['ignore', 'pipe', 'inherit'] });
await new Promise((res, rej) => {
  const t = setTimeout(() => rej(new Error('preview 서버가 뜨지 않음')), 20000);
  server.stdout.on('data', (d) => {
    if (String(d).includes(String(PORT))) {
      clearTimeout(t);
      res();
    }
  });
});

const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
const failures = [];
try {
  for (const vp of VIEWPORTS) {
    for (const template of TEMPLATES) {
      const tag = `${vp}-${template}${ENGINE ? '-' + ENGINE : ''}`;
      const ctx = await browser.newContext({ viewport: SIZES[vp], acceptDownloads: true, deviceScaleFactor: 1 });
      const page = await ctx.newPage();
      const logs = [];
      page.on('console', (m) => logs.push(`${m.type()}: ${m.text()}`));
      page.on('pageerror', (e) => logs.push(`pageerror: ${e.message}`));
      const url = `http://localhost:${PORT}/${ENGINE ? `?engine=${ENGINE}` : ''}`;
      await page.goto(url);
      const jobPath = join(OUT, `job-${template}.json`);
      writeFileSync(jobPath, JSON.stringify(jobFor(template), null, 2));
      await page.setInputFiles('#jsonFile', jobPath);
      const media = ['base.mp4', 'src1.mp4', 'src2.mp4', 'src3.mp4', 'bgm.m4a'].map((f) => join(MEDIA, f));
      await page.setInputFiles('#mediaFiles', template === 'montage' ? media.slice(1) : media);
      await page.waitForFunction(() => !document.getElementById('makeBtn').disabled, null, { timeout: 30000 }).catch(async (e) => {
        const msgs = await page.locator('#messages').innerText();
        throw new Error(`${tag}: 만들기 버튼이 켜지지 않음 — ${msgs}\n${logs.join('\n')}`);
      });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      await page.screenshot({ path: join(OUT, `${tag}-ready.png`), fullPage: true });
      const t0 = Date.now();
      const [download] = await Promise.all([page.waitForEvent('download', { timeout: 180000 }), page.click('#makeBtn')]);
      const file = join(OUT, download.suggestedFilename().replace(/^e2e-/, `${tag}-`));
      await download.saveAs(file);
      const secs = ((Date.now() - t0) / 1000).toFixed(1);
      await page.screenshot({ path: join(OUT, `${tag}-done.png`), fullPage: true });
      const info = probe(file);
      const v = info.streams.find((s) => s.codec_type === 'video');
      const a = info.streams.find((s) => s.codec_type === 'audio');
      const dur = Number(info.format.duration);
      const ok = v && v.width === 720 && v.height === 1280 && a && dur > 2;
      console.log(`${ok ? 'OK ' : 'BAD'} ${tag}: ${v?.codec_name} ${v?.width}x${v?.height} + ${a?.codec_name || '오디오 없음'} · ${dur.toFixed(2)}초 · ${secs}초 걸림 · 가로넘침 ${overflow}px → ${file}`);
      if (!ok || overflow > 0) failures.push(tag);
      for (const t of [1, 3.5, Math.max(0.5, dur - 1)]) {
        execFileSync('ffmpeg', ['-y', '-v', 'error', '-ss', String(t), '-i', file, '-frames:v', '1', '-vf', 'scale=360:-2', join(OUT, `${tag}-f${t.toFixed(1)}.png`)]);
      }
      if (logs.some((l) => l.startsWith('pageerror') || l.startsWith('error'))) console.log(logs.join('\n'));
      await ctx.close();
    }
  }
} finally {
  await browser.close();
  server.kill();
}
if (failures.length) {
  console.error(`실패: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('e2e 통과');
