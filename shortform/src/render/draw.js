// 한 프레임 그리기. 미리보기·내보내기·실시간 녹화가 모두 이 함수를 쓴다.
// 좌표는 plan 의 출력 픽셀 좌표 그대로이고, 미리보기는 ctx 변환으로 줄여 그린다.
// WebGL 은 쓰지 않는다(사용자 GPU 가 약함) — canvas 2D 와 작은 캔버스 확대로 흐림을 낸다.

export const FONT_STACK = '"SamsungOne", "Noto Sans CJK KR", "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif';
const BLUR_DIV = 16; // shorts/render.py 와 같은 값
const DARKEN_ALPHA = 0.3; // render.py DARKEN 0.7 과 같은 밝기

// 세그먼트마다 프레임 번호 범위 [k0, k1) 를 붙여 z·시작 순으로 정렬한다.
export function prepareSegments(plan) {
  const fps = plan.fps;
  return plan.segments
    .map((s, id) => ({ ...s, id, k0: Math.ceil(s.t0 * fps - 1e-6), k1: Math.ceil(s.t1 * fps - 1e-6) }))
    .filter((s) => s.k1 > s.k0)
    .sort((a, b) => a.z - b.z || a.t0 - b.t0);
}

export function frameCount(plan) {
  return Math.max(1, Math.round(plan.duration * plan.fps));
}

export function activeAt(segs, k) {
  return segs.filter((s) => k >= s.k0 && k < s.k1);
}

// 세그먼트 안에서 프레임 k 가 가리키는 원본 시각(초)
export function srcTime(seg, k, fps) {
  return Math.max(0, seg.src + k / fps - seg.t0);
}

function drawSegment(ctx, seg, d, scratch) {
  const r = seg.rect;
  const c = seg.cover;
  const n = seg.contain;
  const b = seg.border || 0;
  const kx = d.w / seg.srcW;
  const ky = d.h / seg.srcH;
  if (b) {
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(r.x - b, r.y - b, r.w + 2 * b, r.h + 2 * b);
  }
  if (seg.fit === 'blur') {
    const bw = Math.max(2, Math.floor(r.w / BLUR_DIV));
    const bh = Math.max(2, Math.floor(r.h / BLUR_DIV));
    if (scratch.width !== bw || scratch.height !== bh) {
      scratch.width = bw;
      scratch.height = bh;
    }
    const sctx = scratch.getContext('2d');
    sctx.imageSmoothingEnabled = true;
    sctx.imageSmoothingQuality = 'medium';
    sctx.drawImage(d.img, c.sx * kx, c.sy * ky, c.sw * kx, c.sh * ky, 0, 0, bw, bh);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'low';
    ctx.drawImage(scratch, 0, 0, bw, bh, r.x, r.y, r.w, r.h);
    ctx.fillStyle = `rgba(0,0,0,${DARKEN_ALPHA})`;
    ctx.fillRect(r.x, r.y, r.w, r.h);
    ctx.imageSmoothingQuality = 'medium';
    ctx.drawImage(d.img, 0, 0, d.w, d.h, n.x, n.y, n.w, n.h);
  } else {
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'medium';
    ctx.drawImage(d.img, c.sx * kx, c.sy * ky, c.sw * kx, c.sh * ky, r.x, r.y, r.w, r.h);
  }
}

function drawTitle(ctx, plan) {
  const st = plan.style.title;
  if (!plan.title.length) return;
  ctx.font = `700 ${st.fontSize}px ${FONT_STACK}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (const ln of plan.title) {
    const w = ctx.measureText(ln.text).width;
    ctx.fillStyle = st.box;
    ctx.fillRect(Math.round(ln.cx - w / 2 - st.pad), Math.round(ln.cy - st.lineHeight / 2 - st.pad), Math.round(w + 2 * st.pad), st.lineHeight + 2 * st.pad);
    ctx.fillStyle = st.color;
    ctx.fillText(ln.text, ln.cx, ln.cy);
  }
}

function drawCaptions(ctx, plan, t) {
  const st = plan.style.caption;
  const cur = plan.captions.filter((c) => t >= c.start && t < c.end);
  if (!cur.length) return;
  ctx.font = `700 ${st.fontSize}px ${FONT_STACK}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.lineJoin = 'round';
  ctx.miterLimit = 2;
  for (const c of cur) {
    for (const ln of c.lines) {
      ctx.lineWidth = st.border * 2;
      ctx.strokeStyle = st.borderColor;
      ctx.strokeText(ln.text, ln.cx, ln.cy);
      ctx.fillStyle = st.color;
      ctx.fillText(ln.text, ln.cx, ln.cy);
    }
  }
}

// get(seg) → { img, w, h } | null  (img: canvas·VideoFrame·video 요소)
export function drawFrame(ctx, plan, segs, k, get, scratch, scale = 1) {
  const t = k / plan.fps;
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.fillStyle = '#000000';
  ctx.fillRect(0, 0, plan.width, plan.height);
  for (const s of segs) {
    if (k < s.k0 || k >= s.k1) continue;
    const d = get(s);
    if (d && d.w > 0 && d.h > 0) drawSegment(ctx, s, d, scratch);
  }
  drawTitle(ctx, plan);
  drawCaptions(ctx, plan, t);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
}
