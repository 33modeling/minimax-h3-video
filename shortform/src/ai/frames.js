// Claude 기획용 소스 프레임: 영상마다 고르게 몇 장을 JPEG(base64)로 뽑는다. shorts/cli.py 와 같은 장수 규칙.
import { CanvasSink } from 'mediabunny';
import { openMedia } from '../render/media.js';
import { kindOf } from '../app/match.js';

async function toB64(canvas) {
  const blob = canvas.convertToBlob
    ? await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.8 })
    : await new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.8));
  const buf = new Uint8Array(await blob.arrayBuffer());
  let bin = '';
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return btoa(bin);
}

export async function sourceFrames(files) {
  const vids = files.filter((f) => kindOf(f) === 'video');
  if (!vids.length) return [];
  const per = Math.min(6, Math.max(2, Math.floor(6 / vids.length)));
  const out = [];
  for (const f of vids) {
    const m = await openMedia(f);
    if (!m.video) continue;
    const w = Math.min(512, m.info.width);
    const sink = new CanvasSink(m.video, { width: 2 * Math.round(w / 2), height: 2 * Math.round((m.info.height * w) / m.info.width / 2), fit: 'fill' });
    const times = Array.from({ length: per }, (_, i) => ((i + 0.5) / per) * m.info.duration);
    const frames = [];
    let i = 0;
    for await (const wc of sink.canvasesAtTimestamps(times)) {
      if (wc) frames.push({ t: times[i], b64: await toB64(wc.canvas) });
      i += 1;
    }
    out.push({ name: f.name, duration: m.info.duration, width: m.info.width, height: m.info.height, frames });
  }
  return out;
}
