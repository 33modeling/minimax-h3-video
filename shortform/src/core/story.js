// JSON 한번에(웹): 동화책 콘티·동화책 만들기 book.json·장면 목록(clips) JSON + 쪽 그림 이름 → 숏폼 명세.
// 규칙은 파이썬 쪽(h3video/story.py 의 장면·길이·프롬프트·그림 맞추기 + shorts/story.py 의 명세·자막)과 같다.
// tests/fixtures/story/ 의 기대 결과를 두 쪽 테스트가 같이 확인한다. 한쪽을 고치면 다른 쪽도 고친다.
// 브라우저에는 파일 경로가 없으므로 JSON 에 적힌 그림 경로는 함께 고른 그림의 이름으로만 맞춘다.

export const DEFAULT_SECONDS = 6;
export const SCENE_MIN = 5;
export const DURATION_MIN = 4;
export const DURATION_MAX = 15;
export const MAX_CLIPS = Infinity;
export const MAX_TOTAL = Infinity;
export const CAPTION_MAX = 120;
const ASPECT_RATIOS = ['16:9', '9:16', '1:1', '4:3', '3:4', '21:9', 'auto'];
const IMAGE_EXTS = ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'];
const HANGUL = /[가-힣]/;
const SHOT = { wide: 'Wide shot: ', medium: 'Medium shot: ', 'close-up': 'Close-up: ', 'bird-eye': "Bird's-eye view: ", 'low-angle': 'Low-angle shot: ', 'over-shoulder': 'Over-the-shoulder shot: ' };

export class StoryError extends Error {}
const isObj = (o) => o !== null && typeof o === 'object' && !Array.isArray(o);
const str = (v) => (v === null || v === undefined ? '' : String(v));
const clean = (s) => str(s).replace(/\s+/g, ' ').trim().replace(/[. ]+$/, '');
const base = (p) => str(p).split(/[\\/]/).pop();
const ext = (p) => { const m = base(p).match(/\.[^.]+$/); return m ? m[0].toLowerCase() : ''; };
const stem = (p) => base(p).replace(/\.[^.]+$/, '');
const noSpace = (t) => str(t).replace(/\s/g, '');
const words = (t) => str(t).trim().split(/\s+/).filter(Boolean);

export function readingSeconds(text) {
  const t = str(text).trim();
  if (!t) return 0;
  return HANGUL.test(t) ? noSpace(t).length / 4 : words(t).length / 2.5;
}

// 전체 장면 길이는 보존한다. 모델 호출은 nativeDurations로 나눈다.
export function autoSeconds(text = '', given = null) {
  if (given !== null && given !== undefined && given !== '') {
    const n = Number(given);
    if (!Number.isFinite(n) || n <= 0) throw new StoryError(`seconds 는 숫자여야 합니다: ${JSON.stringify(given)}`);
    return [Math.max(DURATION_MIN, Math.floor(n + 0.5)), 'JSON'];
  }
  const r = readingSeconds(text);
  if (!r) return [DEFAULT_SECONDS, '기본'];
  const ko = HANGUL.test(text);
  return [Math.max(SCENE_MIN, Math.ceil(r + 1.5)), `글 ${ko ? noSpace(text).length : words(text).length}${ko ? '자' : '단어'}`];
}

export function narrationLine(text) {
  const t = str(text).replace(/\s+/g, ' ').trim().replace(/</g, '‹').replace(/>/g, '›');
  if (!t) return '';
  return ` Voice-over: an off-screen storyteller with a warm, gentle voice reads slowly and clearly <d>[${HANGUL.test(t) ? 'Korean' : 'English'}] ${t}</d>`;
}

export function videoPrompt(scene, { image, style = '', characters = '', text = '', narration = true }) {
  const parts = [`${clean(scene)}.`];
  if (image) {
    parts.push('Bring this picture-book illustration to life with gentle, natural motion: the characters move a little and the camera drifts slowly.'
      + ' Keep the art style and every character exactly as in the first frame.');
  } else {
    if (characters) parts.push(`Characters — ${characters}.`);
    parts.push(`Style: children's picture book illustration${style ? `, ${clean(style)}` : ''}. Gentle, natural motion and a slow camera drift.`);
  }
  parts.push('No on-screen text or captions. Soft, calm background music.');
  return parts.join(' ') + (narration ? narrationLine(text) : '');
}

