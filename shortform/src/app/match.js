// 두 번째 칸에서 고른 파일들을 명세에 맞춘다(순수 함수 — node 테스트가 직접 부른다).
// 명세가 이름으로 가리키는 파일은 그 자리(base/sources/bgm)에 쓰고, 이름이 안 맞는 영상은
// sources 뒤에 붙이며, 이름이 안 맞는 음악 파일은 배경음이 비어 있을 때만 bgm 으로 쓴다.
import { attachFiles, baseName, mediaPath, referencedPaths, isImagePath } from '../core/spec.js';

export function isAudioName(name) {
  return /\.(mp3|m4a|aac|wav|ogg|oga|opus|flac)$/i.test(String(name));
}

export function kindOf(file) {
  const t = (file && file.type) || '';
  const name = file && file.name;
  if (t.startsWith('audio/') || (!t.startsWith('video/') && isAudioName(name))) return 'audio';
  if (t.startsWith('image/') || isImagePath(name)) return 'image';
  return 'video';
}

// files: [{name, type}] (File 이어도 됨). 반환: { spec, roles: {name: 역할}, missing: [이름] }
export function matchFiles(spec, files) {
  const refs = referencedPaths(spec).map(baseName);
  const extraVideos = [];
  let bgmFromFile = null;
  for (const f of files) {
    if (refs.includes(baseName(f.name))) continue;
    const k = kindOf(f);
    if (k === 'video') extraVideos.push(f.name);
    else if (k === 'audio' && !spec.bgm && !bgmFromFile) bgmFromFile = f.name;
    else if (k === 'image' && (spec.prompt || spec.scenes)) extraVideos.push(f.name);
  }
  let next = attachFiles(spec, extraVideos);
  if (bgmFromFile) next = { ...next, bgm: bgmFromFile };

  const have = new Set(files.map((f) => baseName(f.name)));
  const roles = {};
  const setRole = (p, role) => {
    if (!p) return;
    const b = baseName(p);
    if (!roles[b]) roles[b] = role;
  };
  setRole(mediaPath(next.base), '기본 영상');
  (next.sources || []).forEach((m, i) => setRole(mediaPath(m), next.prompt || next.scenes ? `AI 참조 ${i + 1}` : `소스 ${i + 1}`));
  (next.scenes || []).forEach((s, i) => (s.sources || []).forEach((m) => setRole(mediaPath(m), `장면 ${i + 1} 참조`)));
  setRole(next.image, '첫 프레임 이미지');
  setRole(next.bgm, '배경음');
  const missing = referencedPaths(next).map(baseName).filter((b) => !have.has(b));
  const unused = files.map((f) => baseName(f.name)).filter((b) => !roles[b]);
  return { spec: next, roles, missing, unused };
}

// 이름(경로일 수도 있음)으로 File 찾기
export function fileFor(files, path) {
  if (!path) return null;
  const b = baseName(path);
  return files.find((f) => baseName(f.name) === b) || null;
}

export function outputName(spec, ext) {
  const raw = baseName(spec.output || 'short.mp4');
  const stem = raw.replace(/\.[^.]+$/, '') || 'short';
  return `${stem}.${ext}`;
}
