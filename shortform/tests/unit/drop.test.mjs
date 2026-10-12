// 한꺼번에 놓기: zip 읽기(저장·deflate), zip → 파일, JSON 고르기, 칸 나누기.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import zlib from 'node:zlib';
import { makeZip } from '../fixtures/zip.mjs';
import { listZip, crc32, ZipError } from '../../src/app/zip.js';
import { zipToFiles, pickJson, sortDropped, isJsonFile, isZipFile, isMediaFile, mimeOf } from '../../src/app/drop.js';

const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 1, 2, 3, 4, 5, 6, 7, 8]);
const book = { kind: 'batch', title: '토토', items: [{ id: 'page-01', kind: 'page', page: 1, text: '하나', image: 'images/page-01.png', scene: 'A' }] };
const BOOK_ENTRIES = [
  { name: 'book.json', data: JSON.stringify(book) },
  { name: 'images/', data: '' },
  { name: 'images/page-01.png', data: PNG },
  { name: 'images/표지.png', data: PNG },
  { name: 'index.html', data: '<!doctype html>' },
  { name: '__MACOSX/images/._page-01.png', data: 'x' },
  { name: 'images/.DS_Store', data: 'x' },
  { name: 'other/page-01.png', data: 'dup' },
];

test('crc32 는 zlib 과 같다', () => {
  for (const s of ['', 'a', 'hello zip', '한글 이름'.repeat(50)]) assert.equal(crc32(Buffer.from(s)), zlib.crc32(Buffer.from(s)) >>> 0, s);
});

for (const method of [0, 8]) {
  test(`zip 읽기: ${method === 0 ? '저장(압축 없음, 동화책 만들기 파일 받기)' : 'deflate 압축'}`, async () => {
    const entries = listZip(makeZip(BOOK_ENTRIES, { method }));
    assert.deepEqual(entries.map((e) => e.name), BOOK_ENTRIES.filter((e) => !e.name.endsWith('/')).map((e) => e.name));
    assert.ok(entries.every((e) => e.method === method));
    assert.deepEqual(JSON.parse(new TextDecoder().decode(await entries[0].read())), book);
    assert.deepEqual(Buffer.from(await entries[1].read()), PNG);
  });
}

test('zip 읽기: 깨진 파일·zip 아님·UTF-8 표시 없는 한글 이름(EUC-KR)', async () => {
  const z = makeZip([{ name: 'a.json', data: '{"x":1}' }]);
  z[30 + 'a.json'.length] ^= 0xff; // 내용 한 바이트를 바꾸면 CRC 가 안 맞는다
  await assert.rejects(listZip(z)[0].read(), (e) => e instanceof ZipError && /깨졌어요/.test(e.message));
  assert.throws(() => listZip(new Uint8Array(100)), /zip 파일이 아니거나/);
  const euckr = Buffer.from([0xc7, 0xa5, 0xc1, 0xf6, 0x2e, 0x70, 0x6e, 0x67]); // '표지.png'
  assert.equal(listZip(makeZip([{ name: '', nameBytes: euckr, data: PNG }], { utf8: false }))[0].name, '표지.png');
});

test('zip → 파일: JSON·그림만 이름으로, 폴더·숨김·HTML·같은 이름은 뺀다', async () => {
  for (const method of [0, 8]) {
    const { files, skipped } = await zipToFiles(new Blob([makeZip(BOOK_ENTRIES, { method })]));
    assert.deepEqual(files.map((f) => [f.name, f.type]), [['book.json', 'application/json'], ['page-01.png', 'image/png'], ['표지.png', 'image/png']]);
    assert.deepEqual(skipped, ['index.html', 'other/page-01.png']);
    assert.equal(files[1].size, PNG.length);
  }
});

const F = (name, type = mimeOf(name)) => ({ name, type });
const names = (list) => list.map((f) => f.name);

test('파일 종류·JSON 고르기', () => {
  assert.ok(isJsonFile(F('a.JSON', '')) && isZipFile(F('b.zip', '')) && isZipFile(F('c', 'application/x-zip-compressed')));
  assert.ok(isMediaFile(F('x.MOV', '')) && isMediaFile(F('v', 'video/mp4')) && !isMediaFile(F('note.txt')) && !isMediaFile(F('a.json')));
  const { json, others } = pickJson([F('a.json'), F('pic.png'), F('book.json'), F('z.json')]);
  assert.equal(json.name, 'book.json');
  assert.deepEqual(names(others), ['a.json', 'z.json']);
  assert.equal(pickJson([F('x.png')]).json, null);
});

test('칸 나누기: JSON 없음·이야기 JSON 이면 모두 2번 칸, 쓸 수 없는 파일은 뺀다', () => {
  const files = [F('page-01.png'), F('clip.mp4'), F('song.mp3'), F('notes.txt')];
  for (const ctx of [{}, { story: true, spec: { prompt: 'p' } }]) {
    const s = sortDropped(files, ctx);
    assert.deepEqual(names(s.media), ['page-01.png', 'clip.mp4', 'song.mp3']);
    assert.deepEqual([s.image.length, s.refs.length, names(s.skipped)], [0, 0, ['notes.txt']]);
  }
});

test('칸 나누기: 내 영상 합성(AI 없음) — 이름이 맞든 안 맞든 2번 칸', () => {
  const s = sortDropped([F('base.mp4'), F('extra.mov'), F('first.png'), F('bgm.m4a')], { spec: { base: 'clips/base.mp4', bgm: 'bgm.m4a' } });
  assert.deepEqual(names(s.media), ['base.mp4', 'extra.mov', 'first.png', 'bgm.m4a']);
  assert.deepEqual([s.image.length, s.refs.length], [0, 0]);
});

test('칸 나누기: AI 명세 — 첫 그림은 3번 칸, 남는 그림·영상은 4번 칸, 음악·JSON 이 가리키는 파일은 2번 칸', () => {
  const files = [F('a.png'), F('b.png'), F('dance.mp4'), F('voice.mp3'), F('base.mp4')];
  const s = sortDropped(files, { spec: { prompt: 'p', base: 'base.mp4' } });
  assert.deepEqual([names(s.image), names(s.refs), names(s.media)], [['a.png'], ['b.png', 'dance.mp4'], ['voice.mp3', 'base.mp4']]);
  // JSON 에 image 가 있으면 그 이름은 3번 칸, 다른 그림은 참고
  const t = sortDropped([F('a.png'), F('first.png')], { spec: { prompt: 'p', image: 'pics/first.png' } });
  assert.deepEqual([names(t.image), names(t.refs)], [['first.png'], ['a.png']]);
  // 3번 칸이 이미 차 있거나 첫 장면에 그림이 있으면 그림은 모두 참고
  assert.deepEqual(names(sortDropped([F('a.png')], { spec: { prompt: 'p' }, hasImage: true }).refs), ['a.png']);
  assert.deepEqual(names(sortDropped([F('a.png')], { spec: { scenes: [{ prompt: 'p', image: 'x.png' }] } }).refs), ['a.png']);
  // 장면 그림 이름이 맞으면 2번 칸(장면 n 첫 프레임 자리)
  assert.deepEqual(names(sortDropped([F('x.png')], { spec: { scenes: [{ prompt: 'p', image: 'x.png' }] } }).media), ['x.png']);
});
