import './style.css';
import { checkSpec, normalizeSpec, composeInputs, baseName } from './core/spec.js';
import { planTimeline, describePlan } from './core/plan.js';
import { matchFiles, fileFor, outputName } from './app/match.js';
import { checkDecodable, StillFrames, SequentialFrames, mixAudio } from './render/media.js';
import { prepareSegments, drawFrame, frameCount } from './render/draw.js';
import { pickEngine, exportVideo, Cancelled } from './render/export.js';
import { EXAMPLE_JOB } from './app/example.js';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const forceEngine = params.get('engine'); // 'recorder' 면 실시간 녹화 경로(테스트용)

const el = {
  jsonFile: $('jsonFile'),
  jsonName: $('jsonName'),
  jsonText: $('jsonText'),
  jsonDetails: $('jsonDetails'),
  mediaFiles: $('mediaFiles'),
  mediaName: $('mediaName'),
  fileList: $('fileList'),
  messages: $('messages'),
  preview: $('preview'),
  previewEmpty: $('previewEmpty'),
  planLine: $('planLine'),
  scrub: $('scrub'),
  scrubTime: $('scrubTime'),
  playBtn: $('playBtn'),
  engineNote: $('engineNote'),
  makeBtn: $('makeBtn'),
  progressBox: $('progressBox'),
  progressBar: $('progressBar'),
  progressText: $('progressText'),
  cancelBtn: $('cancelBtn'),
  resultBox: $('resultBox'),
  resultVideo: $('resultVideo'),
  downloadLink: $('downloadLink'),
  resultMeta: $('resultMeta'),
  exampleBtn: $('exampleBtn'),
};

const state = {
  jsonText: '',
  files: [],
  job: null, // { spec(정규화), plan, segs, fileOfSeg, fileOfAudio }
  mixed: null,
  still: null,
  busy: false,
  playing: null,
  abort: null,
  resultUrl: null,
};

const pctx = el.preview.getContext('2d', { alpha: false });
const scratch = document.createElement('canvas');

// ---------- 메시지 ----------
function setMessages(list) {
  el.messages.replaceChildren(
    ...list.map(({ level, text }) => {
      const p = document.createElement('p');
      p.className = `msg ${level}`;
      p.textContent = text;
      return p;
    }),
  );
}

function fmtSize(n) {
  if (n >= 1 << 20) return `${(n / (1 << 20)).toFixed(1)}MB`;
  return `${Math.max(1, Math.round(n / 1024))}KB`;
}

function renderFileList(match) {
  const items = [];
  for (const f of state.files) {
    const b = baseName(f.name);
    const role = match ? match.roles[b] : null;
    items.push({ name: f.name, meta: fmtSize(f.size), role: role || (match ? '쓰지 않음' : ''), cls: role ? 'ok' : 'idle' });
  }
  for (const m of match ? match.missing : []) items.push({ name: m, meta: '', role: '파일 칸 2에 없음', cls: 'missing' });
  el.fileList.replaceChildren(
    ...items.map((it) => {
      const li = document.createElement('li');
      li.className = it.cls;
      const name = document.createElement('span');
      name.className = 'fname';
      name.textContent = it.name;
      const role = document.createElement('span');
      role.className = 'frole';
      role.textContent = [it.role, it.meta].filter(Boolean).join(' · ');
      li.append(name, role);
      return li;
    }),
  );
}

// ---------- 분석(명세 → 계획) ----------
let seq = 0;

function clearPlan() {
  stopPlay();
  state.job = null;
  state.mixed = null;
  state.still = null;
  el.makeBtn.disabled = true;
  el.scrub.disabled = true;
  el.playBtn.disabled = true;
  el.planLine.textContent = '아직 계획이 없습니다.';
  el.previewEmpty.hidden = false;
  pctx.fillStyle = '#000';
  pctx.fillRect(0, 0, el.preview.width, el.preview.height);
}

