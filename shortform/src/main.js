import './style.css';
import { checkSpec, normalizeSpec, composeInputs, baseName, aiScenes, schema } from './core/spec.js';
import { planTimeline, describePlan, TEMPLATE_KO } from './core/plan.js';
import { plan as claudePlan } from './core/claude.js';
import { matchFiles, fileFor, outputName } from './app/match.js';
import { EXAMPLE_JOB, EXAMPLES } from './app/example.js';
import { StatusView, notifyDone } from './app/status.js';
import { Tour, tourSeen, setupTips } from './app/tour.js';
import { checkDecodable, StillFrames, SequentialFrames, mixAudio } from './render/media.js';
import { prepareSegments, drawFrame, frameCount } from './render/draw.js';
import { pickEngine, exportVideo, Cancelled } from './render/export.js';
import { generateScene, checkConnection, DEFAULT_H3VIDEO, DEFAULT_FL2VA, DEFAULT_REF2VA, H3_SHORT_EDGE } from './ai/generate.js';
import { sourceFrames } from './ai/frames.js';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const forceEngine = params.get('engine'); // 'recorder' 면 실시간 녹화 경로(테스트용)
const anthropicBase = params.get('anthropic_base') || undefined; // 가짜 엔드포인트 테스트용
const PRESETS = (schema.properties.resolution && schema.properties.resolution['x-presets']) || ['720x1280', '1080x1920'];

const el = new Proxy({}, { get: (_, k) => $(k) });

// ---------- localStorage(실패해도 동작) ----------
const LS = {
  get(k, d = null) {
    try {
      const v = window.localStorage.getItem(k);
      return v == null ? d : v;
    } catch {
      return d;
    }
  },
  set(k, v) {
    try {
      if (v == null || v === '') window.localStorage.removeItem(k);
      else window.localStorage.setItem(k, v);
    } catch {
      /* 저장 못 함 */
    }
  },
};

const state = {
  jsonText: '',
  files: [],
  job: null,
  mixed: null,
  still: null,
  busy: false,
  playing: null,
  abort: null,
  resultUrl: null,
  generated: new Map(), // 장면 요청 키 → 생성된 File (같은 요청은 다시 만들지 않음)
};

const pctx = el.preview.getContext('2d', { alpha: false });
const scratch = document.createElement('canvas');
const status = new StatusView(el.statusBox, el.liveStatus);

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
    const role = match ? match.roles[baseName(f.name)] : null;
    items.push({ name: f.name, meta: fmtSize(f.size), role: role || (match ? '쓰지 않음' : ''), cls: role ? 'ok' : 'idle' });
  }
  for (const m of match ? match.missing : []) items.push({ name: m, meta: '', role: '파일 칸에 없음', cls: 'missing' });
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

// ---------- 설정 ↔ JSON ----------
const conn = {
  mode: LS.get('shorts.aiMode', 'h3video'),
  h3: LS.get('shorts.h3Server', DEFAULT_H3VIDEO),
  fl2va: LS.get('shorts.fl2va', DEFAULT_FL2VA),
  ref2va: LS.get('shorts.ref2va', DEFAULT_REF2VA),
};

function fillResolutionOptions() {
  const sel = el.setResolution;
  sel.replaceChildren();
  const label = (r) => {
    const [w, h] = r.split('x').map(Number);
    const kind = w === h ? '정사각' : w > h ? '가로' : Math.abs(w / h - 0.8) < 0.01 ? '4:5' : '9:16';
    return `${w}×${h} (${kind})${r === '720x1280' ? ' · 기본' : ''}`;
  };
  for (const r of PRESETS) sel.append(new Option(label(r), r));
  sel.append(new Option('직접 입력…', 'custom'));
}

function ensureOption(sel, value, text) {
  if (![...sel.options].some((o) => o.value === value)) sel.append(new Option(text || value, value));
  sel.value = value;
}

