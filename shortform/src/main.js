import './style.css';
import {mountPromptLibrary,draftProject} from '../../src/h3video/studio/prompt-library.js';
import {listProjects,saveDraft,saveScene,saveOutput,loadProject,restorePrevious} from './app/recovery.js';
import { checkSpec, normalizeSpec, composeInputs, baseName, aiScenes, schema } from './core/spec.js';
import { planTimeline, describePlan, TEMPLATE_KO } from './core/plan.js';
import { plan as claudePlan } from './core/claude.js';
import { matchFiles, fileFor, outputName, kindOf } from './app/match.js';
import { isStory, storyToSpec } from './core/story.js';
import { EXAMPLE_JOB, EXAMPLES } from './app/example.js';
import { StatusView, notifyDone, fmtSec, STATE_KO } from './app/status.js';
import { Tour, tourSeen, setupTips, hintDismissed, dismissHint } from './app/tour.js';
import { isJsonFile, isZipFile, isMediaFile, zipToFiles, pickJson, sortDropped } from './app/drop.js';
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
  jsonLabel: '', // 1번 칸에 보일 이름(파일 이름·직접 입력·예시 등)
  files: [],
  match: null,
  job: null,
  mixed: null,
  still: null,
  busy: false,
  playing: null,
  abort: null,
  resultUrl: null,
  generated: new Map(), // 장면 요청 키 → 생성된 File (같은 요청은 다시 만들지 않음)
};

let recoveryId=LS.get('shorts.recovery.current')||crypto.randomUUID(),recoveryReady=false,recoveryWrites=Promise.resolve();
LS.set('shorts.recovery.current',recoveryId);
async function saveCurrent(){if(!recoveryReady||!state.jsonText.trim())return;const draft={id:recoveryId,jsonText:state.jsonText,files:[...state.files],paused:Boolean(state.paused)};recoveryWrites=recoveryWrites.then(()=>saveDraft(draft)).catch(()=>{el.recoveryMessage.textContent='기기 저장 공간을 확인해 주세요. 현재 작업은 유지하며 결과를 내려받을 수 있습니다.';});await recoveryWrites;await refreshLibrary();}
async function refreshLibrary(){try{const rows=await listProjects();el.recoveryLibrary.replaceChildren(new Option('저장한 영상 작업', ''),...rows.map(row=>new Option(row.title+(row.paused?' · 일시중지':''),row.id)));el.recoveryLibrary.value=recoveryId;}catch{}}
async function restoreSaved(saved){if(!saved)return;recoveryId=saved.id;LS.set('shorts.recovery.current',recoveryId);state.files=saved.files.filter(Boolean);slotFiles.media=[...state.files];slotFiles.image=[];slotFiles.refs=[];state.generated=saved.generated;state.paused=saved.paused;setJsonText(saved.jsonText,'저장한 작업');el.resultBox.hidden=true;el.resultEmpty.hidden=false;if(saved.output){if(state.resultUrl)URL.revokeObjectURL(state.resultUrl);state.resultUrl=URL.createObjectURL(saved.output);el.resultVideo.src=state.resultUrl;el.downloadLink.href=state.resultUrl;el.downloadLink.download=saved.output.name;el.downloadLink.textContent='저장한 영상 내려받기';el.resultBox.hidden=false;el.resultEmpty.hidden=true;}el.recoveryMessage.textContent=`저장본을 열었습니다. 완료한 AI 장면 ${state.generated.size}개를 재사용합니다.`;await analyze();}
const pctx = el.preview.getContext('2d', { alpha: false });
const scratch = document.createElement('canvas');
const status = new StatusView(el.statusBox, el.liveStatus);

// 이야기 JSON(JSON 한번에) 상태 — 아래 '입력' 의 takeStory/convertStory 가 쓴다
const story = { src: null, note: null, unused: new Set() };

