// AI 장면 생성: 사용자가 직접 띄운 영상 모델 서버에 브라우저가 바로 요청한다.
// - h3video : minimax-h3-video 의 `h3video web` (POST /api/jobs multipart · GET /api/jobs/{id} · GET /files/{id}/{name})
//             주소 하나로 t2va·fl2va·ref2va 를 모두 처리한다(서버가 SGLang 두 개로 나눠 보냄). 기본 방식.
// - sglang  : SGLang `/v1/videos` 직접(고급). fl2va(=t2va 포함) 주소와 ref2va 주소를 따로 받는다.
//             요청 JSON 은 minimax-h3-video/src/h3video/client.py VideoRequest.to_json() 과 같다.
// shorts/backends.py 와 같은 규칙을 따른다.
import { baseName } from '../core/spec.js';

export const DEFAULT_H3VIDEO = 'http://localhost:8790';
export const DEFAULT_FL2VA = 'http://localhost:30010';
export const DEFAULT_REF2VA = 'http://localhost:30011';
export const H3_SHORT_EDGE = 768;

export class GenError extends Error {}

export function mediaKind(file) {
  const t = (file && file.type) || '';
  const n = (file && file.name) || '';
  if (t.startsWith('image/') || /\.(png|jpe?g|webp|gif|bmp)$/i.test(n)) return 'image';
  if (t.startsWith('audio/') || /\.(mp3|m4a|aac|wav|ogg|oga|opus|flac)$/i.test(n)) return 'audio';
  return 'video';
}

export function normProgress(v) {
  const x = Number(v || 0);
  if (!Number.isFinite(x)) return 0;
  return Math.max(0, Math.min(1, x > 1 ? x / 100 : x));
}

// gen_size → 짧은 변. 숫자면 그대로(상한 768), "WxH" 면 짧은 변.
export function genShortEdge(spec) {
  const g = spec.gen_size;
  let short = H3_SHORT_EDGE;
  if (typeof g === 'string' && g.includes('x')) {
    const [w, h] = g.split('x').map(Number);
    short = Math.min(w, h);
  } else if (g) short = Number(g);
  if (short > H3_SHORT_EDGE) throw new GenError(`gen_size 짧은 변 ${short}px 은 로컬 H3 상한 ${H3_SHORT_EDGE}px 을 넘습니다`);
  return short;
}

const trimSlash = (u) => String(u || '').trim().replace(/\/+$/, '');

export function sglangBody(scene, spec, uriOf) {
  const conds = [];
  if (scene.task === 'fl2va' && scene.image) conds.push({ type: 'image', uri: uriOf(scene.image), role: 'keyframe', frame_index: 0 });
  if (scene.task === 'ref2va') {
    for (const r of scene.sources) conds.push({ type: r.kind, uri: uriOf(r.path), role: 'reference' });
    if (scene.image) conds.push({ type: 'image', uri: uriOf(scene.image), role: 'reference' });
  }
  const body = {
    task: scene.task,
    prompt: scene.prompt,
    conditions: conds,
    target: { short_edge: genShortEdge(spec), aspect_ratio: spec.ratio || '9:16', duration_seconds: Math.round(scene.duration) },
    seed: Number(scene.seed || 0),
  };
  if (spec.model) body.model = spec.model;
  return body;
}

export function h3videoForm(scene, spec, fileOf) {
  const fd = new FormData();
  fd.append('prompt', scene.prompt);
  fd.append('seconds', String(Math.round(scene.duration)));
  fd.append('aspect_ratio', spec.ratio || '9:16');
  fd.append('seed', String(Number(scene.seed || 0)));
  fd.append('title', spec.title || 'shorts');
  if (scene.image && scene.task !== 'ref2va') fd.append('first_image', fileOf(scene.image));
  for (const r of scene.sources) {
    const f = fileOf(r.path);
    const key = { image: 'ref_images', audio: 'ref_audios' }[mediaKind(f)] || 'ref_videos';
    fd.append(key, f, f.name);
  }
  if (scene.task === 'ref2va' && scene.image) fd.append('ref_images', fileOf(scene.image));
  return fd;
}

function netError(url, e) {
  const origin = typeof location !== 'undefined' ? location.origin : '';
  const mixed = origin.startsWith('https:') && url.startsWith('http:') && !/^http:\/\/(localhost|127\.0\.0\.1|\[::1\])[:/]/.test(url);
  const hint = mixed
    ? '이 페이지는 https 라서 http 원격 주소를 부를 수 없습니다(혼합 콘텐츠). ssh -L 터널로 http://localhost:포트 에 붙이세요.'
    : `서버가 켜져 있는지, CORS 로 이 페이지(${origin || '이 주소'})를 허용했는지 확인하세요.`;
  return new GenError(`${url} 에 연결하지 못했습니다 (${e.message}). ${hint}`);
}