async function analyze() {
  const my = ++seq;
  clearPlan();
  if (!state.jsonText.trim()) {
    renderFileList(null);
    setMessages([{ level: 'info', text: '먼저 파일 칸 1에 작업 JSON을 고르세요. 형식이 궁금하면 "예시 JSON 받기"를 누르세요.' }]);
    return;
  }
  let raw;
  try {
    raw = JSON.parse(state.jsonText);
  } catch (e) {
    renderFileList(null);
    setMessages([{ level: 'error', text: `JSON 문법 오류: ${e.message}` }]);
    return;
  }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    setMessages([{ level: 'error', text: 'JSON 최상위는 객체({ ... })여야 합니다' }]);
    return;
  }
  const match = matchFiles(raw, state.files);
  renderFileList(match);
  const { errors, warnings } = checkSpec(match.spec);
  if (errors.length) {
    setMessages(errors.map((text) => ({ level: 'error', text })));
    return;
  }
  const n = normalizeSpec(match.spec);
  if (n.usesAi) {
    setMessages([
      ...warnings.map((text) => ({ level: 'warn', text })),
      { level: 'error', text: '이 JSON에는 prompt(또는 scenes)가 있어 AI 영상 생성이 필요합니다. AI 서버 연결은 다음 판에 들어갑니다. 지금은 base·sources 영상 합성만 됩니다.' },
    ]);
    return;
  }
  if (match.missing.length) {
    setMessages([{ level: 'error', text: `JSON이 가리키는 파일을 파일 칸 2에서 함께 골라 주세요: ${match.missing.join(', ')}` }]);
    return;
  }
  setMessages([{ level: 'info', text: '영상 정보를 읽는 중…' }]);
  const inputs = composeInputs(match.spec);
  const baseFile = inputs.base ? fileFor(state.files, inputs.base.path) : null;
  const clipFiles = inputs.clips.map((c) => fileFor(state.files, c.path));
  const bgmFile = inputs.bgm ? fileFor(state.files, inputs.bgm) : null;
  let probed;
  try {
    const info = async (f) => (await checkDecodable(f)).info;
    probed = {
      base: baseFile ? { media: inputs.base, info: await info(baseFile) } : null,
      clips: await Promise.all(inputs.clips.map(async (c, i) => ({ media: c, info: await info(clipFiles[i]) }))),
      bgm: bgmFile ? { path: inputs.bgm, info: await info(bgmFile) } : null,
    };
    if (probed.base && !probed.base.info.width) throw new Error(`${baseFile.name}: 영상 트랙이 없습니다`);
    if (probed.bgm && !probed.bgm.info.hasAudio) throw new Error(`${bgmFile.name}: 소리 트랙이 없습니다`);
  } catch (e) {
    if (my !== seq) return;
    setMessages([{ level: 'error', text: e.message }]);
    return;
  }
  if (my !== seq) return;
  let plan;
  try {
    plan = planTimeline(n, probed);
  } catch (e) {
    setMessages([{ level: 'error', text: e.message }]);
    return;
  }
  const segs = prepareSegments(plan);
  const fileOfSeg = (s) => (s.kind === 'base' ? baseFile : clipFiles[s.index]);
  const fileOfAudio = (a) => (a.kind === 'base' ? baseFile : a.kind === 'bgm' ? bgmFile : clipFiles[a.index]);
  state.job = { spec: n, plan, segs, fileOfSeg, fileOfAudio };
  const scale = el.preview.width / plan.width;
  state.still = new StillFrames(plan, segs, fileOfSeg, scale);
  const notes = [...new Set([...warnings, ...plan.warnings])];
  setMessages([
    ...notes.map((text) => ({ level: 'warn', text })),
    { level: 'ok', text: `준비됐습니다. "만들기"를 누르면 ${outputName(n, ext())} 파일을 만듭니다.` },
  ]);
  el.planLine.textContent = describePlan(plan);
  el.previewEmpty.hidden = true;
  el.scrub.disabled = false;
  el.playBtn.disabled = false;
  el.makeBtn.disabled = state.busy || !engine || engine.kind === 'none';
  const k0 = Math.round(Math.min(1, plan.duration / 3) * plan.fps);
  el.scrub.value = String(Math.round((k0 / frameCount(plan)) * 1000));
  showStill(k0);
}