// ---------- 메시지 ----------
function setMessages(list) {
  // 이야기 JSON 을 바꿔 넣었으면 그 안내를 맨 위에 둔다
  if (story.src && story.note) list = [story.note, ...list];
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

// ---------- 파일 칸 표시: 칸마다 파일 칩(그림·이름·쓰이는 곳·빼기) ----------
const thumbs = new Map(); // File → { url, el } (설정을 바꿀 때마다 다시 읽지 않게 재사용)
function thumbFor(f) {
  let t = thumbs.get(f);
  if (!t) {
    const kind = kindOf(f);
    t = { url: null, el: document.createElement('span') };
    t.el.className = 'chip-thumb';
    t.el.dataset.kind = kind;
    if (kind === 'image' || kind === 'video') {
      t.url = URL.createObjectURL(f);
      const m = document.createElement(kind === 'image' ? 'img' : 'video');
      if (kind === 'image') {
        m.alt = '';
        m.decoding = 'async';
      } else {
        m.muted = true;
        m.preload = 'metadata';
        m.tabIndex = -1;
      }
      m.src = kind === 'video' ? `${t.url}#t=0.5` : t.url;
      m.addEventListener('error', () => m.remove(), { once: true });
      t.el.append(m);
    }
    thumbs.set(f, t);
  }
  return t.el;
}
function pruneThumbs() {
  const live = new Set([...slotFiles.media, ...slotFiles.image, ...slotFiles.refs]);
  for (const [f, t] of thumbs) {
    if (live.has(f)) continue;
    if (t.url) URL.revokeObjectURL(t.url);
    thumbs.delete(f);
  }
}

function chipEl({ file = null, name, role = '', meta = '', cls = 'idle', slot, kind = null, removable = true }) {
  const li = document.createElement('li');
  li.className = `chip ${cls}`;
  li.dataset.name = name;
  let th;
  if (file) th = thumbFor(file);
  else {
    th = document.createElement('span');
    th.className = 'chip-thumb';
    th.dataset.kind = kind || 'missing';
  }
  const body = document.createElement('span');
  body.className = 'chip-body';
  const nm = document.createElement('span');
  nm.className = 'chip-name';
  nm.textContent = name;
  nm.title = name;
  const rl = document.createElement('span');
  rl.className = 'chip-role';
  rl.textContent = [role, meta].filter(Boolean).join(' · ');
  body.append(nm, rl);
  li.append(th, body);
  if (removable) {
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'chip-x';
    x.textContent = '×';
    x.setAttribute('aria-label', `${name} 빼기`);
    x.title = '빼기';
    x.addEventListener('click', () => removeFile(slot, file ? file.name : null));
    li.append(x);
  }
  return li;
}

function roleOf(f, match) {
  if (story.src && story.unused.has(f.name)) return { role: '쓰지 않음 · 맞는 쪽이 없어요', cls: 'idle' };
  if (!match) return { role: state.jsonText.trim() ? '' : 'JSON을 넣으면 쓰일 곳이 정해져요', cls: 'idle' };
  const r = match.roles[baseName(f.name)];
  if (!r && slotFiles.refs.includes(f)) return { role: '쓰지 않음 · AI 장면(prompt)을 만들 때 참고로 써요', cls: 'idle' };
  return r ? { role: r, cls: 'ok' } : { role: '쓰지 않음', cls: 'idle' };
}

function renderSlots(match = state.match) {
  state.match = match;
  const json = [];
  if (state.jsonText.trim() || story.src) {
    let role = '작업 JSON';
    let cls = 'ok';
    if (story.src) role = story.note && story.note.level === 'error' ? '이야기 JSON · 바꾸지 못함' : `이야기 JSON → 장면 ${story.scenes}개`;
    try {
      if (!story.src) parseJsonText();
    } catch {
      role = 'JSON 문법 오류';
    }
    if (/오류|못함/.test(role)) cls = 'missing';
    json.push(chipEl({ name: state.jsonLabel || '직접 입력', role, cls, slot: 'json', kind: 'json' }));
  }
  const files = (slot) => slotFiles[slot].map((f) => chipEl({ file: f, name: f.name, meta: fmtSize(f.size), slot, ...roleOf(f, match) }));
  const missing = (match ? match.missing : []).map((m) => chipEl({ name: m, role: '빠짐 · 이 칸에 같이 넣어 주세요', cls: 'missing', slot: 'media', removable: false }));
  el.chipsJson.replaceChildren(...json);
  el.chipsMedia.replaceChildren(...files('media'), ...missing);
  el.chipsImage.replaceChildren(...files('image'));
  el.chipsRefs.replaceChildren(...files('refs'));
  for (const [id, n] of [['slotJson', json.length], ['slotMedia', slotFiles.media.length + missing.length], ['slotImage', slotFiles.image.length], ['slotRefs', slotFiles.refs.length]]) {
    el[id].classList.toggle('filled', n > 0);
  }
  el.slotMedia.classList.toggle('has-missing', missing.length > 0);
  pruneThumbs();
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
    // 넓은 화면의 좁은 칸에서도 잘리지 않게 짧게 (전에는 '720×1280 (9:16) · 기본' 이 잘렸다)
    const kind = w === h ? '정사각' : w > h ? '가로' : Math.abs(w / h - 0.8) < 0.01 ? '4:5' : '세로';
    return `${w}×${h} ${kind}${r === '720x1280' ? '(기본)' : ''}`;
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

function setTemplateCard(v) {
  document.querySelectorAll('input[name=tpl]').forEach((r) => (r.checked = r.value === v));
  showTemplateNote();
}
// 좁은 화면에서는 카드 설명을 숨기고 고른 카드의 설명만 아래 한 줄로 보인다
function showTemplateNote() {
  const card = document.querySelector('input[name=tpl]:checked')?.closest('.tpl-card');
  el.tplNow.textContent = card ? `${card.querySelector('.tpl-name').textContent}: ${card.querySelector('.tpl-desc').textContent}` : '';
}

function syncSettings(obj) {
  setTemplateCard(obj.template || '');
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

// JSON.parse 의 영어 오류(브라우저마다 다름) → 몇 줄 몇 번째 글자인지 쉬운 말로. 원래 메시지는 괄호에.
function jsonErrorText(text, e) {
  const msg = String((e && e.message) || e);
  if (!(e instanceof SyntaxError)) return msg;
  let line = null, col = null;
  const lc = /line (\d+) column (\d+)/.exec(msg);
  const pos = /position (\d+)/.exec(msg);
  if (lc) [line, col] = [Number(lc[1]), Number(lc[2])];
  else if (pos) {
    const before = String(text).slice(0, Number(pos[1]));
    line = before.split('\n').length;
    col = before.length - before.lastIndexOf('\n');
  }
  if (line) return `JSON 문법 오류: ${line}줄 ${col}번째 글자 근처 — 따옴표·쉼표·괄호를 확인하세요 (${msg})`;
  if (/end of (JSON|data)|unexpected EOF/i.test(msg)) return `JSON 문법 오류: 중간에 끝났어요 — 닫는 괄호 } ] 나 따옴표가 빠졌는지 확인하세요 (${msg})`;
  return `JSON 문법 오류: 따옴표·쉼표·괄호를 확인하세요 (${msg})`;
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
  if (name != null) state.jsonLabel = name;
}

// 화면 설정 하나를 JSON 에 써 넣는다(value 가 undefined 면 지움).
function writeFields(changes, { quiet = false } = {}) {
  let obj;
  try {
    obj = parseJsonText();
  } catch (e) {
    setMessages([{ level: 'error', text: `먼저 고치세요 — ${jsonErrorText(state.jsonText, e)}` }]);
    return false;
  }
  for (const [k, v] of Object.entries(changes)) {
    if (v === undefined) delete obj[k];
    else obj[k] = v;
  }
  setJsonText(JSON.stringify(obj, null, 2) + '\n', state.jsonText.trim() ? undefined : '화면 설정에서 만듦');
  if (!quiet) analyze();
  return true;
}

// 이야기 JSON 이 아닌 작업 JSON 을 바로 넣을 때(예시·Claude)
function useJson(text, label) {
  story.src = null;
  story.note = null;
  story.unused = new Set();
  setJsonText(text, label);
  syncFiles();
}

function saveConn() {
  LS.set('shorts.aiMode', conn.mode);
  LS.set('shorts.h3Server', conn.h3);
  LS.set('shorts.fl2va', conn.fl2va);
  LS.set('shorts.ref2va', conn.ref2va);
}

// ---------- 분석(명세 → 계획) ----------
let seq = 0;

function setReady(on) {
  el.makeBtn.disabled = !on;el.restartBtn.disabled=!on||state.busy;
  el.againBtn.disabled = !on;
  updateDock();
}

function setEmpty(text) {
  el.previewEmpty.hidden = false;
  el.previewEmptyText.innerHTML = text;
  el.stageCard.classList.add('is-empty');
}

function clearPlan() {
  stopPlay();
  state.job = null;
  state.mixed = null;
  state.still = null;
  setReady(false);
  el.scrub.disabled = true;
  el.playBtn.disabled = true;
  el.planSum.textContent = '아직 만들 것이 없어요';
  el.planLine.textContent = '아직 계획이 없습니다.';
  setEmpty('파일을 넣으면<br>여기서 미리 봐요');
  pctx.fillStyle = '#0d0f12';
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
  el.previewWrap.style.setProperty('--ar', `${W} / ${H}`);
  el.resultVideo.style.aspectRatio = `${W} / ${H}`;
}

async function analyze() {
  await saveCurrent();
  const my = ++seq;
  clearPlan();
  el.failBox.hidden = true;
  if (!state.jsonText.trim()) {
    renderSlots(null);
    setMessages([{ level: 'info', text: story.src ? '이야기 JSON을 바꾸지 못했어요. 위 안내를 보세요.' : '작업 JSON이 있어야 만들 수 있어요. 파일을 놓거나, 위에서 "예시로 해 보기"·"아이디어로 기획"을 골라 보세요.' }]);
    return;
  }
  let raw;
  try {
    raw = parseJsonText();
  } catch (e) {
    renderSlots(null);
    setMessages([{ level: 'error', text: jsonErrorText(state.jsonText, e) }]);
    return;
  }
  syncSettings(raw);
  const eff = effectiveSpec(raw);
  const match = matchFiles(eff, state.files);
  renderSlots(match);
  const { errors, warnings } = checkSpec(match.spec);
  if (errors.length) {
    setMessages(errors.map((text) => ({ level: 'error', text })));
    return;
  }
  const n = normalizeSpec(match.spec);
  if (match.missing.length) {
    setMessages([{ level: 'error', text: `JSON에 적힌 파일이 아직 없어요: ${match.missing.join(', ')} — 2번 칸(내 영상·그림·음악)에 같이 넣어 주세요` }]);
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
    el.planSum.textContent = `AI 장면 ${scenes.length}개 · 합계 ${total}초`;
    el.planLine.textContent = `AI 장면 ${scenes.length}개(${scenes.map((s) => s.task).join(', ')}, 합계 ${total}초) 생성 → ${TEMPLATE_KO[n.template] || n.template} 합성`;
    setEmpty('AI 장면을 만든 뒤<br>여기서 미리 봐요');
    setMessages([
      ...warnings.map((text) => ({ level: 'warn', text })),
      { level: 'ok', text: `준비됐어요. "만들기"를 누르면 ${where} 에 장면 생성을 요청하고 합성해요.` },
    ]);
    setReady(!state.busy && engine && engine.kind !== 'none');
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
    { level: 'ok', text: genFiles ? 'AI 장면이 준비됐어요.' : `준비됐어요. "만들기"를 누르면 ${outputName(base.spec, ext())} 파일을 만들어요.` },
  ]);
  const clips = plan.segments.filter((x) => x.kind === 'clip').length;
  el.planSum.textContent = `${plan.duration.toFixed(1)}초 · ${TEMPLATE_KO[plan.template] || plan.template}` + (genFiles ? ` · AI 장면 ${genFiles.length}개` : clips ? ` · 클립 ${clips}개` : '');
  el.planLine.textContent = describePlan(plan) + (genFiles ? ` · AI 장면 ${genFiles.length}개` : '');
  el.previewEmpty.hidden = true;
  el.stageCard.classList.remove('is-empty');
  el.scrub.disabled = false;
  el.playBtn.disabled = false;
  setReady(!state.busy && engine && engine.kind !== 'none');
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
  el.playBtn.textContent = '재생';
  el.playBtn.setAttribute('aria-label', '미리보기 재생');
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
  el.playBtn.setAttribute('aria-label', '미리보기 정지');
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
  for (const id of ['jsonFile', 'mediaFiles', 'firstImage', 'refFiles', 'allFiles', 'jsonText', 'importFile', 'planBtn', 'pickAll', 'startExample', 'startStory', 'startIdea']) el[id].disabled = b;
  document.querySelectorAll('#settingsPanel select, #settingsPanel input, #aiPanel input, #aiPanel select, .slot-pick').forEach((x) => (x.disabled = b));
  document.body.classList.toggle('is-busy', b);
  el.restartBtn.disabled=b||!state.job;el.makeBtn.textContent = b ? '만드는 중…' : state.paused?'저장본 이어 만들기':'만들기';
  el.pauseBtn.disabled=!b;for(const id of ['recoveryLibrary','recoverySave','recoveryRestore','recoveryNew'])el[id].disabled=b;
  el.progressBox.hidden = !b;
  el.cancelBtn.disabled = !b;
  setReady(!b && !!state.job);
}

// 진행률: 큰 숫자(%) + 막대 + 지금 하는 일 + 남은 시간(이 단계가 시작된 뒤 걸린 시간으로 어림)
const phase = { t0: 0 };
const newPhase = () => (phase.t0 = performance.now());
function setProgress(frac, text) {
  const pct = Math.max(0, Math.min(100, Math.floor(frac * 100)));
  el.progressBar.style.width = `${Math.round(frac * 1000) / 10}%`;
  el.progressPct.textContent = `${pct}%`;
  el.progressRole.setAttribute('aria-valuenow', String(pct));
  el.progressText.textContent = String(text).replace(/ · 남은 시간 약 [^·]*/, '');
  const spent = (performance.now() - phase.t0) / 1000;
  el.progressEta.textContent = frac > 0.02 && frac < 1 && spent > 1 ? `남은 시간 약 ${fmtSec((spent * (1 - frac)) / frac)}` : frac >= 1 ? '마무리 중' : '';
  updateDock();
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
  state.paused=false;state.pauseRequested=false;state.phase=job.ai?'generate':'compose';
  await saveCurrent();
  newPhase();
  setProgress(0, '준비 중…');
  requestAnimationFrame(() => el.progressBox.scrollIntoView({ block: 'nearest' }));
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
        if(state.pauseRequested)throw new Cancelled();
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
              setProgress(overall, `AI 장면 ${i + 1}/${N} · ${STATE_KO[st.state] || st.state || ''}${st.retry ? ` · 재시도 중(${st.retry}/${st.maxRetry})` : ''}`);
              status.title(`⏳ ${Math.floor(overall * 100)}% 생성 중`);
            }
          },
        });
        const file = new File([blob], `ai-scene-${i + 1}.mp4`, { type: 'video/mp4' });
        state.generated.set(key, file);
        try{await saveScene(recoveryId,key,file);}catch{el.recoveryMessage.textContent='완료한 장면은 현재 창에 보존했습니다. 기기 저장 공간을 확인해 주세요.';}
        files[i] = file;
        status.updateScene(i, { state: 'completed' });
      }
      if(state.pauseRequested)throw new Cancelled();
      state.phase='compose';
      status.stage('compose');
      const composed = await prepareCompose(job, files, null);
      if (!composed) throw new Error(el.messages.textContent || '생성한 영상을 합성 준비하지 못했습니다');
      job = composed;
    }
    status.stage('compose');
    newPhase();
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
    newPhase();
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
    el.downloadLink.textContent = '내려받기';
    const secs = ((performance.now() - started) / 1000).toFixed(1);
    el.resultName.textContent = name;
    el.resultMeta.textContent = `${fmtSize(blob.size)} · ${plan.duration.toFixed(1)}초 · ${plan.width}×${plan.height} · ${plan.fps}fps`;
    el.resultSub.textContent = `${engine.label} · ${secs}초 걸림 · 내려받기가 자동으로 시작돼요`;
    try{await saveOutput(recoveryId,new File([blob],name,{type:blob.type}));}catch{el.recoveryMessage.textContent='기기 저장 공간이 부족합니다. 완성본을 내려받아 보관하세요.';}
    el.resultBox.hidden = false;
    el.resultEmpty.hidden = true;
    el.downloadLink.click();
    requestAnimationFrame(() => el.resultBox.scrollIntoView({ block: 'nearest', behavior: 'smooth' }));
    status.finish(true, `완성했어요: ${name}`);
    status.title('✅ 완료');
    notifyDone(`${name} 완성`, el.notifyChk.checked);
    setMessages([{ level: 'ok', text: `완성했어요: ${name}. 내려받기가 저절로 시작되지 않으면 "내려받기"를 누르세요.` }]);
  } catch (e) {
    if (e instanceof Cancelled || e.name === 'AbortError' || abort.signal.aborted) {
      state.paused=true;await saveCurrent();
      status.finish(false,state.pauseRequested?'저장하고 일시중지했습니다':'취소했어요',true);
      status.title(null);
      setMessages([{ level: 'warn', text: '만들기를 취소/일시중지했습니다. 저장본을 수정하고 이어 만들 수 있습니다. 완료한 AI 장면은 새로고침 후에도 재사용합니다.' }]);
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
  const good = engine.kind === 'webcodecs' && engine.container === 'mp4';
  // 잘 되는 경우는 한 줄만(설명은 마우스를 올리면), 대신 쓰는 경우는 이유까지 보인다
  el.engineNote.textContent = `만들 형식: ${engine.label}${engine.note && !good ? ` — ${engine.note}` : ''}`;
  el.engineNote.title = engine.note || '';
  el.engineNote.className = `engine ${good ? 'good' : 'warn'}`;
  document.body.dataset.engine = engine.kind;
}

// ---------- 입력 ----------
// JSON 한번에: 이야기 JSON(동화책 콘티·동화책 만들기 book.json·clips 목록)
// 1번 칸에 넣으면 숏폼 명세로 바꿔 넣는다. 장면 수·길이(쪽 글 읽는 시간)는 JSON 에서 정하고,
// 2번 칸의 그림을 쪽마다 첫 프레임으로 맞춘다(이름 page-03 → 3쪽, cover → 표지, 나머지는 순서대로).
// CLI 의 shorts run 이야기.json 그림폴더/ 와 같다(src/core/story.js ↔ shorts/story.py).
const KIND_KO = { conti: '동화책 콘티', book: '동화책 만들기 book.json', list: '장면 목록' };
function takeStory(text, name) {
  let v;
  try { v = JSON.parse(text.replace(/^﻿/, '')); } catch { story.src = null; return false; }
  if (!isStory(v)) { story.src = null; return false; }
  story.src = { data: v, name };
  convertStory();
  return true;
}
function convertStory() {
  if (!story.src) return;
  const names = slotFiles.media.filter((f) => kindOf(f) === 'image').map((f) => f.name)
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  story.unused = new Set();
  story.scenes = 0;
  try {
    const { spec, info } = storyToSpec(story.src.data, names);
    story.unused = new Set(info.unused_images);
    story.scenes = info.clips.length;
    const linked = info.clips.filter((c) => c.image).length;
    story.note = { level: 'info', text: `${KIND_KO[info.source]} → 숏폼: ${info.title} · 장면 ${info.clips.length}개 · 합계 ${info.total}초(쪽 글 읽는 시간) · 그림 ${linked}장 연결`
      + (linked < info.clips.length ? ` · 그림 없는 장면 ${info.clips.length - linked}개는 글로만 만듭니다(쪽 그림은 2번 칸에 같이 넣기)` : '')
      + (story.unused.size ? ` · 쓰지 않는 그림: ${[...story.unused].join(', ')}` : '') };
    setJsonText(JSON.stringify(spec, null, 2), story.src.name);
  } catch (e) {
    story.note = { level: 'error', text: `${story.src.name}: ${e.message}` };
    setJsonText('', story.src.name);
  }
  syncFiles();
}

async function loadJsonFile(f) {
  if (!f) return;
  const text = await f.text();
  el.importFile.value = '';
  if (takeStory(text, f.name)) return analyze();
  setJsonText(text, f.name);
  analyze();
}
el.importFile.addEventListener('change', () => loadJsonFile(el.importFile.files[0]));

let typing = null;
el.jsonText.addEventListener('input', () => {
  clearTimeout(typing);
  typing = setTimeout(() => {
    if (takeStory(el.jsonText.value, '직접 입력')) return analyze();
    state.jsonText = el.jsonText.value;
    const prev = state.jsonLabel;
    state.jsonLabel = !state.jsonText.trim() ? '' : !prev || prev === '직접 입력' || prev.endsWith('(고침)') ? prev || '직접 입력' : `${prev} (고침)`;
    analyze();
  }, 400);
});

// 파일 칸: 1 작업 JSON, 2 내 영상·그림·음악(이름으로 JSON 과 짝), 3 첫 장면 그림(JSON image), 4 참고 자료(JSON sources).
// 칸 3·4 는 CLI 의 --image / --ref 와 같다: 넣은 파일 이름을 JSON 에 써 넣고, 빼면 지운다. 칸마다 따로 두고 합쳐서 쓴다.
const slotFiles = { media: [], image: [], refs: [] };
function syncFiles() {
  const seen = new Set();
  // 이야기 JSON 에서 맞는 쪽이 없는 그림은 빼 둔다(남으면 모든 장면의 참조로 붙는다)
  state.files = [...slotFiles.media, ...slotFiles.image, ...slotFiles.refs]
    .filter((f) => !seen.has(f.name) && seen.add(f.name) && !(story.src && story.unused.has(f.name)));
}
// 파일 하나는 한 칸에만: 같은 이름이 있으면 새 파일로 바꾼다
function putFiles(slot, files) {
  const names = new Set(files.map((f) => f.name));
  for (const k of Object.keys(slotFiles)) slotFiles[k] = slotFiles[k].filter((f) => !names.has(f.name));
  slotFiles[slot] = slot === 'image' ? files.slice(0, 1) : [...slotFiles[slot], ...files];
}
const sourceName = (m) => (typeof m === 'string' ? m : m && m.path);
function jsonObj() {
  try {
    return parseJsonText();
  } catch {
    return null;
  }
}
function refsToJson(files) {
  const obj = jsonObj() || {};
  const cur = Array.isArray(obj.sources) ? obj.sources : [];
  const have = new Set(cur.map((m) => baseName(sourceName(m) || '')));
  return writeFields({ sources: [...cur, ...files.map((f) => f.name).filter((n) => !have.has(n))] }, { quiet: true });
}

// 칩의 × : 칸에서 빼고, 3·4번 칸이면 JSON 에서도 그 이름을 지운다
function removeFile(slot, name) {
  if (state.busy) return;
  showDropNote([]);
  if (slot === 'json') {
    story.src = null;
    story.note = null;
    story.unused = new Set();
    setJsonText('', '');
    el.jsonFile.value = '';
  } else {
    slotFiles[slot] = slotFiles[slot].filter((f) => f.name !== name);
    const obj = jsonObj();
    if (obj && slot === 'image' && obj.image && baseName(obj.image) === name) writeFields({ image: undefined }, { quiet: true });
    if (obj && slot === 'refs' && Array.isArray(obj.sources)) {
      const left = obj.sources.filter((m) => baseName(sourceName(m) || '') !== name);
      if (left.length !== obj.sources.length) writeFields({ sources: left.length ? left : undefined }, { quiet: true });
    }
    if (slot === 'media') convertStory();
  }
  syncFiles();
  analyze();
}

function showDropNote(lines, level = 'info') {
  const list = (Array.isArray(lines) ? lines : [lines]).filter(Boolean);
  el.dropNote.hidden = !list.length;
  el.dropNote.className = `drop-note ${level}`;
  el.dropNote.textContent = list.join(' · ');
}

// 지금 1번 칸의 내용: 이야기 JSON 인가, 작업 JSON 객체인가
function currentCtx() {
  if (story.src) return { story: true };
  const o = jsonObj();
  return o && Object.keys(o).length ? { spec: o } : {};
}

// 한꺼번에 놓기(또는 칸에 놓기·고르기). target 이 있으면 JSON 이 아닌 파일은 그 칸으로.
// zip 은 풀어서 안의 파일을 하나씩 놓은 것처럼 다룬다.
const SLOT_KO = { media: '내 영상·그림·음악', image: '첫 장면 그림', refs: '참고 자료' };
async function takeDrop(list, target = null) {
  let files = [...list];
  if (!files.length) return;
  if (state.busy) {
    showDropNote('만드는 중에는 파일을 바꿀 수 없어요. 끝나거나 취소한 뒤 넣어 주세요.', 'warn');
    return;
  }
  const zipNotes = [];
  const notes = [];
  let level = 'info';
  const zips = files.filter(isZipFile);
  if (zips.length) {
    files = files.filter((f) => !isZipFile(f));
    for (const z of zips) {
      try {
        const got = await zipToFiles(z);
        files.push(...got.files);
        zipNotes.push(`${z.name}에서 ${got.files.length}개를 꺼냈어요${got.skipped.length ? ` (쓰지 않는 ${got.skipped.length}개는 뺌)` : ''}`);
      } catch (e) {
        zipNotes.push(`${z.name}: ${e.message}`);
        level = 'error';
      }
    }
    target = null; // zip 안의 파일은 늘 알아서 나눈다
  }
  const { json, others } = pickJson(files);
  if (others.length) notes.push(`JSON은 하나만 써요: ${json.name}을 쓰고 ${others.map((f) => f.name).join(', ')}은 뺐어요`);
  const rest = files.filter((f) => !isJsonFile(f));
  let text = null;
  let ctx = currentCtx();
  if (json) {
    text = await json.text();
    let v;
    try {
      v = JSON.parse(text.replace(/^﻿/, ''));
    } catch {
      v = null;
    }
    ctx = v && typeof v === 'object' ? (isStory(v) ? { story: true } : Array.isArray(v) ? {} : { spec: v }) : {};
  }
  let sorted;
  if (target && target !== 'json') {
    sorted = { media: [], image: [], refs: [], skipped: rest.filter((f) => !isMediaFile(f)) };
    let ok = rest.filter(isMediaFile);
    if (target === 'image') {
      const imgs = ok.filter((f) => kindOf(f) === 'image');
      if (imgs.length !== ok.length || imgs.length > 1) notes.push('3번 칸에는 그림 한 장만 들어가요');
      ok = imgs.slice(0, 1);
    }
    sorted[target] = ok;
  } else sorted = sortDropped(rest, { ...ctx, hasImage: slotFiles.image.length > 0 });
  if (sorted.skipped.length) notes.push(`쓸 수 없는 파일은 뺐어요: ${sorted.skipped.map((f) => f.name).join(', ')}`);
  if (sorted.media.length) putFiles('media', sorted.media);
  if (json) {
    if (!takeStory(text, json.name)) setJsonText(text, json.name);
  } else if (sorted.media.length) convertStory();
  if (sorted.image.length) {
    putFiles('image', sorted.image);
    writeFields({ image: sorted.image[0].name }, { quiet: true });
  }
  if (sorted.refs.length) {
    putFiles('refs', sorted.refs);
    // 참고 자료는 AI 장면(prompt·scenes)용이다. AI 가 아닌 JSON 의 sources 는 클립이라 그림·소리를 넣으면
    // '읽을 수 없는 형식' 오류로 만들기가 막혔다 → 영상만 클립으로 쓰고 그림·소리는 칸에만 둔다.
    const o = jsonObj() || {};
    const ai = !!(story.src || o.prompt || o.scenes);
    const usable = ai ? sorted.refs : sorted.refs.filter((f) => kindOf(f) === 'video');
    if (usable.length) refsToJson(usable);
    if (usable.length < sorted.refs.length) {
      notes.push('4번 칸의 그림·소리는 AI로 장면을 만들 때(JSON에 prompt가 있을 때) 참고로 써요. 지금은 넣어만 뒀어요');
      level = level === 'error' ? level : 'warn';
    }
  }
  syncFiles();
  const placed = [json ? '작업 JSON 1개' : '', ...['media', 'image', 'refs'].map((k) => (sorted[k].length ? `${SLOT_KO[k]} ${sorted[k].length}개` : ''))].filter(Boolean);
  if (placed.length && (!target || zips.length || files.length > 1)) notes.unshift(`${target ? '넣었어요' : '나눠 넣었어요'}: ${placed.join(', ')}`);
  showDropNote([...zipNotes, ...notes], level);
  analyze();
}

// 칸마다 고르기: 고른 파일을 그 칸에 더한다(빈 선택은 그 칸 비우기)
el.jsonFile.addEventListener('change', () => {
  const f = el.jsonFile.files[0];
  el.jsonFile.value = '';
  if (f) takeDrop([f], 'json');
});
el.mediaFiles.addEventListener('change', () => {
  const picked = [...el.mediaFiles.files];
  el.mediaFiles.value = '';
  if (picked.length) return takeDrop(picked, 'media');
  if (state.busy) return;
  slotFiles.media = [];
  syncFiles();
  convertStory();
  analyze();
});
el.firstImage.addEventListener('change', () => {
  const f = el.firstImage.files[0];
  el.firstImage.value = '';
  if (f) takeDrop([f], 'image');
});
el.refFiles.addEventListener('change', () => {
  const picked = [...el.refFiles.files];
  el.refFiles.value = '';
  if (picked.length) takeDrop(picked, 'refs');
});
el.allFiles.addEventListener('change', () => {
  const picked = [...el.allFiles.files];
  el.allFiles.value = '';
  if (picked.length) takeDrop(picked);
});
el.pickAll.addEventListener('click', () => el.allFiles.click());
el.dropZone.addEventListener('click', (e) => {
  if (!e.target.closest('button') && !state.busy) el.allFiles.click();
});
document.querySelectorAll('.slot-pick').forEach((b) => b.addEventListener('click', () => el[b.dataset.input].click()));

// 끌어 놓기: 페이지 어디에 놓아도 되고, 칸 위에 놓으면 그 칸으로. 폴더를 놓으면 안의 파일을 모두 꺼낸다.
const hasFiles = (e) => !!e.dataTransfer && [...(e.dataTransfer.types || [])].includes('Files');
let dragDepth = 0;
function markDrop(target) {
  const zone = target && target.closest ? target.closest('[data-slot], #dropZone') : null;
  document.querySelectorAll('.drop-hover').forEach((x) => x !== zone && x.classList.remove('drop-hover'));
  if (zone) zone.classList.add('drop-hover');
}
function endDrag() {
  dragDepth = 0;
  document.body.classList.remove('dragging');
  markDrop(null);
}
async function readEntries(entries) {
  const out = [];
  const walk = async (en, depth) => {
    if (en.isFile) out.push(await new Promise((res, rej) => en.file(res, rej)));
    else if (en.isDirectory && depth < 4) {
      const reader = en.createReader();
      for (;;) {
        const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
        if (!batch.length) break;
        for (const c of batch) await walk(c, depth + 1);
      }
    }
  };
  for (const en of entries) await walk(en, 0);
  return out;
}
window.addEventListener('dragenter', (e) => {
  if (!hasFiles(e)) return;
  dragDepth += 1;
  document.body.classList.add('dragging');
});
window.addEventListener('dragleave', (e) => {
  if (!hasFiles(e)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) endDrag();
});
window.addEventListener('dragover', (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = state.busy ? 'none' : 'copy';
  markDrop(e.target);
});
window.addEventListener('drop', (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  endDrag();
  const slotEl = e.target && e.target.closest ? e.target.closest('[data-slot]') : null;
  // DataTransfer 는 이 이벤트 안에서만 읽힌다: 폴더 항목과 파일 목록을 먼저 잡아 둔다
  const entries = [...(e.dataTransfer.items || [])].filter((it) => it.kind === 'file').map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null));
  const plain = [...(e.dataTransfer.files || [])];
  const useEntries = entries.length && entries.every(Boolean) && entries.some((en) => en.isDirectory);
  (useEntries ? readEntries(entries) : Promise.resolve(plain))
    .then((files) => takeDrop(files, slotEl ? slotEl.dataset.slot : null))
    .catch((err) => showDropNote(`파일을 읽지 못했어요: ${err.message}`, 'error'));
});