const bookOf = (o) => (isObj(o) && 'book' in o ? o.book : o);
export function isConti(o) {
  const b = bookOf(o);
  return isObj(b) && Array.isArray(b.pages) && isObj(b.style) && b.pages.some((p) => isObj(p) && typeof p.scene === 'string');
}
export const isMakerBook = (o) => isObj(o) && o.kind === 'batch' && Array.isArray(o.items);
// 숏폼 명세가 아니라 이야기 JSON 인가 (shorts/story.py is_story 와 같음)
// 배열은 장면 목록일 때만 (["프롬프트", {prompt}]) — [1, 2] 같은 건 명세 오류로 알린다
export const isStory = (o) => (Array.isArray(o) ? o.length > 0 && o.every((x) => typeof x === 'string' || (isObj(x) && ('prompt' in x || 'scene' in x)))
  : isObj(o) && (Array.isArray(o.board?.scenes) || isConti(o) || isMakerBook(o) || Array.isArray(o.clips)));

function contiRaw(o) {
  const b = bookOf(o);
  const style = clean((b.style || {}).prompt);
  const chars = {};
  for (const c of b.characters || []) if (isObj(c)) chars[str(c.name)] = clean(c.prompt);
  const raw = [];
  const cover = b.cover || {};
  if (clean(cover.scene)) raw.push({ id: 'cover', label: '표지', scene: `Book cover: ${clean(cover.scene)}`, text: '', chars: cover.characters || [], optional: true, page: 0 });
  (b.pages || []).forEach((p, k) => {
    if (!isObj(p) || !clean(p.scene)) return;
    const n = Number.isInteger(p.page) ? p.page : k + 1;
    raw.push({ id: `page-${String(n).padStart(2, '0')}`, label: `${n}쪽`, page: n, scene: (SHOT[p.shot] || '') + clean(p.scene), text: str(p.text), chars: p.characters || [], seconds: p.seconds });
  });
  for (const r of raw) {
    r.style = style;
    r.characters = r.chars.filter((n) => chars[n]).map((n) => `${n}: ${chars[n]}`).join('; ');
    delete r.chars;
  }
  return [str(b.title) || '동화책', isObj(o.opts) ? o.opts.ratio : null, raw];
}

function makerRaw(o) {
  const style = clean(o.style);
  const raw = [];
  for (const it of o.items) {
    if (!isObj(it) || !['cover', 'page', 'image'].includes(it.kind)) continue;
    raw.push({ id: str(it.id), label: str(it.label || it.id), page: it.page, scene: clean(it.scene || it.prompt), text: str(it.text),
      image: it.image ? str(it.image) : null, style, characters: '', optional: it.kind === 'cover' });
  }
  let ratio = null;
  if (o.width && o.height) {
    const r = o.width / o.height;
    ratio = ['16:9', '9:16', '1:1', '4:3', '3:4', '21:9'].reduce((best, a) => {
      const [x, y] = a.split(':').map(Number);
      return Math.abs(Math.log(r / (x / y))) < Math.abs(Math.log(r / best[1])) ? [a, x / y] : best;
    }, ['16:9', 16 / 9])[0];
  }
  return [str(o.title) || '동화책', ratio, raw];
}