// ---------- 미리보기 ----------
let stillBusy = false;
let stillNext = null;

async function showStill(k) {
  const job = state.job;
  if (!job) return;
  el.scrubTime.textContent = `${(k / job.plan.fps).toFixed(1)}초`;
  if (stillBusy) {
    stillNext = k;
    return;
  }
  stillBusy = true;
  try {
    const still = state.still;
    await still.load(k);
    if (state.job === job && !state.playing && !state.busy) {
      drawFrame(pctx, job.plan, job.segs, k, (s) => still.get(s), scratch, el.preview.width / job.plan.width);
    }
  } catch (e) {
    console.warn(e);
  } finally {
    stillBusy = false;
    if (stillNext != null) {
      const n = stillNext;
      stillNext = null;
      showStill(n);
    }
  }
}

function scrubFrame() {
  const job = state.job;
  if (!job) return 0;
  const N = frameCount(job.plan);
  return Math.min(N - 1, Math.round((Number(el.scrub.value) / 1000) * N));
}

async function ensureMix() {
  const job = state.job;
  if (!state.mixed) {
    const notes = [];
    state.mixed = await mixAudio(job.plan, job.fileOfAudio, (t) => notes.push(t));
    if (notes.length) setMessages(notes.map((text) => ({ level: 'warn', text })));
  }
  return state.mixed;
}

function stopPlay() {
  if (state.playing) {
    state.playing.stop = true;
    state.playing.actx?.close().catch(() => {});
    state.playing = null;
  }
  el.playBtn.textContent = '미리보기 재생';
}

async function togglePlay() {
  if (state.playing) {
    stopPlay();
    return;
  }
  const job = state.job;
  if (!job) return;
  const play = { stop: false, actx: null };
  state.playing = play;
  el.playBtn.textContent = '정지';
  const { plan, segs } = job;
  const scale = el.preview.width / plan.width;
  const N = frameCount(plan);
  let k = scrubFrame();
  if (k >= N - 1) k = 0;
  const frames = new SequentialFrames(plan, segs, job.fileOfSeg, scale);
  try {
    const mixed = await ensureMix();
    if (play.stop) return;
    const actx = new AudioContext();
    play.actx = actx;
    const src = new AudioBufferSourceNode(actx, { buffer: mixed });
    src.connect(actx.destination);
    const startAt = actx.currentTime + 0.1;
    const offset = k / plan.fps;
    src.start(startAt, offset);
    for (; k < N && !play.stop; k++) {
      await frames.step(k);
      if (play.stop) break;
      drawFrame(pctx, plan, segs, k, (s) => frames.get(s), scratch, scale);
      el.scrub.value = String(Math.round((k / N) * 1000));
      el.scrubTime.textContent = `${(k / plan.fps).toFixed(1)}초`;
      const due = startAt + (k + 1) / plan.fps - offset;
      const wait = (due - actx.currentTime) * 1000;
      if (wait > 1) await new Promise((r) => setTimeout(r, wait));
    }
  } catch (e) {
    console.warn(e);
  } finally {
    await frames.close();
    if (state.playing === play) stopPlay();
  }
}

// ---------- 만들기 ----------
let engine = null;
const ext = () => (engine && engine.container) || 'mp4';

function setBusy(b) {
  state.busy = b;
  el.jsonFile.disabled = b;
  el.mediaFiles.disabled = b;
  el.jsonText.disabled = b;
  el.makeBtn.disabled = b || !state.job;
  el.progressBox.hidden = !b;
  el.cancelBtn.disabled = !b;
}

function setProgress(frac, text) {
  el.progressBar.style.width = `${Math.round(frac * 1000) / 10}%`;
  el.progressText.textContent = `${Math.floor(frac * 100)}% · ${text}`;
}