document.querySelectorAll('input[name=tpl]').forEach((r) =>
  r.addEventListener('change', () => {
    if (!r.checked) return;
    showTemplateNote();
    writeFields({ template: r.value || undefined });
  }),
);
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
el.restartBtn.addEventListener('click',async()=>{if(state.busy||!state.job)return;await saveCurrent();recoveryId=crypto.randomUUID();LS.set('shorts.recovery.current',recoveryId);state.generated=new Map();state.paused=false;await saveCurrent();el.recoveryMessage.textContent='기존 영상과 완료 장면을 보관하고 새 저장본에서 처음부터 만듭니다.';await make();});
el.retryBtn.addEventListener('click', make);
el.againBtn.addEventListener('click', make);
el.cancelBtn.addEventListener('click', () => state.abort && state.abort.abort());
el.pauseBtn.onclick=()=>{state.pauseRequested=true;el.pauseBtn.disabled=true;if(state.phase==='generate')setProgress(0,'현재 장면 저장 후 일시중지…');else state.abort?.abort();};
el.recoverySave.onclick=()=>saveCurrent().then(()=>{el.recoveryMessage.textContent='작업·원본 파일·완료한 장면을 저장했습니다.';});
el.recoveryLibrary.onchange=async()=>{if(state.busy||!el.recoveryLibrary.value)return;const selected=el.recoveryLibrary.value;await saveCurrent();await restoreSaved(await loadProject(selected));};
el.recoveryRestore.onclick=async()=>{if(state.busy)return;await restoreSaved(await restorePrevious(recoveryId));};
el.recoveryNew.onclick=async()=>{if(state.busy)return;await saveCurrent();recoveryId=crypto.randomUUID();LS.set('shorts.recovery.current',recoveryId);state.files=[];state.generated.clear();state.paused=false;setJsonText('','새 작업');el.resultBox.hidden=true;el.resultEmpty.hidden=false;clearPlan();await refreshLibrary();};
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
let siteConnection={configured:false};
const siteConnectionReady=import(/* @vite-ignore */ new URL('../creative-ai/client.mjs',location.href).href)
 .then(client=>client.getConnection()).then(connection=>{
  siteConnection=connection;
  if(connection.configured){el.apiKey.disabled=true;el.apiKey.placeholder='Claude 연결됨 · 키 입력 불필요';el.keyClear.hidden=true;document.querySelector('#claudeConnection').textContent='Claude 연결됨';}
  if(connection.mount)connection.mount(el.claudePanel.querySelector('.fold-body'));
  return connection;
 }).catch(()=>siteConnection);
