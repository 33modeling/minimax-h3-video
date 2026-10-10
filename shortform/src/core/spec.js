// 작업 명세(JSON) 검증·정규화. shorts/spec.py 와 같은 규칙을 쓴다(테스트가 둘을 맞대어 본다).
import schema from '../../schema/job.schema.json' with { type: 'json' };

export { schema };

export const DEFAULTS = {
  version: 1,
  duration: 8,
  ratio: '9:16',
  seed: 0,
  backend: 'auto',
  poll: 3,
  timeout: 1800,
  fit: 'blur',
  resolution: '720x1280',
  fps: 30,
  quality: 'medium',
  max_duration: 60,
  title: '',
  bgm_volume: 0.25,
  original_volume: 1,
  output: 'short.mp4',
};

// H3 ref2va 제한 (minimax-h3-video spec.REF_LIMITS 와 같음)
export const REF_LIMITS = { image: 9, video: 3, audio: 3, total: 12 };
export const RESOLUTION_PRESETS = schema.properties.resolution['x-presets'];
export const SIZE_MIN = 240;
export const SIZE_MAX = 2160; // 짧은 변 상한
export const LONG_MAX = 2560; // 긴 변 상한 (1440x2560 프리셋)
export const H3_MAX_SHORT_EDGE = 768;
export const GEN_FPS = 24; // H3 생성은 24fps 고정, 출력 fps 는 합성 단계에서 맞춘다

// "WxH" → {width, height} (형식이 틀리면 null)
export function parseSize(v) {
  const m = /^([0-9]+)x([0-9]+)$/.exec(String(v));
  return m ? { width: Number(m[1]), height: Number(m[2]) } : null;
}

// 짝수·범위 검사. 오류 문장 목록을 돌려준다.
export function checkSize(name, w, h) {
  const errs = [];
  const shown = h == null ? `${w}` : `${w}x${h}`;
  const vals = h == null ? [w] : [w, h];
  if (vals.some((x) => x % 2 !== 0)) errs.push(`${name}: ${h == null ? '' : '가로·세로는 '}짝수여야 합니다 (지금 ${shown})`);
  if (h == null) {
    if (w < SIZE_MIN || w > SIZE_MAX) errs.push(`${name}: ${SIZE_MIN}~${SIZE_MAX} 사이여야 합니다 (지금 ${shown})`);
  } else if (Math.min(w, h) < SIZE_MIN || Math.min(w, h) > SIZE_MAX || Math.max(w, h) > LONG_MAX) {
    errs.push(`${name}: 짧은 변은 ${SIZE_MIN}~${SIZE_MAX}, 긴 변은 ${LONG_MAX} 이하여야 합니다 (지금 ${shown})`);
  }
  return errs;
}

// gen_size 의 짧은 변(px). 없으면 null.
export function genShortEdge(g) {
  if (g == null) return null;
  if (typeof g === 'number') return g;
  const s = parseSize(g);
  return s ? Math.min(s.width, s.height) : null;
}

const TYPE_KO = {
  string: '문자열이어야',
  number: '숫자여야',
  integer: '정수여야',
  boolean: 'true 또는 false여야',
  array: '목록([...])이어야',
  object: '객체({...})여야',
};

function typeOf(v) {
  if (Array.isArray(v)) return 'array';
  if (v === null) return 'null';
  if (typeof v === 'number') return Number.isInteger(v) ? 'integer' : 'number';
  return typeof v;
}

function typeMatches(t, v) {
  const k = typeOf(v);
  return t === k || (t === 'number' && k === 'integer');
}

export function fmtValue(v) {
  // 글자 수는 코드 포인트로 센다(파이썬 len 과 같게 — 이모지가 UTF-16 두 칸이라 자르는 자리가 달랐다)
  const cs = [...JSON.stringify(v)];
  return cs.length > 40 ? cs.slice(0, 37).join('') + '...' : cs.join('');
}

function resolveRef(root, ref) {
  return ref.slice(2).split('/').reduce((o, k) => o[k], root);
}