async function make() {
  const job = state.job;
  if (!job || state.busy) return;
  stopPlay();
  setBusy(true);
  el.resultBox.hidden = true;
  const abort = new AbortController();
  state.abort = abort;
  setProgress(0, '소리 섞는 중…');
  const started = performance.now();
  try {
    if (!engine || engine.width !== job.plan.width) engine = { ...(await pickEngine(job.plan.width, job.plan.height, forceEngine)), width: job.plan.width };
    const mixed = await ensureMix();
    if (abort.signal.aborted) throw new Cancelled();
    const scale = el.preview.width / job.plan.width;
    const blob = await exportVideo({
      plan: job.plan,
      fileOf: job.fileOfSeg,
      mixed,
      engine,
      signal: abort.signal,
      onProgress: setProgress,
      onFrame: (canvas) => {
        pctx.setTransform(1, 0, 0, 1, 0, 0);
        pctx.drawImage(canvas, 0, 0, job.plan.width * scale, job.plan.height * scale);
      },
    });
    if (state.resultUrl) URL.revokeObjectURL(state.resultUrl);
    const url = URL.createObjectURL(blob);
    state.resultUrl = url;
    const name = outputName(job.spec, engine.container);
    el.resultVideo.src = url;
    el.downloadLink.href = url;
    el.downloadLink.download = name;
    el.downloadLink.textContent = `내려받기 (${name})`;
    const secs = ((performance.now() - started) / 1000).toFixed(1);
    el.resultMeta.textContent = `${job.plan.width}×${job.plan.height} · ${job.plan.duration.toFixed(1)}초 · ${fmtSize(blob.size)} · ${engine.label} · ${secs}초 걸림`;
    el.resultBox.hidden = false;
    el.downloadLink.click();
    setMessages([{ level: 'ok', text: `완성했습니다: ${name}. 다운로드가 시작되지 않으면 아래 "내려받기"를 누르세요.` }]);
  } catch (e) {
    if (e instanceof Cancelled || abort.signal.aborted) setMessages([{ level: 'warn', text: '만들기를 취소했습니다.' }]);
    else {
      console.error(e);
      setMessages([{ level: 'error', text: `만들지 못했습니다: ${e.message || e}` }]);
    }
  } finally {
    state.abort = null;
    setBusy(false);
    if (state.job === job) showStill(scrubFrame());
  }
}

// ---------- 입력 ----------
el.jsonFile.addEventListener('change', async () => {
  const f = el.jsonFile.files[0];
  if (!f) return;
  el.jsonName.textContent = f.name;
  state.jsonText = await f.text();
  el.jsonText.value = state.jsonText;
  analyze();
});

let typing = null;
el.jsonText.addEventListener('input', () => {
  clearTimeout(typing);
  typing = setTimeout(() => {
    state.jsonText = el.jsonText.value;
    el.jsonName.textContent = state.jsonText.trim() ? '직접 입력' : '선택 안 함';
    analyze();
  }, 400);
});

el.mediaFiles.addEventListener('change', () => {
  state.files = [...el.mediaFiles.files];
  el.mediaName.textContent = state.files.length ? `${state.files.length}개 선택` : '선택 안 함';
  analyze();
});

el.scrub.addEventListener('input', () => {
  if (state.playing) stopPlay();
  showStill(scrubFrame());
});
el.playBtn.addEventListener('click', togglePlay);
el.makeBtn.addEventListener('click', make);
el.cancelBtn.addEventListener('click', () => state.abort && state.abort.abort());
el.exampleBtn.addEventListener('click', () => {
  const blob = new Blob([JSON.stringify(EXAMPLE_JOB, null, 2) + '\n'], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'shortform-job.json';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

// ---------- 시작 ----------
(async () => {
  try {
    engine = { ...(await pickEngine(720, 1280, forceEngine)), width: 720 };
  } catch (e) {
    engine = { kind: 'none', label: '확인 실패', note: String(e.message || e) };
  }
  el.engineNote.textContent = `만들 형식: ${engine.label}${engine.note ? ` — ${engine.note}` : ''}`;
  el.engineNote.className = `engine ${engine.kind === 'webcodecs' && engine.container === 'mp4' ? 'good' : 'warn'}`;
  document.body.dataset.engine = engine.kind;
  if (state.job) el.makeBtn.disabled = state.busy || engine.kind === 'none';
})();
analyze();