el.apiKey.value = LS.get('shorts.anthropicKey', '');
el.apiKey.addEventListener('change', () => LS.set('shorts.anthropicKey', el.apiKey.value.trim()));
el.keyClear.addEventListener('click', () => {
  LS.set('shorts.anthropicKey', null);
  el.apiKey.value = '';
  el.planOut.textContent = '키를 지웠어요.';
});
let planAbort = null;
el.planBtn.addEventListener('click', async () => {
  await siteConnectionReady;
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
    el.planOut.textContent = `Claude에게 기획을 요청하는 중…${sources.length ? ` (프레임 ${sources.reduce((a, s) => a + s.frames.length, 0)}장)` : ''} 1~2분 걸릴 수 있어요`;
    const useQwen = document.querySelector('#llmModel').value === 'Qwen/Qwen3.8-27B';
    const res = await claudePlan({
      idea: el.idea.value,
      sources,
      model:document.querySelector('#llmModel').value,
      apiKey:useQwen?document.querySelector('#qwenLlmKey').value.trim():apiKey,
      baseUrl:useQwen?document.querySelector('#qwenLlmUrl').value.trim():anthropicBase,
      connection:useQwen?undefined:siteConnection,
      signal: planAbort.signal,
      log: (t) => (el.planOut.textContent = t),
    });
    useJson(JSON.stringify(res.spec, null, 2) + '\n', 'Claude 기획');
    el.jsonDetails.open = true;
    el.planOut.textContent = `작업 JSON을 채웠어요(시도 ${res.attempts}회). 확인하고 "만들기"를 누르세요.`;
    el.planOut.className = 'check-out ok';
    analyze();
  } catch (e) {
    el.planOut.textContent = e.name === 'AbortError' ? '기획 요청을 취소했어요.' : e.message;
    el.planOut.className = 'check-out bad';
  } finally {
    planAbort = null;
    el.planBtn.textContent = 'Claude에게 기획 요청';
  }
});

