// 타임라인·배치 계획. 순수 함수만 둔다. shorts/plan.py 가 같은 계산을 한 줄씩 따라 한다
// (tests/unit/parity.test.mjs 가 두 결과를 비교). 숫자 연산 순서를 바꾸면 둘 다 바꿀 것.

export const FPS = 30; // 기본 출력 fps (spec.fps 로 바꿈)
// 출력 품질: CLI 는 x264 crf, 웹은 픽셀·프레임당 비트(bpp)로 비트레이트를 정한다.
export const QUALITY = { low: { crf: 28, bpp: 0.05 }, medium: { crf: 23, bpp: 0.08 }, high: { crf: 18, bpp: 0.13 } };

export function qualityFor(name, W, H, fps) {
  const q = QUALITY[name] || QUALITY.medium;
  return { name: QUALITY[name] ? name : 'medium', crf: q.crf, bitrate: Math.round((W * H * fps * q.bpp) / 1000) * 1000 };
}
export const TEMPLATES = ['cutaway', 'split', 'pip', 'montage'];
export const TEMPLATE_KO = { cutaway: '컷어웨이', split: '위아래 분할', pip: 'PIP', montage: '몽타주', base: '기본 영상만' };
const CUTAWAY_MAX_SHARE = 0.6;


export const r3 = (x) => Math.round(x * 1000) / 1000;
export const jsRound = (x) => Math.round(x);
export const even = (x) => 2 * Math.round(x / 2);

export function parseResolution(r) {
  const [w, h] = String(r).split('x').map(Number);
  return { width: w, height: h };
}

export function effRange(media, info) {
  const start = Math.min(Math.max(media.start || 0, 0), info.duration);
  const end = media.end == null ? info.duration : Math.min(media.end, info.duration);
  return { start: r3(start), dur: r3(Math.max(0, end - start)) };
}

// 원본(srcW×srcH)을 rect 에 넣는 두 방식의 좌표. cover=가운데 잘라 채우기, contain=전체가 보이게.
export function fitGeometry(srcW, srcH, rect) {
  const sc = Math.max(rect.w / srcW, rect.h / srcH);
  const sw = Math.min(srcW, even(rect.w / sc));
  const sh = Math.min(srcH, even(rect.h / sc));
  const cover = { sx: Math.floor((srcW - sw) / 2), sy: Math.floor((srcH - sh) / 2), sw, sh };
  const sc2 = Math.min(rect.w / srcW, rect.h / srcH);
  const cw = Math.min(rect.w, even(srcW * sc2));
  const ch = Math.min(rect.h, even(srcH * sc2));
  const contain = { x: rect.x + Math.floor((rect.w - cw) / 2), y: rect.y + Math.floor((rect.h - ch) / 2), w: cw, h: ch };
  return { cover, contain };
}

function segment(kind, index, t0, t1, src, rect, fit, info, z, border = 0) {
  const geom = fitGeometry(info.width, info.height, rect);
  // 원본 비율이 칸과 거의 같으면 흐린 배경이 보일 틈이 없으니 잘라 채우기로 처리
  const effFit = fit === 'blur' && (geom.contain.w < rect.w - 2 || geom.contain.h < rect.h - 2) ? 'blur' : 'crop';
  return { kind, index, t0, t1, src, rect, fit: effFit, srcW: info.width, srcH: info.height, cover: geom.cover, contain: geom.contain, z, border };
}

// ---------- 자막·제목 ----------
export function isWide(code) {
  return (
    (code >= 0x1100 && code <= 0x115f) ||
    (code >= 0x2e80 && code <= 0xa4cf) ||
    (code >= 0xac00 && code <= 0xd7a3) ||
    (code >= 0xf900 && code <= 0xfaff) ||
    (code >= 0xfe30 && code <= 0xfe4f) ||
    (code >= 0xff00 && code <= 0xff60) ||
    (code >= 0xffe0 && code <= 0xffe6) ||
    code >= 0x1f300
  );
}

export function charUnits(ch) {
  const code = ch.codePointAt(0);
  if (ch === ' ' || ch === '\t') return 0.3;
  if (isWide(code)) return 1.0;
  if ((code >= 0x41 && code <= 0x5a) || (code >= 0x30 && code <= 0x39)) return 0.62;
  return 0.56;
}

export function textUnits(s) {
  let u = 0;
  for (const ch of s) u += charUnits(ch);
  return u;
}

// 글자 폭을 어림해 줄을 나눈다(웹 canvas 와 ffmpeg drawtext 가 같은 줄바꿈을 쓰도록 측정 대신 어림값).
export function wrapText(text, fontSize, maxWidth, maxLines) {
  const limit = maxWidth / fontSize;
  const words = String(text).trim().split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = '';
  let curU = 0;
  const pushChars = (word) => {
    for (const ch of word) {
      const u = charUnits(ch);
      if (cur && curU + u > limit) {
        lines.push(cur);
        cur = '';
        curU = 0;
      }
      cur += ch;
      curU += u;
    }
  };
  for (const w of words) {
    const wu = textUnits(w);
    if (!cur) {
      if (wu <= limit) {
        cur = w;
        curU = wu;
      } else pushChars(w);
    } else if (curU + 0.3 + wu <= limit) {
      cur += ' ' + w;
      curU += 0.3 + wu;
    } else {
      lines.push(cur);
      cur = '';
      curU = 0;
      if (wu <= limit) {
        cur = w;
        curU = wu;
      } else pushChars(w);
    }
  }
  if (cur) lines.push(cur);
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines);
    let last = kept[maxLines - 1];
    const chars = [...last];
    while (chars.length && textUnits(chars.join('')) + 1 > limit) chars.pop();
    kept[maxLines - 1] = chars.join('') + '…';
    return kept;
  }
  return lines;
}