async function call(fetchFn, url, opts = {}, signal) {
  let r;
  try {
    r = await fetchFn(url, { ...opts, signal });
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    throw netError(url, e);
  }
  if (!r.ok) {
    let detail = '';
    try {
      const t = await r.text();
      try {
        detail = JSON.parse(t).error || t;
      } catch {
        detail = t;
      }
    } catch {
      /* 무시 */
    }
    if (typeof detail === 'object') detail = detail.message || JSON.stringify(detail);
    throw new GenError(`서버 오류 HTTP ${r.status} (${url}): ${String(detail).slice(0, 200)}`);
  }
  return r;
}

const MAX_RETRY = 5;

// 상태 조회는 끊겨도 바로 실패하지 않고 MAX_RETRY 번까지 다시 묻는다(연결 오류·5xx).
async function pollJson(fetchFn, url, signal, onStatus) {
  for (let k = 0; ; k++) {
    try {
      const j = await (await call(fetchFn, url, {}, signal)).json();
      if (k) onStatus({ retry: 0 });
      return j;
    } catch (e) {
      if (e.name === 'AbortError') throw e;
      const transient = !/HTTP [1-4]\d\d/.test(e.message);
      if (!transient || k >= MAX_RETRY) throw e;
      onStatus({ retry: k + 1, maxRetry: MAX_RETRY });
      await sleep(Math.min(8000, 500 * 2 ** k), signal);
    }
  }
}

const sleep = (ms, signal) =>
  new Promise((res, rej) => {
    const t = setTimeout(res, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(t);
      rej(new DOMException('취소', 'AbortError'));
    }, { once: true });
  });

function readDataUrl(file) {
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result);
    fr.onerror = () => rej(fr.error);
    fr.readAsDataURL(file);
  });
}

// 서버 종류 자동 판별: /api/spec 에 tasks 가 있으면 h3video, 아니면 sglang
export async function detectBackend(server, fetchFn = fetch, signal) {
  try {
    const r = await fetchFn(`${trimSlash(server)}/api/spec`, { signal });
    if (r.ok) {
      const j = await r.json();
      if (j && j.tasks) return 'h3video';
    }
  } catch (e) {
    if (e.name === 'AbortError') throw e;
  }
  return 'sglang';
}

// 연결 확인(화면의 "연결 확인" 버튼)
export async function checkConnection(conn, fetchFn = fetch) {
  if (conn.backend === 'sglang') {
    const out = [];
    for (const [label, url] of [['fl2va', conn.server], ['ref2va', conn.refServer]]) {
      const r = await call(fetchFn, `${trimSlash(url)}/v1/models`);
      const j = await r.json().catch(() => ({}));
      const ids = (j.data || []).map((m) => m.id).filter(Boolean);
      out.push(`${label} 응답 OK${ids.length ? ` (${ids.slice(0, 2).join(', ')})` : ''}`);
    }
    return out.join(' · ');
  }
  const r = await call(fetchFn, `${trimSlash(conn.server)}/api/spec`);
  const j = await r.json();
  if (!j.tasks) throw new GenError('h3video 웹 서버의 /api/spec 응답이 아닙니다');
  let health = '';
  try {
    const h = await (await call(fetchFn, `${trimSlash(conn.server)}/api/health`)).json();
    health = ` · fl2va ${h.fl2va ? '켜짐' : '꺼짐'} · ref2va ${h.ref2va ? '켜짐' : '꺼짐'} · 대기 ${h.queue ?? 0}건`;
  } catch {
    /* health 없음 */
  }
  return `h3video 웹 서버 OK${health}`;
}

