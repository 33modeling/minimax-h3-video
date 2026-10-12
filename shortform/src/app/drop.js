// 한꺼번에 놓은 파일 나누기(순수 — node 테스트가 직접 부른다).
// JSON 은 1번 칸, 나머지는 지금 JSON 을 보고 2·3·4번 칸으로 나눈다. 이름 맞추기·역할은 match.js 가 그대로 정한다.
import { baseName, referencedPaths } from '../core/spec.js';
import { kindOf } from './match.js';
import { listZip } from './zip.js';

const MIME = {
  mp4: 'video/mp4', m4v: 'video/mp4', mov: 'video/quicktime', webm: 'video/webm', mkv: 'video/x-matroska',
  mp3: 'audio/mpeg', m4a: 'audio/mp4', aac: 'audio/aac', wav: 'audio/wav', ogg: 'audio/ogg', oga: 'audio/ogg', opus: 'audio/ogg', flac: 'audio/flac',
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif', bmp: 'image/bmp',
  json: 'application/json', zip: 'application/zip',
};
const extOf = (name) => {
  const m = /\.([^./\\]+)$/.exec(String(name));
  return m ? m[1].toLowerCase() : '';
};
export const mimeOf = (name) => MIME[extOf(name)] || '';
export const isJsonFile = (f) => extOf(f.name) === 'json' || f.type === 'application/json';
export const isZipFile = (f) => extOf(f.name) === 'zip' || /^application\/(x-)?zip/.test(f.type || '');
export function isMediaFile(f) {
  if (/^(video|audio|image)\//.test(f.type || '')) return true;
  return /^(video|audio|image)\//.test(mimeOf(f.name));
}

// zip → File 목록. 쓸 수 있는 것(JSON·영상·그림·음악)만, 폴더 경로는 버리고 이름만 남긴다(같은 이름은 처음 것).
// 숨김 파일·__MACOSX·index.html 같은 것은 skipped 로.
export async function zipToFiles(blob) {
  const entries = listZip(new Uint8Array(await blob.arrayBuffer()));
  const files = [];
  const skipped = [];
  const seen = new Set();
  for (const e of entries) {
    const name = baseName(e.name);
    const probe = { name, type: mimeOf(name) };
    const junk = !name || name.startsWith('.') || e.name.startsWith('__MACOSX/');
    if (junk || !(isJsonFile(probe) || isMediaFile(probe)) || seen.has(name)) {
      if (!junk) skipped.push(e.name);
      continue;
    }
    seen.add(name);
    files.push(new File([await e.read()], name, { type: probe.type }));
  }
  return { files, skipped };
}

// JSON 이 여러 개면 하나만 쓴다: book.json(동화책 만들기) → 처음 것
export function pickJson(files) {
  const jsons = files.filter(isJsonFile);
  const json = jsons.find((f) => baseName(f.name).toLowerCase() === 'book.json') || jsons[0] || null;
  return { json, others: jsons.filter((f) => f !== json) };
}

// files: JSON·zip 을 뺀 나머지. ctx: { spec: 작업 JSON 객체 | null, story: 이야기 JSON 인가, hasImage: 3번 칸이 차 있나 }
// 반환: { media(2번 칸), image(3번 칸, 한 장), refs(4번 칸), skipped(쓸 수 없는 파일) }
// - JSON 이 없거나 이야기 JSON 이면: 모두 2번 칸 (이야기면 그림이 쪽 그림이 된다)
// - JSON 이 이름으로 가리키는 파일: image 면 3번 칸, 나머지는 2번 칸(그 자리에 들어감)
// - 이름이 안 맞는 파일: AI 명세(prompt·scenes)면 첫 그림은 3번 칸(첫 장면이 비어 있을 때), 남는 그림·영상은 4번 칸(참고),
//   음악은 2번 칸(배경음이 비어 있으면 배경음). AI 가 아니면 모두 2번 칸(영상은 클립, 음악은 배경음).
export function sortDropped(files, { spec = null, story = false, hasImage = false } = {}) {
  const out = { media: [], image: [], refs: [], skipped: [] };
  for (const f of files) {
    if (!isMediaFile(f)) out.skipped.push(f);
    else if (story || !spec) out.media.push(f);
  }
  if (story || !spec) return out;
  const named = new Set(referencedPaths(spec).map(baseName));
  const imageName = spec.image ? baseName(spec.image) : null;
  const ai = !!(spec.prompt || spec.scenes);
  const firstScene = Array.isArray(spec.scenes) && spec.scenes[0];
  let freeFirst = ai && !imageName && !hasImage && !(firstScene && firstScene.image);
  for (const f of files) {
    if (!isMediaFile(f)) continue;
    const b = baseName(f.name);
    const kind = kindOf(f);
    if (imageName && b === imageName && !out.image.length) out.image.push(f);
    else if (named.has(b)) out.media.push(f);
    else if (ai && kind === 'image' && freeFirst) {
      out.image.push(f);
      freeFirst = false;
    } else if (ai && kind !== 'audio') out.refs.push(f);
    else out.media.push(f);
  }
  return out;
}
