// 웹 전용 순수 모듈 단위 테스트: 파일 맞추기, Claude 기획(CLI 와 같은 요청), AI 요청 본문, 재요청 흐름.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { matchFiles, outputName, kindOf } from '../../src/app/match.js';
import { SYSTEM_PROMPT, apiSchema, buildRequest, parseReply, plan, headers } from '../../src/core/claude.js';
import { sglangBody, genShortEdge, normProgress, mediaKind } from '../../src/ai/generate.js';
import { aiScenes } from '../../src/core/spec.js';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const f = (name, type = '') => ({ name, type });

test('파일 맞추기: 이름이 맞는 파일은 그 자리, 남는 영상은 sources, 남는 음악은 bgm', () => {
  const spec = { base: 'clips/base.mp4', sources: ['a.mp4'], title: 't' };
  const m = matchFiles(spec, [f('base.mp4', 'video/mp4'), f('a.mp4', 'video/mp4'), f('extra.mov', 'video/quicktime'), f('song.mp3', 'audio/mpeg')]);
  assert.deepEqual(m.spec.sources, ['a.mp4', 'extra.mov']);
  assert.equal(m.spec.bgm, 'song.mp3');
  assert.equal(m.roles['base.mp4'], '기본 영상');
  assert.equal(m.roles['extra.mov'], '소스 2');
  assert.deepEqual(m.missing, []);
  assert.deepEqual(matchFiles({ base: 'x.mp4' }, []).missing, ['x.mp4']);
});

test('파일 맞추기: 배경음이 이미 있으면 남는 음악은 쓰지 않음, 이미지는 AI 명세에서만 참조', () => {
  const m = matchFiles({ base: 'b.mp4', bgm: 'm.mp3' }, [f('b.mp4'), f('m.mp3'), f('other.wav')]);
  assert.equal(m.spec.bgm, 'm.mp3');
  assert.deepEqual(m.unused, ['other.wav']);
  assert.deepEqual(matchFiles({ prompt: 'p' }, [f('ref.png', 'image/png')]).spec.sources, ['ref.png']);
  assert.equal(matchFiles({ base: 'b.mp4' }, [f('b.mp4'), f('ref.png')]).spec.sources, undefined);
  assert.equal(kindOf(f('x.M4A')), 'audio');
  assert.equal(outputName({ output: 'dir/out.mp4' }, 'webm'), 'out.webm');
});

test('Claude: 시스템 프롬프트·도구 스키마가 CLI(shorts/claude.py)와 같다', () => {
  const py = JSON.parse(
    execFileSync('python3', ['-c', 'import json,sys; sys.path.insert(0,"."); from shorts import claude as C; print(json.dumps({"p": C.SYSTEM_PROMPT, "s": C.api_schema()}, ensure_ascii=False))'], { cwd: ROOT }).toString(),
  );
  assert.equal(SYSTEM_PROMPT, py.p);
  assert.deepEqual(apiSchema(), py.s);
});

test('Claude: 요청 본문이 CLI(shorts/claude.py build_request)와 같다 — 구조화 출력, tools·tool_choice 없음', () => {
  const src = [{ name: 'a.mp4', duration: 2.25, width: 1280, height: 720, frames: [{ t: 0.25, b64: 'AAAA' }] }];
  const body = buildRequest('아이디어', src);
  const py = JSON.parse(
    execFileSync('python3', ['-c', 'import json,sys; sys.path.insert(0,"."); from shorts import claude as C; '
      + 'print(json.dumps(C.build_request("아이디어", [{"name": "a.mp4", "duration": 2.25, "width": 1280, "height": 720, "frames": [(0.25, bytes(3))]}]), ensure_ascii=False))'], { cwd: ROOT }).toString(),
  );
  assert.deepEqual(body, py);
  assert.equal(body.model, 'claude-opus-5-5');
  assert.equal(body.output_config.format.type, 'json_schema');
  assert.equal(body.tools, undefined);
  assert.equal(body.tool_choice, undefined);
  assert.equal(body.fallbacks, 'default');
  assert.equal(body.messages[0].content[0].type, 'image');
  assert.match(body.messages[0].content.at(-1).text, /a\.mp4: 2\.3초, 1280×720, 프레임 1장 \(시점: 0\.3초\)/);
  const h = headers('k');
  assert.equal(h['anthropic-dangerous-direct-browser-access'], 'true');
  assert.equal(h['anthropic-beta'], 'server-side-fallback-2026-07-01');
  assert.equal(h['x-api-key'], 'k');
});

