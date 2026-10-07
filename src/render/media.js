// 파일 읽기(mediabunny 디먹서 + WebCodecs 디코더), 프레임 공급, 오디오 믹스.
import { Input, BlobSource, ALL_FORMATS, CanvasSink, AudioBufferSink } from 'mediabunny';
import { srcTime } from './draw.js';

export const hasWebCodecs = () =>
  typeof window !== 'undefined' && typeof window.VideoEncoder === 'function' && typeof window.VideoDecoder === 'function' && typeof window.AudioDecoder === 'function';

const inputs = new WeakMap(); // File → { input, video, audio, info }

export async function openMedia(file) {
  if (inputs.has(file)) return inputs.get(file);
  const p = (async () => {
    const input = new Input({ source: new BlobSource(file), formats: ALL_FORMATS });
    if (!(await input.canRead())) throw new Error(`${file.name}: 읽을 수 없는 형식입니다`);
    const video = await input.getPrimaryVideoTrack();
    const audio = await input.getPrimaryAudioTrack();
    const duration = await input.computeDuration();
    const info = {
      duration: Math.round(duration * 1000) / 1000,
      width: video ? video.displayWidth : 0,
      height: video ? video.displayHeight : 0,
      hasAudio: !!audio,
    };
    return { input, video, audio, info };
  })();
  inputs.set(file, p);
  try {
    return await p;
  } catch (e) {
    inputs.delete(file);
    throw e;
  }
}

// 영상 디코딩 가능 여부(WebCodecs 경로에서만 의미가 있다)
export async function checkDecodable(file) {
  const m = await openMedia(file);
  if (m.video && hasWebCodecs() && !(await m.video.canDecode())) {
    throw new Error(`${file.name}: 이 브라우저가 이 영상 코덱(${m.video.codec || '알 수 없음'})을 풀지 못합니다. H.264 MP4로 바꿔 보세요`);
  }
  return m;
}

const even = (x) => 2 * Math.max(1, Math.round(x / 2));

// 세그먼트를 그리는 데 필요한 원본 해상도만큼만 디코딩한다(4K 원본을 720p 출력에 쓸 때 메모리 절약).
function sinkSize(seg, scale) {
  const r = seg.rect;
  const coverScale = Math.max(r.w / seg.cover.sw, r.h / seg.cover.sh);
  const containScale = seg.contain.w / seg.srcW;
  const k = Math.min(1, Math.max(coverScale, containScale) * scale);
  const w = Math.min(seg.srcW, even(seg.srcW * k));
  const h = Math.min(seg.srcH, even((seg.srcH * w) / seg.srcW));
  return { width: w, height: h };
}

// 내보내기·재생용: 세그먼트마다 순차 디코딩 반복자를 둔다.
export class SequentialFrames {
  constructor(plan, segs, fileOf, scale = 1) {
    this.plan = plan;
    this.segs = segs;
    this.fileOf = fileOf; // seg → File
    this.scale = scale;
    this.iters = new Map();
    this.cur = new Map();
  }

  async step(k) {
    const fps = this.plan.fps;
    for (const s of this.segs) {
      if (k >= s.k1 && this.iters.has(s.id)) {
        const it = this.iters.get(s.id);
        this.iters.delete(s.id);
        this.cur.delete(s.id);
        await it.return?.();
      }
    }
    const pulls = [];
    for (const s of this.segs) {
      if (k < s.k0 || k >= s.k1) continue;
      let it = this.iters.get(s.id);
      if (!it) {
        const m = await openMedia(this.fileOf(s));
        const sink = new CanvasSink(m.video, { ...sinkSize(s, this.scale), fit: 'fill' });
        const dur = m.info.duration;
        const from = k; // 처음 쓰이는 프레임부터(재생을 중간에서 시작할 수 있음)
        function* times() {
          for (let j = from; j < s.k1; j++) yield Math.min(srcTime(s, j, fps), Math.max(0, dur - 0.001));
        }
        it = sink.canvasesAtTimestamps(times());
        this.iters.set(s.id, it);
      }
      pulls.push(
        it.next().then((r) => {
          if (r.value) this.cur.set(s.id, r.value.canvas);
        }),
      );
    }
    await Promise.all(pulls);
  }

  get(seg) {
    const c = this.cur.get(seg.id);
    return c ? { img: c, w: c.width, h: c.height } : null;
  }

  async close() {
    for (const it of this.iters.values()) await it.return?.();
    this.iters.clear();
    this.cur.clear();
  }
}

// 미리보기 한 장(임의 시각): 세그먼트별 저해상도 싱크에서 getCanvas.
export class StillFrames {
  constructor(plan, segs, fileOf, scale) {
    this.plan = plan;
    this.segs = segs;
    this.fileOf = fileOf;
    this.scale = scale;
    this.sinks = new Map();
    this.cur = new Map();
  }