// Templates remain editable, and applying one starts a new saved project.
async function applyStoryboard(project,label='영상 콘티'){
  if(state.busy)throw new Error('진행 중인 제작을 마친 뒤 콘티를 불러와 주세요.');
  const {spec}=storyToSpec(project,[],{ratio:project.brief?.ratio});
  spec.resolution=({'9:16':'720x1280','16:9':'1280x720','1:1':'720x720'})[spec.ratio]||'720x1280';
  const {errors}=checkSpec(spec);if(errors.length)throw new Error(errors.join('\n'));
  await saveCurrent();recoveryId=crypto.randomUUID();LS.set('shorts.recovery.current',recoveryId);
  slotFiles.media=[];slotFiles.image=[];slotFiles.refs=[];state.files=[];state.generated=new Map();state.paused=false;
  useJson(JSON.stringify(spec,null,2),label);clearPlan();await analyze();await saveCurrent();
  el.planOut.textContent=label+'을 불러왔어요. 기존 작업은 보관함에 보관했습니다. 장면을 확인하고 만들기를 누르세요.';
  el.filesPanel.scrollIntoView({block:'start'});
}
mountPromptLibrary(el.promptLibrary,{dark:true,applyLabel:'숏폼 작업으로 불러오기',onApply:draft=>applyStoryboard(draftProject(draft),'템플릿 장면 초안')});
let recoveryBoot=Promise.resolve();
if(location.hash==='#from=frame'&&window.opener){
  addEventListener('message',async event=>{
    if(event.source!==window.opener||event.origin!==location.origin||event.data?.type!=='creative-conti-handoff')return;
    try{await recoveryBoot;await applyStoryboard(event.data.project);event.source.postMessage({type:'shorts-received'},event.origin);}
    catch(error){el.planOut.textContent=error.message;event.source.postMessage({type:'shorts-transfer-error',error:error.message},event.origin);}
  });
}

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
      useJson(JSON.stringify(ex.job, null, 2) + '\n', `예시: ${ex.name}`);
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