// 장면 하나 생성 → mp4 Blob
// scene: aiScenes() 한 항목 { prompt, sources:[{path}], image, duration, seed, task }
// conn: { backend: 'h3video'|'sglang'|'auto', server, refServer, poll(초), timeout(초) }
export async function generateScene({ scene, spec, conn, fileOf, signal, onStatus = () => {}, fetchFn = fetch }) {
  let backend = conn.backend || 'h3video';
  const server = trimSlash(conn.server);
  if (!server) throw new GenError('AI 서버 주소를 넣어 주세요');
  if (backend === 'auto') backend = await detectBackend(server, fetchFn, signal);
  genShortEdge(spec); // 상한 검사(h3video 웹 서버는 크기를 받지 않고 자체 768p 로 만든다)
  const pollMs = Math.max(200, (conn.poll || 3) * 1000);
  const deadline = Date.now() + (conn.timeout || 3600) * 1000;
  const sources = scene.sources.map((r) => ({ path: r.path, kind: mediaKind(fileOf(r.path)) }));
  const sc = { ...scene, sources };

  if (backend === 'h3video') {
    onStatus({ stage: 'connect', backend });
    const r = await call(fetchFn, `${server}/api/jobs`, { method: 'POST', body: h3videoForm(sc, spec, fileOf) }, signal);
    const job = await r.json();
    if (job.error) throw new GenError(`h3video 서버가 거절했습니다: ${job.error}`);
    const id = encodeURIComponent(job.id);
    onStatus({ stage: 'queue', state: job.status || 'queued', id: job.id, backend });
    const onAbort = () => onStatus({ note: 'h3video 웹 서버는 작업 취소를 지원하지 않아 서버에서는 끝까지 돌 수 있습니다' });
    signal?.addEventListener('abort', onAbort, { once: true });
    try {
      for (;;) {
        if (Date.now() > deadline) throw new GenError(`생성 대기 한도(${conn.timeout}초)를 넘었습니다`);
        const j = await pollJson(fetchFn, `${server}/api/jobs/${id}`, signal, onStatus);
        const scenes = j.scenes || [];
        const prog = scenes.length ? scenes.reduce((a, x) => a + normProgress(x.progress), 0) / scenes.length : normProgress(j.progress);
        const state = j.status === 'pending' ? 'queued' : j.status;
        onStatus({ stage: state === 'queued' ? 'queue' : state === 'completed' ? 'download' : 'generate', state, progress: prog, backend });
        if (j.status === 'completed') {
          if (!j.output) throw new GenError('작업에 결과 파일이 없습니다');
          const name = encodeURIComponent(baseName(j.output));
          const blob = await (await call(fetchFn, `${server}/files/${id}/${name}`, {}, signal)).blob();
          if (blob.size < 1000) throw new GenError(`받은 영상이 너무 작습니다 (${blob.size} bytes)`);
          return blob;
        }
        if (j.status === 'failed') throw new GenError(`서버가 생성에 실패했습니다: ${j.error || (scenes.find((x) => x.error) || {}).error || '이유 없음'}`);
        await sleep(pollMs, signal);
      }
    } finally {
      signal?.removeEventListener('abort', onAbort);
    }
  }

  // SGLang 직접: 로컬 파일은 data: URI 로 보낸다(서버 프로세스가 브라우저 파일을 읽을 방법이 없음).
  const base = scene.task === 'ref2va' ? trimSlash(conn.refServer || server) : server;
  const uris = new Map();
  for (const p of [scene.image, ...sources.map((s) => s.path)].filter(Boolean)) uris.set(p, await readDataUrl(fileOf(p)));
  const body = sglangBody(sc, spec, (p) => uris.get(p));
  onStatus({ stage: 'connect', backend: 'sglang' });
  const r = await call(fetchFn, `${base}/v1/videos`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }, signal);
  const created = await r.json();
  if (!created.id) throw new GenError(`응답에 id 가 없습니다: ${JSON.stringify(created).slice(0, 200)}`);
  const id = encodeURIComponent(created.id);
  onStatus({ stage: 'queue', state: created.status || 'queued', id: created.id, backend: 'sglang' });
  // 취소하면 서버 작업도 지우기를 시도한다(OpenAI 호환 DELETE /v1/videos/{id}; 지원 안 하면 무시)
  const onAbort = () => {
    fetchFn(`${base}/v1/videos/${id}`, { method: 'DELETE' })
      .then((x) => onStatus({ note: x.ok ? '서버 작업 취소를 요청했습니다' : '서버가 작업 취소를 지원하지 않습니다' }))
      .catch(() => onStatus({ note: '서버 작업 취소 요청이 닿지 않았습니다' }));
  };
  signal?.addEventListener('abort', onAbort, { once: true });
  try {
    for (;;) {
      if (Date.now() > deadline) throw new GenError(`생성 대기 한도(${conn.timeout}초)를 넘었습니다`);
      const st = await pollJson(fetchFn, `${base}/v1/videos/${id}`, signal, onStatus);
      const s = st.status;
      const done = s === 'completed' || s === 'succeeded';
      onStatus({ stage: s === 'queued' ? 'queue' : done ? 'download' : 'generate', state: s, progress: normProgress(st.progress), backend: 'sglang' });
      if (done) {
        const blob = await (await call(fetchFn, `${base}/v1/videos/${id}/content`, {}, signal)).blob();
        if (blob.size < 1000) throw new GenError(`받은 영상이 너무 작습니다 (${blob.size} bytes)`);
        return blob;
      }
      if (s === 'failed' || s === 'error' || s === 'cancelled') {
        const err = typeof st.error === 'object' && st.error ? st.error.message || JSON.stringify(st.error) : st.error;
        throw new GenError(`서버가 생성에 실패했습니다: ${err || s}`);
      }
      await sleep(pollMs, signal);
    }
  } finally {
    signal?.removeEventListener('abort', onAbort);
  }
}