function editDistance(a, b) {
  const dp = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
  for (let j = 1; j <= b.length; j++) dp[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
  }
  return dp[a.length][b.length];
}

function label(path, sch) {
  const p = path || '(전체)';
  return sch && sch.title ? `${p} [${sch.title}]` : p;
}

// 작은 JSON Schema 검사기: type, enum, minimum/maximum, minLength/maxLength, pattern,
// minItems/maxItems, items, properties, required, additionalProperties:false, anyOf, $ref.
export function validateSchema(value, sch = schema, path = '', root = schema, errors = [], parentTitle = null) {
  if (sch.$ref) {
    const target = resolveRef(root, sch.$ref);
    return validateSchema(value, { ...target, title: sch.title || parentTitle || target.title }, path, root, errors);
  }
  const at = label(path, sch.title ? sch : parentTitle ? { title: parentTitle } : null);
  if (sch.anyOf) {
    const ok = sch.anyOf.some((s) => validateSchema(value, s, path, root, []).length === 0);
    if (!ok) {
      const branch = sch.anyOf.find((s) => s.type && typeMatches(s.type, value));
      if (branch) return validateSchema(value, branch, path, root, errors, sch.title);
      errors.push(`${at}: 형식이 맞지 않습니다. ${sch['x-hint'] || ''} 형태로 적어 주세요 (지금 ${fmtValue(value)})`);
    }
    return errors;
  }
  if (sch.type && !typeMatches(sch.type, value)) {
    errors.push(`${at}: ${TYPE_KO[sch.type]} 합니다 (지금 ${fmtValue(value)})`);
    return errors;
  }
  if (sch.enum && !sch.enum.includes(value)) {
    errors.push(`${at}: ${sch.enum.map((x) => JSON.stringify(x)).join(', ')} 중 하나여야 합니다 (지금 ${fmtValue(value)})`);
  }
  if (typeof value === 'string') {
    if (sch.minLength && value.trim().length < sch.minLength) errors.push(`${at}: 비어 있으면 안 됩니다`);
    if (sch.maxLength && [...value].length > sch.maxLength) {
      errors.push(`${at}: ${sch.maxLength}자 이하여야 합니다 (지금 ${[...value].length}자)`);
    }
    if (sch.pattern && !new RegExp(sch.pattern).test(value)) {
      errors.push(`${at}: ${sch['x-pattern'] || '형식이 맞아야'} 합니다 (지금 ${fmtValue(value)})`);
    }
  }
  if (typeof value === 'number') {
    if (sch.minimum !== undefined && value < sch.minimum) errors.push(`${at}: ${sch.minimum} 이상이어야 합니다 (지금 ${fmtValue(value)})`);
    if (sch.maximum !== undefined && value > sch.maximum) errors.push(`${at}: ${sch.maximum} 이하여야 합니다 (지금 ${fmtValue(value)})`);
  }
  if (Array.isArray(value)) {
    if (sch.minItems && value.length < sch.minItems) errors.push(`${at}: 최소 ${sch.minItems}개가 필요합니다`);
    if (sch.maxItems !== undefined && value.length > sch.maxItems) {
      errors.push(`${at}: 최대 ${sch.maxItems}개까지 넣을 수 있습니다 (지금 ${value.length}개)`);
    }
    if (sch.items) value.forEach((v, i) => validateSchema(v, sch.items, `${path}[${i}]`, root, errors, sch.title));
  }
  if (typeOf(value) === 'object') {
    for (const key of sch.required || []) {
      if (!(key in value)) errors.push(`${at}: '${key}' 항목이 필요합니다`);
    }
    const props = sch.properties || {};
    for (const [key, v] of Object.entries(value)) {
      const sub = path ? `${path}.${key}` : key;
      if (props[key]) validateSchema(v, props[key], sub, root, errors);
      else if (sch.additionalProperties === false) {
        const names = Object.keys(props).filter((n) => n !== '$schema');
        const best = names.map((n) => [editDistance(key, n), n]).sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : 1))[0];
        const hint = best && best[0] <= 3 ? ` 혹시 '${best[1]}' 인가요?` : '';
        errors.push(`${sub}: 알 수 없는 항목입니다.${hint}`);
      }
    }
  }
  return errors;
}