test('Claude: 검증 실패면 오류를 붙여 한 번만 다시 묻고(CLI 와 같은 문장), 두 번 다 실패하면 오류', async () => {
  const reply = (obj) => ({ stop_reason: 'end_turn', content: [{ type: 'thinking', thinking: '' }, { type: 'text', text: JSON.stringify(obj) }] });
  const bodies = [];
  const ok = await plan({
    idea: 'i',
    apiKey: 'k',
    post: async (url, body) => {
      bodies.push(structuredClone(body));
      return bodies.length === 1 ? reply({ prompt: 'p', template: 'zoom' }) : reply({ prompt: 'p', template: 'montage' });
    },
  });
  assert.equal(ok.attempts, 2);
  assert.equal(ok.spec.template, 'montage');
  const last = bodies[1].messages.at(-1);
  assert.equal(last.role, 'user');
  assert.match(last.content[0].text, /^위 JSON 이 검증에 실패했습니다\. 아래 오류를 모두 고친 전체 JSON 을 다시 주세요\.\n- template/);
  assert.equal(bodies[1].messages.at(-2).content[0].type, 'thinking'); // 앞 응답 그대로 덧붙임
  await assert.rejects(plan({ idea: 'i', apiKey: 'k', post: async () => reply({ template: 'zoom' }) }), /검증을 통과하지 못했습니다/);
  assert.equal(parseReply({ stop_reason: 'refusal', content: [] }).errors.length, 1);
  assert.equal(parseReply({ stop_reason: 'end_turn', content: [{ type: 'text', text: '{"prompt":"p"}' }] }).obj.prompt, 'p');
  assert.match(parseReply({ stop_reason: 'end_turn', content: [{ type: 'text', text: '[1]' }] }).errors[0], /JSON 객체가 아닙니다/);
  assert.match(parseReply({ stop_reason: 'max_tokens', content: [{ type: 'text', text: '{"pro' }] }).errors[0], /max_tokens/);
});

test('AI: SGLang 요청 본문은 h3video client.py VideoRequest.to_json 과 같은 모양', () => {
  const spec = { prompt: 'p', sources: ['v.mp4', 'i.png'], duration: 6, ratio: '9:16', seed: 3, gen_size: 576 };
  const [sc] = aiScenes(spec);
  assert.equal(sc.task, 'ref2va');
  const body = sglangBody({ ...sc, sources: sc.sources.map((s) => ({ ...s, kind: mediaKind(f(s.path)) })) }, spec, (p) => `data:${p}`);
  assert.deepEqual(body, {
    task: 'ref2va',
    prompt: 'p',
    conditions: [
      { type: 'video', uri: 'data:v.mp4', role: 'reference' },
      { type: 'image', uri: 'data:i.png', role: 'reference' },
    ],
    target: { short_edge: 576, aspect_ratio: '9:16', duration_seconds: 6 },
    seed: 3,
  });
  const fl = sglangBody({ prompt: 'q', task: 'fl2va', image: 'first.png', sources: [], duration: 8, seed: 0 }, {}, (p) => p);
  assert.deepEqual(fl.conditions, [{ type: 'image', uri: 'first.png', role: 'keyframe', frame_index: 0 }]);
  assert.equal(fl.target.short_edge, 768);
  assert.equal(genShortEdge({ gen_size: '432x768' }), 432);
  assert.throws(() => genShortEdge({ gen_size: 1080 }), /768/);
  assert.equal(normProgress(45), 0.45);
  assert.equal(normProgress(0.3), 0.3);
  assert.equal(normProgress('x'), 0);
});