// ---------- 시작 방법 3가지 ----------
// 예시로 해 보기: 예시 영상 3개 + 배경음을 이 브라우저에서 만들고 예시 작업 JSON 과 함께 칸에 넣는다.
el.startExample.addEventListener('click', async () => {
  if (state.busy) return;
  const btn = el.startExample;
  btn.disabled = true;
  btn.classList.add('working');
  try {
    showDropNote('예시 영상을 만드는 중… (몇 초)');
    const eng = await enginePick;
    const { makeDemo } = await import('./app/demo.js');
    const { job, files } = await makeDemo(eng, (t) => showDropNote(`예시 만드는 중 · ${t}`));
    slotFiles.media = [];
    slotFiles.image = [];
    slotFiles.refs = [];
    story.src = null;
    const jsonFile = new File([JSON.stringify(job, null, 2) + '\n'], 'example-job.json', { type: 'application/json' });
    await takeDrop([jsonFile, ...files]);
    showDropNote('예시 파일을 넣었어요: 작업 JSON 1개, 내 영상(가로) 1개, 클립 2개, 배경음 1개. 미리보기를 보고 "만들기"를 눌러 보세요.', 'ok');
    el.filesPanel.scrollIntoView({ block: 'start', behavior: 'smooth' });
  } catch (e) {
    console.warn(e);
    useJson(JSON.stringify(EXAMPLE_JOB, null, 2) + '\n', '예시 작업 JSON');
    analyze();
    showDropNote(`${e.message} 예시 작업 JSON만 넣어 뒀어요.`, 'warn');
  } finally {
    btn.disabled = state.busy;
    btn.classList.remove('working');
  }
});
// 이야기 JSON + 그림: 동화책 콘티 JSON·동화책 만들기 zip·쪽 그림을 고르게 한다(놓기와 같은 규칙)
el.startStory.addEventListener('click', () => {
  showDropNote('동화책 콘티의 "JSON" 내보내기 파일이나 동화책 만들기의 "파일 받기" zip을 고르세요. 쪽 그림을 같이 골라도 돼요.');
  el.allFiles.click();
});
// 아이디어로 기획: Claude 칸을 열고 아이디어 칸으로
el.startIdea.addEventListener('click', () => {
  el.claudePanel.open = true;
  el.claudePanel.scrollIntoView({ block: 'start', behavior: 'smooth' });
  el.idea.focus({ preventScroll: true });
});

