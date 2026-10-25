// 받아쓰기 작업실(asr-studio) 내보내기 → 작업 JSON captions. 아래 SRT·VTT·JSON 은 asr-studio 의 실제 내보내기 모양 그대로다.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseCaptionFile, parseClock, parseSrt, parseVtt, fromTranscript, isCaptionFileName, looksLikeTranscriptText, captionSummary } from '../../src/app/captions-import.js';
import { checkSpec } from '../../src/core/spec.js';
import { timeCaptions } from '../../src/core/plan.js';
import { zipToFiles } from '../../src/app/drop.js';
import { makeZip } from '../fixtures/zip.mjs';

const SRT = '﻿1\r\n00:00:00,400 --> 00:00:02,100\r\n민수: 안녕하세요, 오늘은 <중요한> 얘기예요.\r\n\r\n2\r\n00:00:02,500 --> 00:00:04,250\r\n두 번째 줄\r\n줄바꿈 있음\r\n\r\n3\r\n01:00:05,000 --> 01:00:07,005\r\n<i>A --> B</i> & C\r\n';
const VTT = 'WEBVTT\n\nNOTE 메모 덩어리\n00:00:09.000 --> 00:00:10.000\n\n00:00:00.400 --> 00:00:02.100 align:start\n<v 민수>안녕하세요, 오늘은 &lt;중요한&gt; 얘기예요.\n\n00:00:05.000 --> 00:00:07.000\n<v 지은>A → B &amp; C\n';
const JSON_EXPORT = JSON.stringify({ app: 'asr-studio', title: '회의 & 메모', segments: [
  { start: 5, end: 7, speaker: '지은', text: '나중 줄' },
  { start: 0.4, end: 2.1, speaker: '민수', text: '  첫 줄 \n 둘째 줄 ' },
  { start: 3, end: 3, speaker: '', text: '길이 0' },
  { start: 4, end: 5, speaker: '', text: '   ' },
] });

test('시각: SRT 쉼표·VTT 점·시 생략·밀리초 자릿수', () => {
  assert.equal(parseClock('00:00:02,100'), 2.1);
  assert.equal(parseClock('01:02.5'), 62.5);
  assert.equal(parseClock('1:00:00.04'), 3600.04);
  assert.ok(Number.isNaN(parseClock('00:61:00')));
  assert.ok(Number.isNaN(parseClock('abc')));
});

test('SRT: 번호·BOM·CRLF, 글 속 <중요한>·--> 는 남기고 서식 꼬리표만 뺀다', () => {
  const c = parseSrt(SRT);
  assert.deepEqual(c, [
    { text: '민수: 안녕하세요, 오늘은 <중요한> 얘기예요.', start: 0.4, end: 2.1 },
    { text: '두 번째 줄\n줄바꿈 있음', start: 2.5, end: 4.25 },
    { text: 'A --> B & C', start: 3605, end: 3607.005 },
  ]);
});

test('VTT: NOTE 덩어리·꼬리표·&lt; 풀기·cue 설정 무시', () => {
  assert.deepEqual(parseVtt(VTT), [
    { text: '안녕하세요, 오늘은 <중요한> 얘기예요.', start: 0.4, end: 2.1 },
    { text: 'A → B & C', start: 5, end: 7 },
  ]);
});

test('받아쓰기 JSON: 시작 순 정렬, 빈 글·길이 0 구간은 뺌, 제목', () => {
  const r = parseCaptionFile(JSON_EXPORT, '회의.json');
  assert.equal(r.kind, 'JSON');
  assert.equal(r.title, '회의 & 메모');
  assert.deepEqual(r.captions, [{ text: '첫 줄\n둘째 줄', start: 0.4, end: 2.1 }, { text: '나중 줄', start: 5, end: 7 }]);
  assert.equal(captionSummary(r.captions), '2줄(0:00~0:07)');
});

test('넘기기 묶음(from: asr-studio)도 같은 모양으로 읽는다', () => {
  const r = fromTranscript({ v: 1, from: 'asr-studio', at: '2026-10-26T00:00:00Z', title: '넘김', segments: [{ start: 1, end: 2, speaker: 'A', text: '하나' }] });
  assert.deepEqual(r.captions, [{ text: '하나', start: 1, end: 2 }]);
  assert.throws(() => fromTranscript({ book: {} }), /형식/);
});

test('알아보기: 확장자·내용', () => {
  assert.ok(isCaptionFileName('a.SRT') && isCaptionFileName('b.vtt') && !isCaptionFileName('c.json'));
  assert.ok(looksLikeTranscriptText('﻿' + JSON_EXPORT));
  assert.ok(!looksLikeTranscriptText(JSON.stringify({ base: 'a.mp4', captions: [] })));
  assert.throws(() => parseCaptionFile('{"base":"a.mp4"}', 'job.json'), /받아쓰기 작업실/);
  assert.throws(() => parseCaptionFile('hello', 'bad.srt'), /자막 줄이 없습니다/);
});

test('넣은 captions 는 작업 JSON 검사를 통과하고 시각 그대로 배치된다(영상보다 늦은 줄은 빠짐)', () => {
  const { captions } = parseCaptionFile(SRT, '회의.srt');
  const spec = { sources: ['a.mp4'], captions };
  assert.deepEqual(checkSpec(spec).errors, []);
  const timed = timeCaptions(captions, 10);
  assert.deepEqual(timed.map((c) => [c.start, c.end, c.auto]), [[0.4, 2.1, false], [2.5, 4.25, false]]);
});

test('zip 안의 SRT·VTT 도 꺼낸다', async () => {
  const zip = makeZip([{ name: 'subs/회의.srt', data: SRT }, { name: 'a.vtt', data: VTT }, { name: 'x.txt', data: 'x' }]);
  const { files, skipped } = await zipToFiles(new Blob([zip]));
  assert.deepEqual(files.map((f) => f.name), ['회의.srt', 'a.vtt']);
  assert.deepEqual(skipped, ['x.txt']);
});