export function countChars(text) {
  return [...String(text).replace(/\s/g, '')].length;
}

// 자막 시간 자동 배분: 글자 수(+2)에 비례. start/end 를 직접 준 줄은 그 값을 쓴다.
export function timeCaptions(captions, T) {
  const items = captions.map((c) => (typeof c === 'string' ? { text: c } : c));
  const weights = items.map((c) => 2 + countChars(c.text));
  const total = weights.reduce((a, b) => a + b, 0);
  const out = [];
  let acc = 0;
  items.forEach((c, i) => {
    let start = r3((T * acc) / total);
    acc += weights[i];
    let end = r3((T * acc) / total);
    if (c.start != null) start = r3(Math.min(Math.max(c.start, 0), T));
    if (c.end != null) end = r3(Math.min(Math.max(c.end, 0), T));
    if (end - start >= 0.05) out.push({ text: c.text, start, end, auto: c.start == null && c.end == null });
  });
  return out;
}

// 글자 크기 기준 폭: 세로 화면은 가로 폭, 정사각·가로 화면은 높이의 3/4 (16:9 에서 글자가 너무 커지지 않게)
export function textBase(W, H) {
  return Math.min(W, Math.round(H * 0.75));
}

export function textStyle(W, H, template) {
  const U = textBase(W, H);
  const capFs = even(U * 0.056);
  const titleFs = even(U * 0.07);
  return {
    caption: {
      fontSize: capFs,
      lineHeight: Math.round(capFs * 1.28),
      maxWidth: Math.round(W * 0.86),
      centerY: template === 'split' && W <= H ? Math.round(H * 0.5) : Math.round(H * (W > H ? 0.82 : 0.74)),
      maxLines: 3,
      border: Math.max(2, Math.round(U * 0.0075)),
      color: '#ffffff',
      borderColor: '#000000',
    },
    title: {
      fontSize: titleFs,
      lineHeight: Math.round(titleFs * 1.25),
      maxWidth: Math.round(W * 0.88),
      top: Math.round(H * 0.065),
      pad: Math.round(titleFs * 0.3),
      gap: Math.round(titleFs * 0.12),
      maxLines: 2,
      color: '#ffe14d',
      box: 'rgba(0,0,0,0.6)',
    },
  };
}

export function layoutCaption(text, W, st) {
  const lines = wrapText(text, st.fontSize, st.maxWidth, st.maxLines);
  const n = lines.length;
  const first = st.centerY - ((n - 1) * st.lineHeight) / 2;
  return lines.map((t, i) => ({ text: t, cx: Math.round(W / 2), cy: Math.round(first + i * st.lineHeight) }));
}

export function layoutTitle(text, W, st) {
  if (!text || !String(text).trim()) return [];
  const lines = wrapText(text, st.fontSize, st.maxWidth, st.maxLines);
  const step = st.lineHeight + 2 * st.pad + st.gap;
  return lines.map((t, i) => ({ text: t, cx: Math.round(W / 2), cy: Math.round(st.top + st.pad + st.lineHeight / 2 + i * step) }));
}

