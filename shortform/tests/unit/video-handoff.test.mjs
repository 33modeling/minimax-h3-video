// 영상 만들기 '숏폼으로 보내기' → 숏폼 '내 영상' 칸: 받는 쪽 확인 규칙
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { checkVideoHandoff, VIDEO_HANDOFF_KEY, VIDEO_HANDOFF_HASH } from '../../src/app/video-handoff.js';
import { isFresh, HANDOFF_TTL } from '../../../src/h3video/studio/handoff-store.js';

const now = Date.parse('2026-10-26T09:00:00Z');
const at = new Date(now - 60_000).toISOString();
const video = new File([new Uint8Array([0, 0, 0, 24, 102, 116, 121, 112])], '바다.mp4', { type: 'video/mp4' });

test('약속한 key·주소', () => {
  assert.equal(VIDEO_HANDOFF_KEY, 'shorts-video-input');
  assert.equal(VIDEO_HANDOFF_HASH, '#from=video');
});
test('맞는 영상은 File 과 제목을 돌려준다', () => {
  const got = checkVideoHandoff({ v: 1, from: 'video-maker', at, title: ' 바다 ', file: video }, now);
  assert.equal(got.file, video);
  assert.equal(got.title, '바다');
});
test('이름 없는 Blob 도 영상이면 File 로 바꾼다', () => {
  const got = checkVideoHandoff({ v: 1, from: 'video-maker', at, file: new Blob([new Uint8Array(4)], { type: 'video/webm' }) }, now);
  assert.ok(got.file instanceof File);
  assert.equal(got.file.type, 'video/webm');
});
test('없음·옛 형식·오래됨·빈 파일·영상 아님은 한국어 오류', () => {
  assert.throws(() => checkVideoHandoff(null, now), /찾지 못했어요/);
  assert.throws(() => checkVideoHandoff({ v: 0, from: 'video-maker', at, file: video }, now), /형식을 알 수 없어/);
  assert.throws(() => checkVideoHandoff({ v: 1, from: 'image-maker', at, file: video }, now), /형식을 알 수 없어/);
  assert.throws(() => checkVideoHandoff({ v: 1, from: 'video-maker', at: new Date(now - HANDOFF_TTL - 1).toISOString(), file: video }, now), /30분/);
  assert.throws(() => checkVideoHandoff({ v: 1, from: 'video-maker', at, file: new Blob([]) }, now), /비어 있어/);
  assert.throws(() => checkVideoHandoff({ v: 1, from: 'video-maker', at, file: new File(['x'], 'a.txt', { type: 'text/plain' }) }, now), /영상이 아니라/);
});
test('isFresh: 시각이 없거나 먼 미래면 아님', () => {
  assert.equal(isFresh({ at }, now), true);
  assert.equal(isFresh({}, now), false);
  assert.equal(isFresh({ at: new Date(now + 5 * 60_000).toISOString() }, now), false);
});
