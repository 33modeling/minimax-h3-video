// "예시로 해 보기": 파일이 없어도 바로 만들어 볼 수 있게 예시 영상 3개와 배경음을 이 브라우저에서 몇 초 만에 만든다.
// 만든 파일은 예시 작업 JSON(example.js 의 EXAMPLE_JOB, 컷어웨이)과 이름이 맞는다. 아무 데도 보내지 않는다.
import { Output, Mp4OutputFormat, WebMOutputFormat, BufferTarget, CanvasSource, AudioBufferSource, Quality } from 'mediabunny';
import { sliceAudio } from '../render/media.js';
import { FONT_STACK } from '../render/draw.js';
import { EXAMPLE_JOB } from './example.js';

const SR = 48000;
const FPS = 24;

// 음 목록 [시작초, 길이초, 주파수, 크기] → 스테레오 AudioBuffer
function tones(seconds, notes) {
  const n = Math.round(seconds * SR);
  const L = new Float32Array(n);
  for (const [t0, d, f, g] of notes) {
    const a = Math.round(t0 * SR);
    const b = Math.min(n, Math.round((t0 + d) * SR));
    for (let i = a; i < b; i++) {
      const t = (i - a) / SR;
      const env = Math.min(1, t / 0.02) * Math.min(1, (d - t) / 0.25);
      L[i] += g * env * Math.sin(2 * Math.PI * f * t);
    }
  }
  const buf = new AudioBuffer({ length: n, numberOfChannels: 2, sampleRate: SR });
  buf.copyToChannel(L, 0);
  buf.copyToChannel(L, 1);
  return buf;
}

async function encode(engine, { w = 0, h = 0, seconds, draw = null, audio }) {
  const format = engine.container === 'mp4' ? new Mp4OutputFormat({ fastStart: 'in-memory' }) : new WebMOutputFormat();
  const output = new Output({ format, target: new BufferTarget() });
  let vsrc = null;
  let ctx = null;
  if (draw) {
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    ctx = canvas.getContext('2d', { alpha: false });
    vsrc = new CanvasSource(canvas, { codec: engine.video, quality: new Quality({ bitrate: 900_000 }), keyFrameInterval: 1 });
    output.addVideoTrack(vsrc, { frameRate: FPS });
  }
  const asrc = new AudioBufferSource({ codec: engine.audio, quality: new Quality({ bitrate: 96_000 }) });
  output.addAudioTrack(asrc);
  await output.start();
  let done = 0;
  const N = Math.round(seconds * FPS);
  const pushAudio = async (upTo) => {
    while (done < upTo) {
      const to = Math.min(audio.length, done + SR);
      await asrc.add(sliceAudio(audio, done, to));
      done = to;
    }
  };
  for (let k = 0; vsrc && k < N; k++) {
    await pushAudio(Math.min(audio.length, Math.round(((k + 1) / FPS + 1) * SR)));
    draw(ctx, k / FPS, w, h);
    await vsrc.add(k / FPS, 1 / FPS);
  }
  await pushAudio(audio.length);
  vsrc?.close();
  asrc.close();
  await output.finalize();
  return output.target.buffer;
}