// ---------- 타임라인 ----------
// inputs = { base: {media:{path,start,end}, info:{duration,width,height,hasAudio}} | null,
//            clips: [{media, info}], bgm: {path, info:{duration}} | null }
export function planTimeline(spec, inputs) {
  const { width: W, height: H } = parseResolution(spec.resolution);
  const warnings = [];
  const ov = spec.original_volume;
  const full = { x: 0, y: 0, w: W, h: H };
  const base = inputs.base ? { ...effRange(inputs.base.media, inputs.base.info), info: inputs.base.info } : null;
  const clips = [];
  inputs.clips.forEach((c, i) => {
    const r = effRange(c.media, c.info);
    if (r.dur >= 0.1 && c.info.width > 0) clips.push({ ...r, info: c.info, index: i });
    else warnings.push(`소스 ${i + 1}: 길이가 너무 짧거나 영상이 없어 뺍니다`);
  });
  let template = spec.template;
  if (!base && template !== 'montage') {
    warnings.push(`기본 영상(base)이 없어 '${template}' 대신 몽타주로 만듭니다`);
    template = 'montage';
  }
  if (base && !clips.length) template = 'base';
  if (!base && !clips.length) throw new Error('합성할 영상이 없습니다');
  const sumClips = clips.reduce((a, c) => a + c.dur, 0);
  let T = template === 'montage' ? Math.min(spec.max_duration > 0 ? spec.max_duration : Infinity, sumClips) : Math.min(spec.max_duration > 0 ? spec.max_duration : Infinity, base.dur);
  T = r3(T);
  // 기본 영상 구간이 비면(start 가 영상 길이보다 뒤 등) 0초짜리 빈 파일을 '완성'이라고 내던 것을 막는다
  if (T < 0.1) throw new Error(`기본 영상에서 쓸 구간이 없습니다: start/end 가 영상 길이(${base.info.duration.toFixed(1)}초) 밖입니다`);
  const segments = [];
  const audio = [];
  const baseAudio = () => {
    if (base && base.info.hasAudio) audio.push({ kind: 'base', index: 0, t0: 0, t1: T, src: base.start, gain: ov, loop: false });
  };
  const sequential = (rect, z, loop, border) => {
    let t = 0;
    let i = 0;
    while (t < T - 0.05) {
      if (!loop && i >= clips.length) break;
      const c = clips[i % clips.length];
      const d = Math.min(c.dur, T - t);
      const t1 = r3(t + d);
      segments.push(segment('clip', c.index, r3(t), t1, c.start, rect, spec.fit, c.info, z, border));
      t = t1;
      i += 1;
    }
  };

  if (template === 'base') {
    segments.push(segment('base', 0, 0, T, base.start, full, spec.fit, base.info, 0));
    baseAudio();
  } else if (template === 'cutaway') {
    segments.push(segment('base', 0, 0, T, base.start, full, spec.fit, base.info, 0));
    baseAudio();
    let durs = clips.map((c) => c.dur);
    const C = durs.reduce((a, b) => a + b, 0);
    const cap = T * CUTAWAY_MAX_SHARE;
    if (C > cap) durs = durs.map((d) => r3((d * cap) / C));
    const used = durs.reduce((a, b) => a + b, 0);
    const gap = (T - used) / (clips.length + 1);
    let acc = 0;
    clips.forEach((c, i) => {
      const t0 = r3(gap * (i + 1) + acc);
      acc += durs[i];
      const t1 = r3(Math.min(T, t0 + durs[i]));
      if (t1 - t0 >= 0.05) segments.push(segment('clip', c.index, t0, t1, c.start, full, spec.fit, c.info, 1));
    });
  } else if (template === 'split') {
    if (W > H) {
      // 가로 화면: 왼쪽 기본 영상, 오른쪽 소스
      const half = even(W / 2);
      segments.push(segment('base', 0, 0, T, base.start, { x: 0, y: 0, w: half, h: H }, spec.fit, base.info, 0));
      sequential({ x: half, y: 0, w: W - half, h: H }, 1, true, 0);
    } else {
      // 세로·정사각: 위 기본 영상, 아래 소스
      const half = even(H / 2);
      segments.push(segment('base', 0, 0, T, base.start, { x: 0, y: 0, w: W, h: half }, spec.fit, base.info, 0));
      sequential({ x: 0, y: half, w: W, h: H - half }, 1, true, 0);
    }
    baseAudio();
  } else if (template === 'pip') {
    segments.push(segment('base', 0, 0, T, base.start, full, spec.fit, base.info, 0));
    const pw = even(Math.min(W * 0.42, H * 0.6));
    const ph = even((pw * 9) / 16);
    const rect = { x: W - pw - Math.round(W * 0.045), y: Math.round(H * 0.24), w: pw, h: ph };
    sequential(rect, 1, true, Math.max(2, Math.round(textBase(W, H) * 0.006)));
    baseAudio();
  } else {
    sequential(full, 0, false, 0);
    if (base && base.info.hasAudio) baseAudio();
    else {
      segments.forEach((s) => {
        const c = clips.find((x) => x.index === s.index);
        if (c.info.hasAudio) audio.push({ kind: 'clip', index: s.index, t0: s.t0, t1: s.t1, src: s.src, gain: ov, loop: false });
      });
    }
  }
  if (inputs.bgm && spec.bgm_volume > 0) {
    audio.push({ kind: 'bgm', index: 0, t0: 0, t1: T, src: 0, gain: spec.bgm_volume, loop: true });
  }
  const style = textStyle(W, H, template);
  const captions = timeCaptions(spec.captions || [], T).map((c) => ({ ...c, lines: layoutCaption(c.text, W, style.caption) }));
  const title = layoutTitle(spec.title, W, style.title);
  const fps = spec.fps || FPS;
  const quality = qualityFor(spec.quality, W, H, fps);
  return { width: W, height: H, fps, duration: T, template, segments, audio, captions, title, style, quality, warnings };
}

// 사람이 읽는 한 줄 요약(웹 화면과 CLI --dry-run 이 같은 문장을 쓴다)
export function describePlan(plan) {
  const segs = plan.segments.filter((s) => s.kind === 'clip').length;
  return `${TEMPLATE_KO[plan.template]} · ${plan.width}×${plan.height} · ${plan.fps}fps · 품질 ${plan.quality.name} · ${plan.duration.toFixed(1)}초 · 소스 구간 ${segs}개 · 자막 ${plan.captions.length}줄`;
}