export function mediaPath(m) {
  return typeof m === 'string' ? m : m && m.path;
}

export function normMedia(m) {
  if (m == null) return null;
  if (typeof m === 'string') return { path: m, start: 0, end: null };
  return { path: m.path, start: m.start ?? 0, end: m.end ?? null };
}

export function baseName(p) {
  return String(p).split(/[\\/]/).pop();
}

// 명세가 가리키는 파일 이름들(웹에서 파일을 맞출 때, CLI 에서 두 번째 파일을 맞출 때 쓴다)
export function referencedPaths(spec) {
  const out = [];
  const add = (p) => p && !out.includes(p) && out.push(p);
  add(mediaPath(spec.base));
  (spec.sources || []).forEach((m) => add(mediaPath(m)));
  (spec.scenes || []).forEach((s) => {
    (s.sources || []).forEach((m) => add(mediaPath(m)));
    add(s.image);
  });
  add(spec.image);
  add(spec.bgm);
  return out;
}

// 두 번째 파일(소스 영상): 명세가 이름으로 가리키는 파일이면 그 자리에, 아니면 sources 에 붙인다.
export function attachFiles(spec, names) {
  const next = JSON.parse(JSON.stringify(spec));
  const refs = referencedPaths(next).map(baseName);
  for (const name of names) {
    if (refs.includes(baseName(name))) continue;
    next.sources = [...(next.sources || []), name];
  }
  return next;
}

function checkRange(m, path, errors) {
  if (m && typeof m === 'object' && m.start != null && m.end != null && m.end <= m.start) {
    errors.push(`${path}: end(${m.end})는 start(${m.start})보다 커야 합니다`);
  }
}

export function aiScenes(spec) {
  const n = normalizeSpec(spec);
  if (n.scenes) {
    return n.scenes.map((s, i) => makeScene(s.prompt, s.sources ?? n.sources, s.image ?? (i === 0 ? n.image : null), s.duration ?? n.duration, s.seed ?? n.seed + i));
  }
  if (n.prompt) return [makeScene(n.prompt, n.sources, n.image, n.duration, n.seed)];
  return [];
}

function makeScene(prompt, sources, image, duration, seed) {
  const refs = (sources || []).map(normMedia);
  const task = refs.length ? 'ref2va' : image ? 'fl2va' : 't2va';
  return { prompt, sources: refs, image: image || null, duration, seed, task };
}