function showMode(mode) {
  el.h3Fields.hidden = mode !== 'h3video';
  el.sgFields.hidden = mode !== 'sglang';
  document.querySelectorAll('input[name=aiMode]').forEach((r) => (r.checked = r.value === mode));
}

function syncSettings(obj) {
  el.setTemplate.value = obj.template || '';
  el.setFit.value = obj.fit || 'blur';
  const res = obj.resolution || '720x1280';
  if (PRESETS.includes(res)) {
    el.setResolution.value = res;
    el.setResolutionCustom.hidden = true;
  } else {
    el.setResolution.value = 'custom';
    el.setResolutionCustom.hidden = false;
    if (document.activeElement !== el.setResolutionCustom) el.setResolutionCustom.value = res;
  }
  ensureOption(el.setFps, String(obj.fps || 30), `${obj.fps || 30}fps`);
  el.setQuality.value = obj.quality || 'medium';
  if (obj.backend === 'sglang') {
    conn.mode = 'sglang';
    if (obj.server) conn.fl2va = obj.server;
    if (obj.ref_server) conn.ref2va = obj.ref_server;
  } else if (obj.backend === 'h3video' || obj.backend === 'auto' || obj.server) {
    conn.mode = 'h3video';
    if (obj.server) conn.h3 = obj.server;
  }
  showMode(conn.mode);
  el.aiServer.value = conn.h3;
  el.aiFl2va.value = conn.fl2va;
  el.aiRef2va.value = conn.ref2va;
  const g = obj.gen_size ?? H3_SHORT_EDGE;
  ensureOption(el.aiGenSize, String(g), typeof g === 'number' ? `${g}p` : g);
  if (obj.prompt || obj.scenes) el.aiPanel.open = true;
}

// JSON 이 비어 있는 필드는 화면의 연결 설정으로 채운다(내보내기·생성에 쓰는 실제 명세).
// JSON 에 server 만 있고 backend 가 없으면 명세 기본값 auto(서버에 물어 판별) — CLI 와 같다.
// (전에는 h3video 로 단정해 examples/scenes.json 처럼 SGLang 주소를 적은 명세가 /api/jobs 404 로 실패했다)
function effectiveSpec(raw) {
  const s = { ...raw };
  if (!s.prompt && !s.scenes) return s;
  if (s.backend == null) s.backend = s.server != null ? 'auto' : conn.mode;
  if (s.server == null) s.server = conn.mode === 'sglang' ? conn.fl2va : conn.h3;
  if (s.ref_server == null && s.backend === 'sglang') s.ref_server = conn.ref2va;
  return s;
}

function parseJsonText() {
  if (!state.jsonText.trim()) return {};
  const v = JSON.parse(state.jsonText);
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error('JSON 최상위는 객체({ ... })여야 합니다');
  return v;
}

function setJsonText(text, name) {
  state.jsonText = text;
  el.jsonText.value = text;
  if (name != null) el.jsonName.textContent = name;
}

// 화면 설정 하나를 JSON 에 써 넣는다(value 가 undefined 면 지움).
function writeFields(changes) {
  let obj;
  try {
    obj = parseJsonText();
  } catch (e) {
    setMessages([{ level: 'error', text: `JSON 문법 오류를 먼저 고치세요: ${e.message}` }]);
    return;
  }
  for (const [k, v] of Object.entries(changes)) {
    if (v === undefined) delete obj[k];
    else obj[k] = v;
  }
  setJsonText(JSON.stringify(obj, null, 2) + '\n', state.jsonText.trim() ? undefined : '화면 설정에서 만듦');
  analyze();
}

function saveConn() {
  LS.set('shorts.aiMode', conn.mode);
  LS.set('shorts.h3Server', conn.h3);
  LS.set('shorts.fl2va', conn.fl2va);
  LS.set('shorts.ref2va', conn.ref2va);
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
  el.previewEmpty.innerHTML = 'JSON과 영상을 고르면<br>여기에 미리보기가 나옵니다';
  pctx.fillStyle = '#000';
  pctx.fillRect(0, 0, el.preview.width, el.preview.height);
}