  async load(k) {
    const fps = this.plan.fps;
    this.cur.clear();
    await Promise.all(
      this.segs
        .filter((s) => k >= s.k0 && k < s.k1)
        .map(async (s) => {
          const m = await openMedia(this.fileOf(s));
          let sink = this.sinks.get(s.id);
          if (!sink) {
            sink = new CanvasSink(m.video, { ...sinkSize(s, this.scale), fit: 'fill' });
            this.sinks.set(s.id, sink);
          }
          const t = Math.min(srcTime(s, k, fps), Math.max(0, m.info.duration - 0.001));
          const wc = (await sink.getCanvas(t)) || (await sink.getCanvas(0.0));
          if (wc) this.cur.set(s.id, wc.canvas);
        }),
    );
  }

  get(seg) {
    const c = this.cur.get(seg.id);
    return c ? { img: c, w: c.width, h: c.height } : null;
  }
}

// ---------- 오디오 ----------
const SR = 48000;

async function decodeWithMediabunny(file, start, dur) {
  const m = await openMedia(file);
  if (!m.audio || !(await m.audio.canDecode())) return null;
  const sr = m.audio.sampleRate;
  const ch = Math.min(2, Math.max(1, m.audio.numberOfChannels));
  const len = Math.max(1, Math.ceil(dur * sr));
  const out = new AudioBuffer({ length: len, numberOfChannels: ch, sampleRate: sr });
  const sink = new AudioBufferSink(m.audio);
  for await (const { buffer, timestamp } of sink.buffers(start, start + dur)) {
    let dst = Math.round((timestamp - start) * sr);
    let from = 0;
    if (dst < 0) {
      from = -dst;
      dst = 0;
    }
    const n = Math.min(buffer.length - from, len - dst);
    if (n <= 0) continue;
    for (let c = 0; c < ch; c++) {
      const data = buffer.getChannelData(Math.min(c, buffer.numberOfChannels - 1));
      out.getChannelData(c).set(data.subarray(from, from + n), dst);
    }
  }
  return out;
}

const fullDecodes = new WeakMap();
async function decodeWithWebAudio(file, start, dur) {
  if (!fullDecodes.has(file)) {
    fullDecodes.set(
      file,
      file.arrayBuffer().then((ab) => new OfflineAudioContext(2, SR, SR).decodeAudioData(ab)),
    );
  }
  const full = await fullDecodes.get(file);
  const sr = full.sampleRate;
  const a = Math.min(full.length, Math.round(start * sr));
  const b = Math.min(full.length, a + Math.ceil(dur * sr));
  const out = new AudioBuffer({ length: Math.max(1, b - a), numberOfChannels: full.numberOfChannels, sampleRate: sr });
  for (let c = 0; c < full.numberOfChannels; c++) out.getChannelData(c).set(full.getChannelData(c).subarray(a, b));
  return out;
}

async function decodeRange(file, start, dur) {
  if (hasWebCodecs()) {
    try {
      const r = await decodeWithMediabunny(file, start, dur);
      if (r) return r;
    } catch (e) {
      console.warn('mediabunny 오디오 디코딩 실패, Web Audio 로 다시 시도', e);
    }
  }
  return decodeWithWebAudio(file, start, dur);
}

// plan.audio 를 48kHz 스테레오 한 버퍼로 섞는다. 소리가 하나도 없으면 무음(그래도 오디오 트랙은 넣는다).
export async function mixAudio(plan, fileOfAudio, onNote = () => {}) {
  const T = plan.duration;
  const length = Math.max(1, Math.round(T * SR));
  const ctx = new OfflineAudioContext({ numberOfChannels: 2, length, sampleRate: SR });
  for (const a of plan.audio) {
    const file = fileOfAudio(a);
    if (!file) continue;
    const span = a.t1 - a.t0;
    let buf;
    try {
      if (a.loop) {
        const m = await openMedia(file);
        buf = await decodeRange(file, 0, Math.min(m.info.duration || span, span));
      } else {
        buf = await decodeRange(file, a.src, span);
      }
    } catch (e) {
      onNote(`${file.name}: 소리를 풀지 못해 빼고 만듭니다`);
      continue;
    }
    const node = new AudioBufferSourceNode(ctx, { buffer: buf, loop: !!a.loop });
    const gain = new GainNode(ctx, { gain: a.gain });
    node.connect(gain).connect(ctx.destination);
    if (a.loop) {
      node.start(a.t0);
      node.stop(a.t1);
    } else {
      node.start(a.t0, 0, span);
    }
  }
  return ctx.startRendering();
}

export function sliceAudio(buf, from, to) {
  const a = Math.max(0, Math.min(buf.length, from));
  const b = Math.max(a, Math.min(buf.length, to));
  const out = new AudioBuffer({ length: Math.max(1, b - a), numberOfChannels: buf.numberOfChannels, sampleRate: buf.sampleRate });
  for (let c = 0; c < buf.numberOfChannels; c++) out.copyToChannel(buf.getChannelData(c).subarray(a, b), c);
  return out;
}