const label = (ctx, text, x, y, size) => {
  ctx.font = `700 ${size}px ${FONT_STACK}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.lineWidth = Math.max(3, size / 8);
  ctx.strokeStyle = 'rgba(0,0,0,0.55)';
  ctx.strokeText(text, x, y);
  ctx.fillStyle = '#ffffff';
  ctx.fillText(text, x, y);
};

// 가로 "내 영상": 하늘색이 천천히 바뀌고 공이 지나간다
function drawBase(ctx, t, w, h) {
  const g = ctx.createLinearGradient(0, 0, w, h);
  g.addColorStop(0, `hsl(${205 + t * 8} 60% 42%)`);
  g.addColorStop(1, `hsl(${245 + t * 8} 55% 22%)`);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = 'rgba(255,255,255,0.08)';
  for (let i = 0; i < 6; i++) ctx.fillRect(((i * 120 + t * 40) % (w + 120)) - 120, h * 0.72, 80, h * 0.28);
  ctx.fillStyle = '#ffd166';
  ctx.beginPath();
  ctx.arc(w * (0.1 + 0.8 * ((t / 6) % 1)), h * 0.42 - Math.abs(Math.sin(t * 2.4)) * h * 0.18, h * 0.08, 0, Math.PI * 2);
  ctx.fill();
  label(ctx, '내 영상 (가로)', w / 2, h * 0.2, Math.round(h * 0.11));
  label(ctx, `${t.toFixed(1)}초`, w / 2, h * 0.86, Math.round(h * 0.08));
}

// 세로 클립 두 개: 도는 네모 / 흐르는 줄무늬
const drawClip = (n, hue) => (ctx, t, w, h) => {
  ctx.fillStyle = `hsl(${hue} 55% 38%)`;
  ctx.fillRect(0, 0, w, h);
  if (n === 1) {
    ctx.save();
    ctx.translate(w / 2, h / 2);
    ctx.rotate(t * 1.6);
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    ctx.fillRect(-w * 0.2, -w * 0.2, w * 0.4, w * 0.4);
    ctx.restore();
  } else {
    ctx.fillStyle = 'rgba(255,255,255,0.18)';
    for (let y = -80; y < h + 80; y += 80) ctx.fillRect(0, y + ((t * 90) % 80), w, 36);
  }
  label(ctx, `클립 ${n}`, w / 2, h * 0.16, Math.round(w * 0.14));
};

// engine: pickEngine 결과(WebCodecs 만). 반환: { job, files }
export async function makeDemo(engine, onStep = () => {}) {
  if (!engine || engine.kind !== 'webcodecs') throw new Error('이 브라우저는 예시 영상을 만들 수 없어요(WebCodecs 필요). 최신 크롬·엣지에서 해 보세요.');
  const ext = engine.container;
  const vtype = ext === 'mp4' ? 'video/mp4' : 'video/webm';
  const aname = ext === 'mp4' ? 'bgm.m4a' : 'bgm.weba';
  const atype = ext === 'mp4' ? 'audio/mp4' : 'audio/webm';
  const files = [];
  onStep('내 영상(가로)을 만드는 중…');
  const pad = tones(6, [[0, 6, 220, 0.05], [0, 6, 277.2, 0.04], [0, 6, 329.6, 0.04]]);
  files.push(new File([await encode(engine, { w: 640, h: 360, seconds: 6, draw: drawBase, audio: pad })], `base.${ext}`, { type: vtype }));
  for (const [n, hue, f] of [[1, 160, 660], [2, 280, 880]]) {
    onStep(`클립 ${n}을 만드는 중…`);
    const ding = tones(3, [[0.1, 0.6, f, 0.12], [1.6, 0.6, f * 1.25, 0.1]]);
    files.push(new File([await encode(engine, { w: 360, h: 640, seconds: 3, draw: drawClip(n, hue), audio: ding })], `src${n}.${ext}`, { type: vtype }));
  }
  onStep('배경음을 만드는 중…');
  const scale = [261.6, 329.6, 392, 523.3, 392, 329.6];
  const melody = Array.from({ length: 24 }, (_, i) => [i * 0.25, 0.4, scale[i % scale.length], 0.09]);
  files.push(new File([await encode(engine, { seconds: 6, audio: tones(6, melody) })], aname, { type: atype }));
  const job = {
    ...EXAMPLE_JOB,
    base: `base.${ext}`,
    sources: [`src1.${ext}`, { path: `src2.${ext}`, start: 0.5, end: 2.5 }],
    bgm: aname,
    title: '예시: 3초 만에 보는 요약',
    output: `example-short.${ext}`,
  };
  return { job, files };
}