function genKey(scene, n) {
  const f = (p) => {
    const x = fileFor(state.files, p);
    return x ? [x.name, x.size, x.lastModified] : p;
  };
  return JSON.stringify({
    p: scene.prompt,
    t: scene.task,
    d: scene.duration,
    s: scene.seed,
    i: scene.image && f(scene.image),
    r: scene.sources.map((m) => f(m.path)),
    ratio: n.ratio,
    g: n.gen_size ?? null,
    b: n.backend,
    sv: n.server,
    rs: n.ref_server,
  });
}

function sizePreview(W, H) {
  const pw = 270;
  const ph = Math.round((pw * H) / W);
  if (el.preview.width !== pw || el.preview.height !== ph) {
    el.preview.width = pw;
    el.preview.height = ph;
  }
  el.previewWrap.style.aspectRatio = `${W} / ${H}`;
  el.resultVideo.style.aspectRatio = `${W} / ${H}`;
}

async function analyze() {
  const my = ++seq;
  clearPlan();
  el.failBox.hidden = true;
  if (!state.jsonText.trim()) {
    renderFileList(null);
    setMessages([{ level: 'info', text: '먼저 파일 칸 1에 작업 JSON을 고르세요. 형식이 궁금하면 "예시 JSON 받기"나 ? 도움말을 보세요.' }]);
    return;
  }
  let raw;
  try {
    raw = parseJsonText();
  } catch (e) {
    renderFileList(null);
    setMessages([{ level: 'error', text: e instanceof SyntaxError ? `JSON 문법 오류: ${e.message}` : e.message }]);
    return;
  }
  syncSettings(raw);
  const eff = effectiveSpec(raw);
  const match = matchFiles(eff, state.files);
  renderFileList(match);
  const { errors, warnings } = checkSpec(match.spec);
  if (errors.length) {
    setMessages(errors.map((text) => ({ level: 'error', text })));
    return;
  }
  const n = normalizeSpec(match.spec);
  if (match.missing.length) {
    setMessages([{ level: 'error', text: `JSON이 가리키는 파일을 파일 칸 2에서 함께 골라 주세요: ${match.missing.join(', ')}` }]);
    return;
  }
  if (n.usesAi) {
    if (n.backend === 'vllm') {
      setMessages([{ level: 'error', text: '웹은 h3video 웹 서버와 SGLang만 연결합니다. vLLM 서버는 CLI(shorts run)를 쓰세요.' }]);
      return;
    }
    const scenes = aiScenes(match.spec);
    const cached = scenes.map((sc) => state.generated.get(genKey(sc, n)));
    const base = { ai: true, spec: n, matchSpec: match.spec, scenes, warnings };
    if (cached.every(Boolean)) {
      await prepareCompose(base, cached, my);
      return;
    }
    state.job = base;
    const total = scenes.reduce((a, s) => a + s.duration, 0);
    const where = n.backend === 'sglang' ? `SGLang ${n.server}${scenes.some((s) => s.task === 'ref2va') ? ` · ref2va ${n.ref_server}` : ''}` : `${n.backend === 'auto' ? '자동 판별' : 'h3video'} ${n.server}`;
    el.planLine.textContent = `AI 장면 ${scenes.length}개(${scenes.map((s) => s.task).join(', ')}, 합계 ${total}초) 생성 → ${TEMPLATE_KO[n.template] || n.template} 합성`;
    el.previewEmpty.innerHTML = 'AI 장면을 만든 뒤<br>여기에 미리보기가 나옵니다';
    setMessages([
      ...warnings.map((text) => ({ level: 'warn', text })),
      { level: 'ok', text: `준비됐습니다. "만들기"를 누르면 ${where} 에 장면 생성을 요청하고 합성합니다.` },
    ]);
    el.makeBtn.disabled = state.busy || !engine || engine.kind === 'none';
    return;
  }
  await prepareCompose({ ai: false, spec: n, matchSpec: match.spec, warnings }, null, my);
}

