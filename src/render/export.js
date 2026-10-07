// 내보내기: WebCodecs + mediabunny 로 MP4(H.264+AAC). WebCodecs 가 없으면 MediaRecorder 로 실시간 녹화(WebM).
import {
  Output,
  Mp4OutputFormat,
  WebMOutputFormat,
  BufferTarget,
  CanvasSource,
  AudioBufferSource,
  Quality,
  canEncodeVideo,
  canEncodeAudio,
} from 'mediabunny';
import { drawFrame, frameCount, prepareSegments } from './draw.js';
import { SequentialFrames, hasWebCodecs, sliceAudio } from './media.js';

export class Cancelled extends Error {
  constructor() {
    super('취소했습니다');
    this.name = 'Cancelled';
  }
}

let aacRegistered = false;

// 어떤 방식으로 만들지 고른다. force: 'recorder' 면 실시간 녹화를 강제(테스트용).
export async function pickEngine(width, height, force) {
  if (force !== 'recorder' && hasWebCodecs()) {
    if (await canEncodeVideo('avc', { width, height })) {
      let note = '';
      if (!(await canEncodeAudio('aac'))) {
        if (!aacRegistered) {
          const { registerAacEncoder } = await import('@mediabunny/aac-encoder');
          registerAacEncoder();
          aacRegistered = true;
        }
        note = 'AAC는 내장 인코더(WASM)로 만듭니다.';
      }
      return { kind: 'webcodecs', container: 'mp4', video: 'avc', audio: 'aac', label: 'MP4 (H.264 + AAC) · WebCodecs', note };
    }
    for (const v of ['vp9', 'vp8']) {
      if (await canEncodeVideo(v, { width, height })) {
        const audio = (await canEncodeAudio('opus')) ? 'opus' : null;
        if (!audio) break;
        return {
          kind: 'webcodecs',
          container: 'webm',
          video: v,
          audio,
          label: `WebM (${v.toUpperCase()} + Opus) · WebCodecs`,
          note: '이 브라우저에는 H.264 인코더가 없어 WebM으로 만듭니다.',
        };
      }
    }
  }
  if (typeof MediaRecorder === 'function' && HTMLCanvasElement.prototype.captureStream) {
    const types = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm', 'video/mp4'];
    const mime = types.find((t) => MediaRecorder.isTypeSupported(t)) || '';
    return {
      kind: 'recorder',
      container: mime.startsWith('video/mp4') ? 'mp4' : 'webm',
      mime,
      label: `${mime.startsWith('video/mp4') ? 'MP4' : 'WebM'} · 실시간 녹화(MediaRecorder)`,
      note: '이 브라우저는 WebCodecs가 없어 실시간 녹화(MediaRecorder)로 만듭니다. 영상 길이만큼 시간이 걸리고, 그동안 이 탭을 앞에 두세요.',
    };
  }
  return { kind: 'none', label: '지원 안 됨', note: '이 브라우저는 영상 인코딩(WebCodecs·MediaRecorder)을 지원하지 않습니다. 최신 크롬·엣지·파이어폭스에서 열어 주세요.' };
}

function bitrateFor(w, h) {
  return w * h >= 1080 * 1920 ? 8_000_000 : 4_000_000;
}

// ctx: { plan, fileOf(seg), mixed: AudioBuffer, engine, signal, onProgress(frac, text), onFrame(canvas, k) }
export async function exportVideo(job) {
  if (job.engine.kind === 'webcodecs') return exportWebCodecs(job);
  if (job.engine.kind === 'recorder') return exportRecorder(job);
  throw new Error(job.engine.note);
}

async function exportWebCodecs({ plan, fileOf, mixed, engine, signal, onProgress, onFrame }) {
  const W = plan.width;
  const H = plan.height;
  const fps = plan.fps;
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d', { alpha: false });
  const scratch = document.createElement('canvas');
  const segs = prepareSegments(plan);
  const frames = new SequentialFrames(plan, segs, fileOf, 1);
  const N = frameCount(plan);
  const format = engine.container === 'mp4' ? new Mp4OutputFormat({ fastStart: 'in-memory' }) : new WebMOutputFormat();
  const output = new Output({ format, target: new BufferTarget() });
  const vsrc = new CanvasSource(canvas, {
    codec: engine.video,
    quality: new Quality({ bitrate: bitrateFor(W, H) }),
    keyFrameInterval: 2,
    latencyMode: 'quality',
  });
  output.addVideoTrack(vsrc, { frameRate: fps });
  const asrc = new AudioBufferSource({ codec: engine.audio, quality: new Quality({ bitrate: 128_000 }) });
  output.addAudioTrack(asrc);
  await output.start();
  const sr = mixed.sampleRate;
  let audioDone = 0; // 샘플 위치
  const totalSamples = mixed.length;
  const started = performance.now();
  try {
    for (let k = 0; k < N; k++) {
      if (signal.aborted) throw new Cancelled();
      // 오디오를 1초 단위로 영상보다 조금 앞서 넣어 두 트랙이 엇갈려 쌓이게 한다.
      const want = Math.min(totalSamples, Math.round(((k + 1) / fps + 1) * sr));
      while (audioDone < want) {
        const to = Math.min(totalSamples, audioDone + sr);
        await asrc.add(sliceAudio(mixed, audioDone, to));
        audioDone = to;
      }
      await frames.step(k);
      drawFrame(ctx, plan, segs, k, (s) => frames.get(s), scratch, 1);
      await vsrc.add(k / fps, 1 / fps);
      if (onFrame && (k % 6 === 0 || k === N - 1)) onFrame(canvas, k);
      if (k % 3 === 0 || k === N - 1) {
        const el = (performance.now() - started) / 1000;
        const left = k > 5 ? (el / (k + 1)) * (N - k - 1) : null;
        onProgress((k + 1) / N, `${k + 1} / ${N} 프레임${left != null ? ` · 남은 시간 약 ${Math.ceil(left)}초` : ''}`);
      }
    }
    while (audioDone < totalSamples) {
      const to = Math.min(totalSamples, audioDone + sr);
      await asrc.add(sliceAudio(mixed, audioDone, to));
      audioDone = to;
    }
    vsrc.close();
    asrc.close();
    onProgress(1, '파일 마무리 중…');
    await output.finalize();
  } catch (e) {
    try {
      await output.cancel();
    } catch {
      /* 이미 닫힘 */
    }
    throw e;
  } finally {
    await frames.close();
  }
  const type = engine.container === 'mp4' ? 'video/mp4' : 'video/webm';
  return new Blob([output.target.buffer], { type });
}

