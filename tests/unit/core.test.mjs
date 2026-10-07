// 공용 계획·검증 모듈(src/core) 단위 테스트 + 파이썬(shorts/plan.py)과 같은 숫자를 내는지 비교.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { checkSpec, normalizeSpec, composeInputs, attachFiles, aiScenes } from '../../src/core/spec.js';
import { planTimeline, timeCaptions, wrapText, fitGeometry } from '../../src/core/plan.js';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const data = JSON.parse(readFileSync(ROOT + 'tests/parity_cases.json', 'utf8'));
const key = (p) => p.replace(/\.[^.]+$/, '');

function inputsFor(spec) {
  const ci = composeInputs(spec, []);
  return {
    base: ci.base ? { media: ci.base, info: data.media[key(ci.base.path)] } : null,
    clips: ci.clips.map((m) => ({ media: m, info: data.media[key(m.path)] })),
    bgm: ci.bgm ? { path: ci.bgm, info: data.media[key(ci.bgm)] } : null,
  };
}

const plans = Object.fromEntries(data.cases.map((c) => [c.name, planTimeline(normalizeSpec(c.spec), inputsFor(c.spec))]));

test('스키마 오류는 한국어로, 오타는 비슷한 이름을 알려 준다', () => {
  const { errors } = checkSpec({ prompt: '', duration: 30, ratio: '2:1', templat: 'pip', captions: [3] });
  assert.ok(errors.some((e) => e.includes('prompt') && e.includes('비어 있으면 안 됩니다')));
  assert.ok(errors.some((e) => e.includes('15 이하여야 합니다 (지금 30)')));
  assert.ok(errors.some((e) => e.includes("'template' 인가요?")));
  assert.ok(errors.some((e) => e.startsWith('captions[0]')));
  assert.ok(errors.every((e) => /[가-힣]/.test(e)));
});

test('재료가 없으면 오류, prompt 와 scenes 를 같이 쓰면 오류', () => {
  assert.match(checkSpec({ title: 'x' }).errors[0], /만들 재료가 없습니다/);
  assert.match(checkSpec({ prompt: 'a', scenes: [{ prompt: 'b' }] }).errors[0], /함께 쓸 수 없습니다/);
  assert.match(checkSpec({ prompt: 'a', sources: ['1.mp4', '2.mp4', '3.mp4', '4.mp4'] }).errors[0], /참조 영상은 최대 3개/);
});

test('두 번째 파일: 이름이 맞으면 그 자리, 아니면 sources 로', () => {
  const s = attachFiles({ base: 'base.mp4' }, ['/x/base.mp4', '/y/clip.mp4']);
  assert.deepEqual(s.sources, ['/y/clip.mp4']);
  assert.equal(aiScenes(attachFiles({ prompt: 'p' }, ['a.mp4']))[0].task, 'ref2va');
  assert.equal(aiScenes({ prompt: 'p', image: 'f.png' })[0].task, 'fl2va');
  assert.equal(aiScenes({ prompt: 'p' })[0].task, 't2va');
});

test('자막 시간 자동 배분: 글자 수에 비례, 끝까지 덮고 직접 준 시간은 그대로', () => {
  const caps = timeCaptions(['가나다', '가나다라마바사아자차', { text: '고정', start: 1, end: 2 }], 10);
  assert.equal(caps[0].start, 0);
  assert.ok(caps[1].end - caps[1].start > caps[0].end - caps[0].start);
  assert.deepEqual([caps[2].start, caps[2].end], [1, 2]);
});

test('줄바꿈: 너비 안에서 나누고 최대 줄 수를 넘으면 말줄임', () => {
  const lines = wrapText('세 번째 자막은 조금 더 길게 써 봅니다', 40, 620, 3);
  assert.deepEqual(lines, ['세 번째 자막은 조금 더 길게 써', '봅니다']);
  const long = wrapText('가'.repeat(80), 40, 400, 2);
  assert.equal(long.length, 2);
  assert.ok(long[1].endsWith('…'));
});

test('맞춤 좌표: 가로 영상을 세로 칸에 cover/contain', () => {
  const g = fitGeometry(1280, 720, { x: 0, y: 0, w: 720, h: 1280 });
  assert.deepEqual(g.cover, { sx: 437, sy: 0, sw: 406, sh: 720 });
  assert.deepEqual(g.contain, { x: 0, y: 437, w: 720, h: 406 });
});

test('템플릿별 배치', () => {
  const cut = plans.cutaway;
  assert.equal(cut.duration, 8);
  assert.equal(cut.segments.filter((s) => s.kind === 'clip').length, 3);
  assert.ok(cut.segments.filter((s) => s.kind === 'clip').every((s) => s.rect.w === 720 && s.rect.h === 1280 && s.z === 1));
  assert.deepEqual(cut.audio.map((a) => a.kind), ['base']);
  const sp = plans.split;
  assert.deepEqual(sp.segments[0].rect, { x: 0, y: 0, w: 720, h: 640 });
  assert.ok(sp.segments.slice(1).every((s) => s.rect.y === 640 && s.rect.h === 640));
  assert.equal(sp.segments.at(-1).t1, 8);
  assert.deepEqual(sp.audio.map((a) => a.kind), ['base', 'bgm']);
  assert.equal(sp.style.caption.centerY, 640);
  const pip = plans['pip-1080'];
  assert.equal(pip.width, 1080);
  assert.equal(pip.duration, 10);
  assert.ok(pip.segments.slice(1).every((s) => s.rect.w < 1080 && s.border > 0));
  assert.equal(pip.audio.length, 0);
  assert.equal(pip.title.length, 2);
  const mon = plans['montage-base-audio'];
  assert.equal(mon.duration, 7.5);
  assert.deepEqual(mon.audio.map((a) => a.kind), ['base']);
  const nob = plans['montage-no-base'];
  assert.equal(nob.template, 'montage');
  assert.ok(nob.warnings[0].includes('몽타주'));
  assert.deepEqual(nob.audio.map((a) => a.kind), ['clip', 'clip', 'bgm']);
  assert.equal(plans['base-only'].template, 'base');
  assert.equal(plans['base-only'].duration, 7.9);
});

test('파이썬 CLI 계획과 같다(웹·CLI 같은 배치)', () => {
  const py = JSON.parse(execFileSync('python3', [ROOT + 'tests/parity_plan.py'], { encoding: 'utf8' }));
  for (const name of Object.keys(plans)) {
    assert.deepEqual(JSON.parse(JSON.stringify(plans[name])), py[name], `계획 불일치: ${name}`);
  }
});
