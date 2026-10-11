// JSON 한번에(웹): 이야기 JSON → 숏폼 명세가 파이썬(shorts/story.py)과 같은 결과인지 tests/fixtures/story 로 확인한다.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { storyToSpec, isStory, captionPieces, autoSeconds } from '../../src/core/story.js';
import { checkSpec, aiScenes } from '../../src/core/spec.js';

const read = (p) => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
const cases = read('../fixtures/story/cases.json');
const expected = read('../fixtures/story/expected.json');

test('story JSON → shortform spec matches the Python converter on every fixture', () => {
  assert.equal(cases.cases.length, expected.length);
  cases.cases.forEach((c, i) => {
    const got = storyToSpec(c.data, c.images, { narration: c.narration });
    assert.deepEqual(got, expected[i], c.name);
    assert.deepEqual(checkSpec(got.spec).errors, [], c.name);
    assert.equal(aiScenes(got.spec).length, got.spec.scenes.length);
  });
  for (const e of cases.errors) assert.throws(() => storyToSpec(e.data, e.images), (err) => err.message.includes(e.contains), e.contains);
});

test('story detection leaves shortform specs alone', () => {
  assert.ok(!isStory([1, 2]) && !isStory([]));
  assert.ok(isStory(['a']) && isStory({ clips: [] }) && isStory({ kind: 'batch', items: [] }) && isStory(cases.cases[0].data));
  for (const name of ['scenes', 'prompt-only', 'compose-only']) assert.equal(isStory(read(`../../examples/${name}.json`)), false, name);
});

test('seconds and caption pieces', () => {
  assert.deepEqual(autoSeconds('숲 가장자리에 아기 고슴도치 토토가 살았어요.\n토토는 늘 혼자 놀았어요.'), [10, '글 31자']);
  assert.deepEqual(autoSeconds('', 6.5), [7, 'JSON']);
  assert.deepEqual(autoSeconds(''), [6, '기본']);
  assert.throws(() => autoSeconds('', '열초'));
  assert.deepEqual(captionPieces('첫 줄\n\n 둘째   줄 '), ['첫 줄', '둘째 줄']);
  assert.deepEqual(captionPieces('가'.repeat(130)).map((x) => x.length), [120, 10]);
});