// ---------- MediaRecorder 대체 경로 ----------
// WebCodecs 가 없으면 디코더도 없으므로 <video> 요소를 실제로 재생하면서 캔버스에 그리고, 캔버스+믹스 오디오를 녹화한다.
async function exportRecorder({ plan, fileOf, mixed, engine, signal, onProgress, onFrame }) {
  const W = plan.width;
  const H = plan.height;
  const fps = plan.fps;
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d', { alpha: false });
  const scratch = document.createElement('canvas');
  const segs = prepareSegments(plan);
  const N = frameCount(plan);
  const videos = new Map(); // `${kind}:${index}` → video 요소
  const urls = [];
  const keyOf = (s) => `${s.kind}:${s.index}`;
  for (const s of segs) {
    const key = keyOf(s);
    if (videos.has(key)) continue;
    const v = document.createElement('video');
    v.muted = true;
    v.playsInline = true;
    v.preload = 'auto';
    const url = URL.createObjectURL(fileOf(s));
    urls.push(url);
    v.src = url;
    videos.set(key, v);
  }
  await Promise.all(
    [...videos.values()].map(
      (v) =>
        new Promise((res, rej) => {
          if (v.readyState >= 2) return res();
          v.addEventListener('loadeddata', res, { once: true });
          v.addEventListener('error', () => rej(new Error('영상을 열지 못했습니다')), { once: true });
        }),
    ),
  );
  const actx = new AudioContext({ sampleRate: mixed.sampleRate });
  const dest = actx.createMediaStreamDestination();
  const asrc = new AudioBufferSourceNode(actx, { buffer: mixed });
  asrc.connect(dest);
  const stream = new MediaStream([...canvas.captureStream(fps).getVideoTracks(), ...dest.stream.getAudioTracks()]);
  const rec = new MediaRecorder(stream, engine.mime ? { mimeType: engine.mime, videoBitsPerSecond: bitrateFor(W, H) } : {});
  const chunks = [];
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  const stopped = new Promise((res) => (rec.onstop = res));
  const owner = new Map(); // video key → 지금 그 요소를 쓰는 세그먼트 id
  const draw = (k) => {
    for (const s of segs) {
      const v = videos.get(keyOf(s));
      const on = k >= s.k0 && k < s.k1;
      if (on && owner.get(keyOf(s)) !== s.id) {
        owner.set(keyOf(s), s.id);
        v.currentTime = s.src + Math.max(0, k / fps - s.t0);
        v.play().catch(() => {});
      } else if (!on && owner.get(keyOf(s)) === s.id && k >= s.k1) {
        owner.delete(keyOf(s));
        v.pause();
      }
    }
    drawFrame(ctx, plan, segs, k, (s) => {
      const v = videos.get(keyOf(s));
      return v && v.readyState >= 2 ? { img: v, w: v.videoWidth, h: v.videoHeight } : null;
    }, scratch, 1);
  };
  draw(0);
  await actx.resume();
  rec.start(1000);
  const t0 = actx.currentTime + 0.05;
  asrc.start(t0);
  try {
    await new Promise((resolve, reject) => {
      const tick = () => {
        if (signal.aborted) return reject(new Cancelled());
        const t = actx.currentTime - t0;
        const k = Math.min(N - 1, Math.max(0, Math.floor(t * fps)));
        draw(k);
        if (onFrame && k % 6 === 0) onFrame(canvas, k);
        onProgress(Math.min(1, t / plan.duration), `실시간 녹화 ${Math.max(0, t).toFixed(1)} / ${plan.duration.toFixed(1)}초`);
        if (t >= plan.duration) return resolve();
        setTimeout(tick, 1000 / fps / 2);
      };
      tick();
    });
  } finally {
    rec.state !== 'inactive' && rec.stop();
    for (const v of videos.values()) v.pause();
    asrc.stop();
    await stopped;
    await actx.close();
    urls.forEach((u) => URL.revokeObjectURL(u));
  }
  return new Blob(chunks, { type: engine.mime ? engine.mime.split(';')[0] : 'video/webm' });
}