// ---------- 폰 아래 고정 만들기 단추: 준비되면, 만들기 단추가 화면 밖일 때만 ----------
const dock = { makeVisible: true };
function updateDock() {
  const ready = !el.makeBtn.disabled;
  const show = (ready || state.busy) && !dock.makeVisible;
  el.dock.hidden = !show;
  document.body.classList.toggle('has-dock', show);
  if (!show) return;
  el.dockBtn.textContent = state.busy ? `진행 보기 ${el.progressPct.textContent}` : '만들기';
  el.dockText.textContent = state.busy ? el.progressText.textContent : el.planSum.textContent;
}
if ('IntersectionObserver' in window) {
  new IntersectionObserver((ents) => {
    dock.makeVisible = ents[ents.length - 1].isIntersecting;
    updateDock();
  }).observe(el.makeBtn);
}
el.dockBtn.addEventListener('click', () => {
  if (!state.busy) make();
  el.makeArea.scrollIntoView({ block: 'center', behavior: 'smooth' });
});

// ---------- 둘러보기: 저절로 열지 않고 작은 안내만(닫으면 다시 안 보임) ----------
function showHint() {
  el.tourHint.hidden = tourSeen() || hintDismissed() || params.has('notour');
}
el.tourHintGo.addEventListener('click', () => {
  el.tourHint.hidden = true;
  tour.start(0);
});
el.tourHintClose.addEventListener('click', () => {
  dismissHint();
  el.tourHint.hidden = true;
});
tour.onClose = showHint;
showHint();

// ---------- 시작 ----------
const enginePick = (async () => {
  try {
    engine = { ...(await pickEngine(720, 1280, forceEngine)), width: 720, height: 1280 };
  } catch (e) {
    engine = { kind: 'none', label: '확인 실패', note: String(e.message || e) };
  }
  showEngine();
  if (state.job) setReady(!state.busy && engine.kind !== 'none');
  return engine;
})();
recoveryBoot=(async()=>{try{const saved=await loadProject(recoveryId);recoveryReady=true;if(saved)await restoreSaved(saved);else await analyze();await refreshLibrary();}catch{recoveryReady=true;await analyze();}})();

recoveryBoot.finally(()=>{if(location.hash==='#from=frame'&&window.opener)window.opener.postMessage({type:'shorts-ready'},location.origin);});