function listRaw(o) {
  const items = Array.isArray(o) ? o : ['clips', 'scenes', 'pages', 'items'].map((k) => o[k]).find(Array.isArray);
  if (!items) throw new StoryError('장면을 찾지 못했습니다: 동화책 콘티 JSON, 동화책 만들기 book.json, 또는 {"clips": [{"prompt": ...}]} 이어야 합니다');
  const raw = items.map((x0, k) => {
    const i = k + 1;
    const x = typeof x0 === 'string' ? { prompt: x0 } : x0;
    if (!isObj(x)) throw new StoryError(`${i}번째 장면이 글이나 객체가 아닙니다`);
    const prompt = str(x.prompt || x.scene).trim();
    if (!prompt) throw new StoryError(`${i}번째 장면에 prompt 가 없습니다`);
    return { id: `clip-${String(i).padStart(2, '0')}`, label: str(x.label || x.name || x.title) || `${i}번`, prompt, text: str(x.text || x.caption),
      image: x.image || x.first || null, seconds: 'seconds' in x ? x.seconds : x.duration, seed: x.seed, page: i };
  });
  return [isObj(o) ? str(o.title) || '영상 묶음' : '영상 묶음', isObj(o) ? o.ratio : null, raw];
}

function numIn(name) {
  const m = stem(name).match(/(?:page|p|쪽|scene|clip)?[-_ ]?0*(\d{1,3})(?!\d)/i);
  return m ? Number(m[1]) : null;
}