// 의미 검사(스키마를 통과한 뒤). 반환: { errors, warnings }
export function checkSpec(spec) {
  const errors = validateSchema(spec);
  const warnings = [];
  if (errors.length) return { errors, warnings };
  const usesAi = !!(spec.prompt || spec.scenes);
  if (spec.prompt && spec.scenes) errors.push('prompt 와 scenes 는 함께 쓸 수 없습니다. 장면이 여러 개면 scenes 만 쓰세요');
  if (!usesAi && !spec.base && !(spec.sources && spec.sources.length)) {
    errors.push('만들 재료가 없습니다: prompt(AI 생성) 또는 base·sources(소스 영상) 중 하나는 있어야 합니다. 소스 영상은 두 번째 파일로 넘겨도 됩니다');
  }
  if (spec.resolution) {
    const r = parseSize(spec.resolution);
    errors.push(...checkSize('resolution', r.width, r.height));
  }
  if (spec.gen_size != null) {
    const g = typeof spec.gen_size === 'number' ? null : parseSize(spec.gen_size);
    errors.push(...(g ? checkSize('gen_size', g.width, g.height) : checkSize('gen_size', spec.gen_size, null)));
  }
  checkRange(spec.base, 'base', errors);
  (spec.sources || []).forEach((m, i) => checkRange(m, `sources[${i}]`, errors));
  (spec.scenes || []).forEach((s, i) => (s.sources || []).forEach((m, j) => checkRange(m, `scenes[${i}].sources[${j}]`, errors)));
  (spec.captions || []).forEach((c, i) => {
    if (typeof c === 'object' && c.start != null && c.end != null && c.end <= c.start) {
      errors.push(`captions[${i}]: end(${c.end})는 start(${c.start})보다 커야 합니다`);
    }
  });
  if (usesAi && !errors.length) {
    aiScenes(spec).forEach((sc, i) => {
      const videos = sc.sources.filter((m) => !isImagePath(m.path)).length;
      const images = sc.sources.length - videos + (sc.task === 'ref2va' && sc.image ? 1 : 0);
      const where = spec.scenes ? `scenes[${i}]` : 'sources';
      if (videos > REF_LIMITS.video) errors.push(`${where}: 참조 영상은 최대 ${REF_LIMITS.video}개입니다 (지금 ${videos}개)`);
      if (images > REF_LIMITS.image) errors.push(`${where}: 참조 이미지는 최대 ${REF_LIMITS.image}개입니다 (지금 ${images}개)`);
      if (videos + images > REF_LIMITS.total) errors.push(`${where}: 참조는 합계 ${REF_LIMITS.total}개 이하여야 합니다`);
      if ((spec.backend === 'vllm') && videos + images > 1) warnings.push(`${where}: vLLM 서버는 참조를 1개만 받습니다. 첫 번째만 보냅니다`);
    });
    if ((spec.sources || []).length) warnings.push('prompt 가 있어 sources 는 AI 참조 입력으로 씁니다');
    const se = genShortEdge(spec.gen_size);
    if (se != null && se > H3_MAX_SHORT_EDGE) {
      warnings.push(`gen_size: 짧은 변 ${se}px 은 로컬 H3 상한 ${H3_MAX_SHORT_EDGE}px 을 넘습니다. H3 서버(sglang·h3video)로는 보내기 전에 막습니다`);
    }
    const gs = typeof spec.gen_size === 'string' ? parseSize(spec.gen_size) : null;
    const ratio = spec.ratio || DEFAULTS.ratio;
    if (gs && ratio !== 'auto') {
      const [a, b] = ratio.split(':').map(Number);
      if (Math.abs(gs.width / gs.height - a / b) > 0.02 * (a / b)) {
        warnings.push(`gen_size ${spec.gen_size} 의 비율이 ratio ${ratio} 와 다릅니다. H3 는 ratio 와 짧은 변(${se}px)만 씁니다`);
      }
    }
  }
  const tpl = spec.template;
  const hasBase = !!spec.base;
  if (tpl && tpl !== 'montage' && !hasBase) warnings.push(`기본 영상(base)이 없어 '${tpl}' 대신 몽타주로 만듭니다`);
  return { errors, warnings };
}

export function isImagePath(p) {
  return /\.(png|jpe?g|webp|gif|bmp)$/i.test(String(p));
}

export function normalizeSpec(spec) {
  const s = { ...DEFAULTS, ...spec };
  s.prompt = spec.prompt || null;
  s.scenes = spec.scenes ? spec.scenes.map((x) => ({ ...x })) : null;
  s.sources = (spec.sources || []).map(normMedia);
  s.base = normMedia(spec.base);
  s.image = spec.image || null;
  s.bgm = spec.bgm || null;
  s.server = spec.server || null;
  s.ref_server = spec.ref_server || null;
  s.model = spec.model || null;
  s.captions = (spec.captions || []).map((c) => (typeof c === 'string' ? { text: c } : { ...c }));
  s.template = spec.template || (s.base ? 'cutaway' : 'montage');
  s.usesAi = !!(s.prompt || s.scenes);
  return s;
}

// 합성 재료: AI 를 쓰면 생성 영상들이 소스, 아니면 명세의 sources.
export function composeInputs(spec, generated = []) {
  const n = normalizeSpec(spec);
  const clips = n.usesAi ? generated.map((p) => ({ path: p, start: 0, end: null })) : n.sources;
  return { base: n.base, clips, bgm: n.bgm };
}