// 합성 준비: 파일 정보를 읽고 타임라인을 짠다. genFiles 가 있으면 AI 생성 영상이 소스.
async function prepareCompose(base, genFiles, my) {
  const all = [...state.files, ...(genFiles || [])];
  const inputs = composeInputs(base.matchSpec, genFiles ? genFiles.map((f) => f.name) : []);
  const baseFile = inputs.base ? fileFor(all, inputs.base.path) : null;
  const clipFiles = inputs.clips.map((c) => fileFor(all, c.path));
  const bgmFile = inputs.bgm ? fileFor(all, inputs.bgm) : null;
  if (!genFiles) setMessages([{ level: 'info', text: '영상 정보를 읽는 중…' }]);
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
    if (my != null && my !== seq) return null;
    setMessages([{ level: 'error', text: e.message }]);
    return null;
  }
  if (my != null && my !== seq) return null;
  let plan;
  try {
    plan = planTimeline(base.spec, probed);
  } catch (e) {
    setMessages([{ level: 'error', text: e.message }]);
    return null;
  }
  const segs = prepareSegments(plan);
  const fileOfSeg = (s) => (s.kind === 'base' ? baseFile : clipFiles[s.index]);
  const fileOfAudio = (a) => (a.kind === 'base' ? baseFile : a.kind === 'bgm' ? bgmFile : clipFiles[a.index]);
  const job = { ...base, plan, segs, fileOfSeg, fileOfAudio };
  state.job = job;
  state.mixed = null;
  sizePreview(plan.width, plan.height);
  state.still = new StillFrames(plan, segs, fileOfSeg, el.preview.width / plan.width);
  const notes = [...new Set([...base.warnings, ...plan.warnings])];
  setMessages([
    ...notes.map((text) => ({ level: 'warn', text })),
    { level: 'ok', text: genFiles ? 'AI 장면이 준비됐습니다.' : `준비됐습니다. "만들기"를 누르면 ${outputName(base.spec, ext())} 파일을 만듭니다.` },
  ]);
  el.planLine.textContent = describePlan(plan) + (genFiles ? ` · AI 장면 ${genFiles.length}개` : '');
  el.previewEmpty.hidden = true;
  el.scrub.disabled = false;
  el.playBtn.disabled = false;
  el.makeBtn.disabled = state.busy || !engine || engine.kind === 'none';
  const k0 = Math.round(Math.min(1, plan.duration / 3) * plan.fps);
  el.scrub.value = String(Math.round((k0 / frameCount(plan)) * 1000));
  showStill(k0);
  return job;
}

// ---------- 미리보기 ----------
let stillBusy = false;
let stillNext = null;

async function showStill(k) {
  const job = state.job;
  if (!job || !job.plan) return;
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
  if (!job || !job.plan) return 0;
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
  if (!job || !job.plan) return;
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
  for (const id of ['jsonFile', 'mediaFiles', 'firstImage', 'refFiles', 'jsonText', 'importFile', 'planBtn']) el[id].disabled = b;
  document.querySelectorAll('#settingsPanel select, #settingsPanel input, #aiPanel input, #aiPanel select').forEach((x) => (x.disabled = b));
  el.makeBtn.disabled = b || !state.job;
  el.makeBtn.textContent = b ? '만드는 중…' : '만들기';
  el.progressBox.hidden = !b;
  el.cancelBtn.disabled = !b;
}

function setProgress(frac, text) {
  el.progressBar.style.width = `${Math.round(frac * 1000) / 10}%`;
  el.progressText.textContent = `${Math.floor(frac * 100)}% · ${text}`;
}