// JSON 경로(이름으로) → 파일 이름(cover·숫자) → 남은 그림은 순서대로. 쓰지 않은 그림을 돌려준다.
function matchImages(raw, images) {
  const byName = new Map(images.map((p) => [base(p).toLowerCase(), p]));
  const used = new Set();
  for (const r of raw) {
    if (!r.image) continue;
    const img = str(r.image);
    if (/^https?:\/\//.test(img)) continue;
    const hit = byName.get(base(img).toLowerCase());
    if (!hit) throw new StoryError(`${r.label}: 그림 ${img} 을 찾지 못했습니다 (같은 이름의 그림을 함께 고르세요)`);
    r.image = hit;
    used.add(hit);
  }
  const rest = images.filter((p) => !used.has(p));
  for (const p of [...rest]) {
    const s = stem(p).toLowerCase();
    let target = null;
    if (s.includes('cover') || s.includes('표지')) target = raw.find((r) => r.id === 'cover' && !r.image);
    else {
      const n = numIn(p);
      if (n !== null) target = raw.find((r) => r.page === n && r.id !== 'cover' && !r.image);
    }
    if (target) { target.image = p; rest.splice(rest.indexOf(p), 1); }
  }
  for (const r of raw) {
    if (!rest.length) break;
    if (!r.image && !r.optional) r.image = rest.shift();
  }
  return rest;
}

// 파이썬 h3video.story.load_story(local_paths=False) 와 같은 결과: { title, ratio, source, clips, unused_images }
export function loadStory(data, images = [], { narration = true, ratio = null, seed = 0 } = {}) {
  if (typeof data === 'string') {
    try { data = JSON.parse(data.replace(/^﻿/, '')); } catch (e) { throw new StoryError(`JSON 을 읽을 수 없습니다: ${e.message}`); }
  }
  if(isObj(data)&&Array.isArray(data.board?.scenes))data={title:data.board.title,ratio:data.brief?.ratio,clips:data.board.scenes.map(s=>({prompt:[s.videoPrompt||s.imagePrompt||s.visual,s.negativePrompt?'Avoid: '+s.negativePrompt:''].filter(Boolean).join('\n'),title:s.title,seconds:s.duration,text:s.caption||''}))};
  let source, title, jratio, raw;
  if (isConti(data)) [source, [title, jratio, raw]] = ['conti', contiRaw(data)];
  else if (isMakerBook(data)) [source, [title, jratio, raw]] = ['book', makerRaw(data)];
  else if (Array.isArray(data) || isObj(data)) [source, [title, jratio, raw]] = ['list', listRaw(data)];
  else throw new StoryError('JSON 이 객체나 배열이 아닙니다');
  const unused = matchImages(raw, [...images]);
  for (const r of raw) {
    if (r.image && !/^https?:\/\//.test(r.image) && !IMAGE_EXTS.includes(ext(r.image))) throw new StoryError(`${r.label}: ${base(r.image)} 은 첫 프레임으로 쓸 수 없는 형식입니다 (PNG·JPEG·WebP)`);
  }
  raw = raw.filter((r) => !(r.optional && !r.image));
  if (!raw.length) throw new StoryError('만들 장면이 없습니다');
  if (raw.length > MAX_CLIPS) throw new StoryError(`한 번에 최대 ${MAX_CLIPS}개 장면입니다 (지금 ${raw.length}개)`);
  const clips = raw.map((r, i) => {
    const [seconds, auto] = autoSeconds(r.text || '', r.seconds ?? null);
    let prompt = r.prompt || videoPrompt(r.scene, { image: Boolean(r.image), style: r.style || '', characters: r.characters || '', text: r.text || '', narration });
    if (r.prompt && narration && r.text) prompt += narrationLine(r.text);
    const s = r.seed;
    const seedOk = typeof s === 'number' || (typeof s === 'string' && /^\d+$/.test(s));
    return { id: r.id, label: r.label, prompt, seconds, image: r.image || null, text: r.text || '', page: r.page ?? null, seed: seedOk ? Math.trunc(Number(s)) : seed + i, auto };
  });
  const r0 = ratio || jratio;
  return { title, ratio: ASPECT_RATIOS.includes(r0) ? r0 : clips.some((c) => c.image) ? 'auto' : '16:9', source, clips, unused_images: unused };
}

const r3 = (x) => Math.floor(x * 1000 + 0.5) / 1000;

export function captionPieces(text) {
  const out = [];
  for (const line0 of str(text).split(/\n+/)) {
    const line = line0.replace(/\s+/g, ' ').trim();
    if (!line) continue;
    const parts = line.length <= CAPTION_MAX ? [line] : line.split(/(?<=[.!?。…])\s+/);
    for (let part of parts) {
      while (part.length > CAPTION_MAX) {
        let cut = part.lastIndexOf(' ', CAPTION_MAX - 1);
        cut = cut > 0 ? cut : CAPTION_MAX;
        out.push(part.slice(0, cut).trim());
        part = part.slice(cut).trim();
      }
      if (part) out.push(part);
    }
  }
  return out;
}

export function slug(title) {
  return str(title).trim().replace(/[\\/:*?"<>|\s]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'short';
}

export function nativeDurations(total) {
  if (total <= DURATION_MAX) return [total];
  const count = Math.min(Math.ceil(total / 10), Math.floor(total / SCENE_MIN));
  const base = Math.floor(total / count), remainder = total % count;
  return Array.from({length:count},(_,i)=>base+(i<remainder?1:0));
}

// 반환: { spec, info: { title, source, total, unused_images, clips: [{id, label, seconds, image, auto}] } }
export function storyToSpec(data, images = [], opts = {}) {
  const story = loadStory(data, images, opts);
  let secs = story.clips.map((c) => c.seconds);
  let total = secs.reduce((a, b) => a + b, 0);
  const scenes = [];
  const captions = [];
  let t = 0;
  story.clips.forEach((c, i) => {
    const sec = secs[i];
    nativeDurations(sec).forEach((duration,part)=>{
      const sc = { prompt: c.prompt, duration, seed: c.seed + part };
      if (c.image) sc.image = c.image;
      scenes.push(sc);
    });
    const pieces = captionPieces(c.text);
    const weights = pieces.map((p) => 2 + noSpace(p).length);
    const sum = weights.reduce((a, b) => a + b, 0);
    let acc = 0;
    pieces.forEach((p, k) => {
      const start = r3(t + (sec * acc) / sum);
      acc += weights[k];
      captions.push({ text: p, start, end: r3(t + (sec * acc) / sum) });
    });
    t += sec;
  });
  const spec = { scenes, ratio: story.ratio, template: 'montage', fit: 'blur', title: story.title, max_duration: 0, output: `${slug(story.title)}.mp4` };
  if (captions.length) spec.captions = captions;
  const info = { title: story.title, source: story.source, total, unused_images: story.unused_images,
    clips: story.clips.map((c, i) => ({ id: c.id, label: c.label, seconds: secs[i], image: c.image, auto: c.auto })) };
  return { spec, info };
}