function explain(e) {
  const m = String((e && e.message) || e);
  if (/연결하지 못했습니다/.test(m)) return m;
  if (/HTTP 4\d\d/.test(m)) return `${m} — 서버가 요청을 거절했습니다. 프롬프트·길이(4~15초)·참조 개수를 확인하세요.`;
  if (/HTTP 5\d\d/.test(m)) return `${m} — 서버 내부 오류입니다. 서버 로그를 확인하고 잠시 뒤 다시 시도하세요.`;
  if (/생성에 실패/.test(m)) return `${m} — 모델이 장면을 만들지 못했습니다. 프롬프트를 바꾸거나 다시 시도하세요.`;
  if (/Encoder|encode|codec/i.test(m)) return `인코딩 오류: ${m} — 해상도를 낮추거나 최신 크롬·엣지에서 다시 해 보세요.`;
  return m;
}

function restoreTitleLater() {
  const done = () => setTimeout(() => !state.busy && status.title(null), 4000);
  if (document.hidden) document.addEventListener('visibilitychange', done, { once: true });
  else done();
}

async function make() {
  let job = state.job;
  if (!job || state.busy) return;
  stopPlay();
  setBusy(true);
  el.failBox.hidden = true;
  const abort = new AbortController();
  state.abort = abort;
  setProgress(0, '준비 중…');
  const started = performance.now();
  status.start(!!job.ai);
  status.stage('validate');
  try {
    if (job.ai) {
      const n = job.spec;
      const N = job.scenes.length;
      const files = [];
      job.scenes.forEach((sc, i) => status.addScene(i, N, sc));
      for (let i = 0; i < N; i++) {
        const sc = job.scenes[i];
        const key = genKey(sc, n);
        if (state.generated.has(key)) {
          files[i] = state.generated.get(key);
          status.updateScene(i, { state: 'reused' });
          continue;
        }
        const blob = await generateScene({
          scene: sc,
          spec: n,
          conn: { backend: n.backend, server: n.server, refServer: n.ref_server, poll: n.poll, timeout: n.timeout },
          fileOf: (p) => fileFor(state.files, p),
          signal: abort.signal,
          onStatus: (st) => {
            if (st.stage) status.stage(st.stage, st.stage === 'generate' || st.stage === 'queue' ? `(장면 ${i + 1}/${N})` : '');
            status.updateScene(i, st);
            if (st.note) status.announce(st.note);
            const p = st.progress != null ? st.progress : 0;
            if (st.state || st.progress != null) {
              const overall = (i + p) / N;
              setProgress(overall, `AI 장면 ${i + 1}/${N} · ${st.state || ''}${st.retry ? ` · 재시도 중(${st.retry}/${st.maxRetry})` : ''}`);
              status.title(`⏳ ${Math.floor(overall * 100)}% 생성 중`);
            }
          },
        });
        const file = new File([blob], `ai-scene-${i + 1}.mp4`, { type: 'video/mp4' });
        state.generated.set(key, file);
        files[i] = file;
        status.updateScene(i, { state: 'completed' });
      }
      status.stage('compose');
      const composed = await prepareCompose(job, files, null);
      if (!composed) throw new Error(el.messages.textContent || '생성한 영상을 합성 준비하지 못했습니다');
      job = composed;
    }
    status.stage('compose');
    setProgress(0, '소리 섞는 중…');
    status.title('⏳ 합성 중');
    const { plan } = job;
    if (!engine || engine.width !== plan.width || engine.height !== plan.height) {
      engine = { ...(await pickEngine(plan.width, plan.height, forceEngine)), width: plan.width, height: plan.height };
      showEngine();
    }
    const mixed = await ensureMix();
    if (abort.signal.aborted) throw new Cancelled();
    status.stage('encode');
    const scale = el.preview.width / plan.width;
    const blob = await exportVideo({
      plan,
      fileOf: job.fileOfSeg,
      mixed,
      engine,
      signal: abort.signal,
      onProgress: (f, t) => {
        setProgress(f, t);
        status.title(`⏳ ${Math.floor(f * 100)}% 인코딩 중`);
      },
      onFrame: (canvas) => {
        pctx.setTransform(1, 0, 0, 1, 0, 0);
        pctx.drawImage(canvas, 0, 0, plan.width * scale, plan.height * scale);
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
    el.resultMeta.textContent = `${plan.width}×${plan.height} · ${plan.fps}fps · ${plan.duration.toFixed(1)}초 · ${fmtSize(blob.size)} · ${engine.label} · ${secs}초 걸림`;
    el.resultBox.hidden = false;
    el.resultEmpty.hidden = true;
    el.downloadLink.click();
    status.finish(true, `완성했습니다: ${name}`);
    status.title('✅ 완료');
    notifyDone(`${name} 완성`, el.notifyChk.checked);
    setMessages([{ level: 'ok', text: `완성했습니다: ${name}. 다운로드가 시작되지 않으면 "내려받기"를 누르세요.` }]);
  } catch (e) {
    if (e instanceof Cancelled || e.name === 'AbortError' || abort.signal.aborted) {
      status.finish(false, '취소했습니다');
      status.title(null);
      setMessages([{ level: 'warn', text: '만들기를 취소했습니다. 이미 만든 AI 장면은 다음 번에 다시 씁니다.' }]);
    } else {
      console.warn(e);
      const text = explain(e);
      status.finish(false, `실패: ${text}`);
      status.title('⚠️ 실패');
      el.failText.textContent = text;
      el.failBox.hidden = false;
      notifyDone('만들기 실패', el.notifyChk.checked);
    }
  } finally {
    state.abort = null;
    setBusy(false);
    restoreTitleLater();
    if (state.job && state.job.plan) showStill(scrubFrame());
  }
}

function showEngine() {
  el.engineNote.textContent = `만들 형식: ${engine.label}${engine.note ? ` — ${engine.note}` : ''}`;
  el.engineNote.className = `engine ${engine.kind === 'webcodecs' && engine.container === 'mp4' ? 'good' : 'warn'}`;
  document.body.dataset.engine = engine.kind;
}

// ---------- 입력 ----------
async function loadJsonFile(f) {
  if (!f) return;
  const fromSlot = f === el.jsonFile.files[0];
  if (!fromSlot) el.jsonFile.value = '';
  setJsonText(await f.text(), fromSlot ? '' : f.name);
  el.importFile.value = '';
  analyze();
}

el.jsonFile.addEventListener('change', () => loadJsonFile(el.jsonFile.files[0]));
el.importFile.addEventListener('change', () => loadJsonFile(el.importFile.files[0]));

let typing = null;
el.jsonText.addEventListener('input', () => {
  clearTimeout(typing);
  typing = setTimeout(() => {
    state.jsonText = el.jsonText.value;
    el.jsonName.textContent = state.jsonText.trim() ? '직접 입력' : '';
    analyze();
  }, 400);
});

// 파일 칸: 2 소스(이름으로 JSON 과 짝), 3 첫 프레임 이미지, 4 참조 이미지·영상. 칸마다 따로 두고 합쳐서 쓴다.
const slotFiles = { media: [], image: [], refs: [] };
function syncFiles() {
  const seen = new Set();
  state.files = [...slotFiles.media, ...slotFiles.image, ...slotFiles.refs].filter((f) => !seen.has(f.name) && seen.add(f.name));
}
el.mediaFiles.addEventListener('change', () => {
  slotFiles.media = [...el.mediaFiles.files];
  syncFiles();
  el.mediaName.textContent = '';
  analyze();
});
// 칸 3·4 는 CLI 의 --image / --ref 와 같다: 고른 파일 이름을 JSON 의 image / sources 에 써 넣는다.
el.firstImage.addEventListener('change', () => {
  const f = el.firstImage.files[0];
  if (!f) return;
  slotFiles.image = [f];
  syncFiles();
  el.firstImageName.textContent = f.name;
  writeFields({ image: f.name });
});
el.refFiles.addEventListener('change', () => {
  const picked = [...el.refFiles.files];
  if (!picked.length) return;
  slotFiles.refs = picked;
  syncFiles();
  el.refFilesName.textContent = picked.map((f) => f.name).join(', ');
  let obj = {};
  try { obj = parseJsonText(); } catch { /* writeFields 가 문법 오류를 알려 준다 */ }
  const cur = Array.isArray(obj.sources) ? obj.sources : [];
  const names = new Set(cur.map((s) => (typeof s === 'string' ? s : s && s.path)));
  writeFields({ sources: [...cur, ...picked.map((f) => f.name).filter((n) => !names.has(n))] });
});

el.setTemplate.addEventListener('change', () => writeFields({ template: el.setTemplate.value || undefined }));
el.setFit.addEventListener('change', () => writeFields({ fit: el.setFit.value }));
el.setFps.addEventListener('change', () => writeFields({ fps: Number(el.setFps.value) }));
el.setQuality.addEventListener('change', () => writeFields({ quality: el.setQuality.value }));
el.setResolution.addEventListener('change', () => {
  if (el.setResolution.value === 'custom') {
    el.setResolutionCustom.hidden = false;
    el.setResolutionCustom.focus();
    return;
  }
  el.setResolutionCustom.hidden = true;
  writeFields({ resolution: el.setResolution.value });
});
el.setResolutionCustom.addEventListener('change', () => {
  const v = el.setResolutionCustom.value.toLowerCase().replace(/\s+/g, '').replace(/[×*]/g, 'x');
  if (v) writeFields({ resolution: v });
});

document.querySelectorAll('input[name=aiMode]').forEach((r) =>
  r.addEventListener('change', () => {
    conn.mode = r.value;
    saveConn();
    showMode(conn.mode);
    if (conn.mode === 'sglang') writeFields({ backend: 'sglang', server: conn.fl2va, ref_server: conn.ref2va });
    else writeFields({ backend: 'h3video', server: conn.h3, ref_server: undefined });
  }),
);
const urlInput = (input, key, field) =>
  input.addEventListener('change', () => {
    conn[key] = input.value.trim();
    saveConn();
    writeFields({ [field]: conn[key] || undefined });
  });
urlInput(el.aiServer, 'h3', 'server');
urlInput(el.aiFl2va, 'fl2va', 'server');
urlInput(el.aiRef2va, 'ref2va', 'ref_server');
el.aiGenSize.addEventListener('change', () => {
  const v = el.aiGenSize.value;
  writeFields({ gen_size: /^\d+$/.test(v) ? Number(v) : v });
});
el.aiCheck.addEventListener('click', async () => {
  el.aiCheckOut.textContent = '확인 중…';
  el.aiCheckOut.className = 'check-out';
  try {
    const c = conn.mode === 'sglang' ? { backend: 'sglang', server: conn.fl2va, refServer: conn.ref2va } : { backend: 'h3video', server: conn.h3 };
    el.aiCheckOut.textContent = await checkConnection(c);
    el.aiCheckOut.className = 'check-out ok';
  } catch (e) {
    el.aiCheckOut.textContent = e.message;
    el.aiCheckOut.className = 'check-out bad';
  }
});

el.scrub.addEventListener('input', () => {
  if (state.playing) stopPlay();
  showStill(scrubFrame());
});
el.playBtn.addEventListener('click', togglePlay);
el.makeBtn.addEventListener('click', make);
el.retryBtn.addEventListener('click', make);
el.cancelBtn.addEventListener('click', () => state.abort && state.abort.abort());
el.notifyChk.addEventListener('change', () => {
  if (el.notifyChk.checked && 'Notification' in window && Notification.permission === 'default') Notification.requestPermission().catch(() => {});
});

function download(obj, name) {
  const blob = new Blob([JSON.stringify(obj, null, 2) + '\n'], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
el.exampleBtn.addEventListener('click', () => download(EXAMPLE_JOB, 'shortform-job.json'));
el.exportBtn.addEventListener('click', () => {
  let obj;
  try {
    obj = effectiveSpec(parseJsonText());
  } catch (e) {
    setMessages([{ level: 'error', text: `내보낼 수 없습니다: ${e.message}` }]);
    return;
  }
  download(obj, outputName(obj, 'json').replace(/\.json$/, '-job.json'));
});

// ---------- Claude 기획 ----------
el.apiKey.value = LS.get('shorts.anthropicKey', '');
el.apiKey.addEventListener('change', () => LS.set('shorts.anthropicKey', el.apiKey.value.trim()));
el.keyClear.addEventListener('click', () => {
  LS.set('shorts.anthropicKey', null);
  el.apiKey.value = '';
  el.planOut.textContent = '키를 지웠습니다.';
});
let planAbort = null;
el.planBtn.addEventListener('click', async () => {
  if (planAbort) {
    planAbort.abort();
    return;
  }
  const apiKey = el.apiKey.value.trim();
  LS.set('shorts.anthropicKey', apiKey);
  planAbort = new AbortController();
  el.planBtn.textContent = '요청 취소';
  el.planOut.className = 'check-out';
  try {
    let sources = [];
    if (state.files.length) {
      el.planOut.textContent = '소스 영상 프레임을 뽑는 중…';
      try {
        sources = await sourceFrames(state.files);
      } catch (e) {
        console.warn(e);
      }
    }
    el.planOut.textContent = `Claude에게 기획을 요청하는 중…${sources.length ? ` (프레임 ${sources.reduce((a, s) => a + s.frames.length, 0)}장)` : ''} 1~2분 걸릴 수 있습니다`;
    const res = await claudePlan({
      idea: el.idea.value,
      sources,
      apiKey,
      baseUrl: anthropicBase,
      signal: planAbort.signal,
      log: (t) => (el.planOut.textContent = t),
    });
    setJsonText(JSON.stringify(res.spec, null, 2) + '\n', 'Claude 기획');
    el.jsonDetails.open = true;
    el.planOut.textContent = `작업 JSON을 채웠습니다(시도 ${res.attempts}회). 확인하고 "만들기"를 누르세요.`;
    el.planOut.className = 'check-out ok';
    analyze();
  } catch (e) {
    el.planOut.textContent = e.name === 'AbortError' ? '기획 요청을 취소했습니다.' : e.message;
    el.planOut.className = 'check-out bad';
  } finally {
    planAbort = null;
    el.planBtn.textContent = 'Claude에게 기획 요청';
  }
});

// ---------- 도움말·둘러보기 ----------
const tour = new Tour();
el.helpBtn.addEventListener('click', () => el.helpDialog.showModal());
el.helpClose.addEventListener('click', () => el.helpDialog.close());
el.tourBtn.addEventListener('click', () => {
  el.helpDialog.close();
  tour.start(0);
});
el.helpExamples.replaceChildren(
  ...EXAMPLES.map((ex) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'example';
    b.innerHTML = '<strong></strong><small></small>';
    b.querySelector('strong').textContent = ex.name;
    b.querySelector('small').textContent = ex.note;
    b.addEventListener('click', () => {
      setJsonText(JSON.stringify(ex.job, null, 2) + '\n', `예시: ${ex.name}`);
      el.jsonDetails.open = true;
      el.helpDialog.close();
      analyze();
      el.slotJson.scrollIntoView({ block: 'center' });
    });
    return b;
  }),
);
document.querySelectorAll('.origin').forEach((x) => (x.textContent = location.origin.startsWith('http') ? location.origin : 'https://33modeling.pages.dev'));
setupTips();
fillResolutionOptions();
syncSettings({});

// ---------- 시작 ----------
(async () => {
  try {
    engine = { ...(await pickEngine(720, 1280, forceEngine)), width: 720, height: 1280 };
  } catch (e) {
    engine = { kind: 'none', label: '확인 실패', note: String(e.message || e) };
  }
  showEngine();
  if (state.job) el.makeBtn.disabled = state.busy || engine.kind === 'none';
})();
analyze();
if (!tourSeen() && !params.has('notour')) setTimeout(() => tour.start(0), 400);
