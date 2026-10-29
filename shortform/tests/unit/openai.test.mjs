// 숏폼 기획을 OpenAI 키로: Claude 요청 본문 → Responses 요청, 응답·오류, plan() 이 OpenAI 모델을 api.openai.com 으로만 보내는지.
import test from 'node:test';
import assert from 'node:assert/strict';
import { responsesBody, openaiMessage, openaiErrorText, isOpenAIModel, OPENAI_MODELS } from '../../src/core/openai-client.js';
import { buildRequest, plan } from '../../src/core/claude.js';
import { EXAMPLE_JOB } from '../../src/app/example.js';

const KEY = 'sk-test-shorts-openai-0123456789';
const ok = (body) => new Response(JSON.stringify(body), { status: 200 });
const reply = (obj, extra = {}) => ({ status: 'completed', output: [{ type: 'reasoning', summary: [] }, { type: 'message', content: [{ type: 'output_text', text: JSON.stringify(obj) }] }], ...extra });

test('OpenAI models are the same list as the video maker setting', () => {
  assert.deepEqual(Object.keys(OPENAI_MODELS), ['gpt-6.1-terra', 'gpt-6-astra']);
  assert.equal(isOpenAIModel('gpt-6.1-terra'), true);
  assert.equal(isOpenAIModel('claude-opus-5-5'), false);
  assert.equal(isOpenAIModel('toString'), false);
});

test('Claude request body becomes a Responses request with the same instructions and schema', () => {
  const sources = [{ name: 'a.mp4', duration: 3, width: 720, height: 1280, frames: [{ t: 1, b64: 'QUJD' }] }];
  const claude = buildRequest('비 오는 날 커피', sources, 'gpt-6.1-terra');
  claude.messages.push({ role: 'assistant', content: [{ type: 'text', text: '{"x":1}' }] }, { role: 'user', content: [{ type: 'text', text: '고쳐 주세요' }] });
  const body = responsesBody(claude, 'gpt-6.1-terra');
  assert.equal(body.model, 'gpt-6.1-terra');
  assert.equal(body.instructions, claude.system);
  assert.equal(body.store, false);
  assert.equal(body.max_output_tokens, claude.max_tokens);
  assert.deepEqual(body.input[0].content[0], { type: 'input_image', image_url: 'data:image/jpeg;base64,QUJD' });
  assert.equal(body.input[0].content.at(-1).type, 'input_text');
  assert.match(body.input[0].content.at(-1).text, /비 오는 날 커피/);
  assert.deepEqual(body.input[1], { role: 'assistant', content: '{"x":1}' });
  assert.deepEqual(body.input[2], { role: 'user', content: [{ type: 'input_text', text: '고쳐 주세요' }] });
  assert.equal(body.text.format.type, 'json_schema');
  assert.equal(body.text.format.strict, false);
  assert.deepEqual(body.text.format.schema, claude.output_config.format.schema);
  assert.equal('fallbacks' in body, false);
});

test('openaiMessage sends the key only in the Authorization header and maps stop reasons', async () => {
  const calls = [];
  const fetchImpl = async (url, init) => { calls.push({ url, init }); return ok(reply({ a: 1 })); };
  const r = await openaiMessage({ body: buildRequest('i', [], 'gpt-6.1-terra'), apiKey: KEY, model: 'gpt-6.1-terra', fetchImpl });
  assert.deepEqual(r, { text: '{"a":1}', stop_reason: 'end_turn' });
  assert.equal(calls[0].url, 'https://api.openai.com/v1/responses');
  assert.equal(calls[0].init.headers.Authorization, 'Bearer ' + KEY);
  assert.ok(!calls[0].url.includes(KEY) && !calls[0].init.body.includes(KEY));
  const cut = await openaiMessage({ body: buildRequest('i', []), apiKey: KEY, model: 'gpt-6.1-terra', fetchImpl: async () => ok({ status: 'incomplete', incomplete_details: { reason: 'max_output_tokens' }, output: [] }) });
  assert.equal(cut.stop_reason, 'max_tokens');
  const refused = await openaiMessage({ body: buildRequest('i', []), apiKey: KEY, model: 'gpt-6.1-terra', fetchImpl: async () => ok({ status: 'completed', output: [{ type: 'message', content: [{ type: 'refusal', refusal: 'no' }] }] }) });
  assert.equal(refused.stop_reason, 'refusal');
  await assert.rejects(openaiMessage({ body: buildRequest('i', []), apiKey: '', model: 'gpt-6.1-terra', fetchImpl }), /OpenAI API 키를 넣어/);
  await assert.rejects(openaiMessage({ body: buildRequest('i', []), apiKey: KEY, model: 'gpt-6.1-terra', fetchImpl: async () => new Response(JSON.stringify({ error: { message: 'Incorrect API key provided: sk-abc***' } }), { status: 401 }) }), (e) => /키가 맞지 않습니다\(401\)/.test(e.message) && !e.message.includes('sk-'));
});

test('a wrong key that the browser sees only as a failed fetch is named by a model lookup', async () => {
  // 실제 OpenAI 는 틀린 키의 POST /v1/responses 에 CORS 머리글 없는 401 을 돌려줘 브라우저에서는 fetch 가 TypeError 로 끝난다.
  const seen = [];
  const fetchImpl = async (url, init) => {
    seen.push({ url, init });
    if (url.endsWith('/responses')) throw new TypeError('Failed to fetch');
    return new Response(JSON.stringify({ error: { message: 'Incorrect API key provided: sk-proj-****abcd.', code: 'invalid_api_key' } }), { status: 401 });
  };
  await assert.rejects(openaiMessage({ body: buildRequest('i', []), apiKey: KEY, model: 'gpt-6.1-terra', fetchImpl }), (e) => /키가 맞지 않습니다\(401\)/.test(e.message) && !e.message.includes('sk-'));
  assert.equal(seen[1].url, 'https://api.openai.com/v1/models/gpt-6.1-terra');
  assert.equal(seen[1].init.headers.Authorization, 'Bearer ' + KEY);
  assert.ok(!seen[1].url.includes(KEY));
  await assert.rejects(openaiMessage({ body: buildRequest('i', []), apiKey: KEY, model: 'gpt-6.1-terra', fetchImpl: async () => { throw new TypeError('Failed to fetch'); } }), /연결하지 못했습니다/);
  const aborted = new Error('aborted'); aborted.name = 'AbortError';
  await assert.rejects(openaiMessage({ body: buildRequest('i', []), apiKey: KEY, model: 'gpt-6.1-terra', fetchImpl: async () => { throw aborted; } }), (e) => e === aborted);
});

test('HTTP errors read as plain Korean', () => {
  assert.match(openaiErrorText(429, JSON.stringify({ error: { message: 'You exceeded your current quota', code: 'insufficient_quota' } })), /크레딧이나 사용 한도/);
  assert.match(openaiErrorText(429, '{}'), /요청 한도에 걸렸습니다/);
  assert.match(openaiErrorText(503, ''), /잠깐 문제/);
  assert.ok(!openaiErrorText(400, JSON.stringify({ error: { message: 'bad sk-live-123456 x' } })).includes('123456'));
});

test('plan() with an OpenAI model asks api.openai.com, validates, and retries once', async () => {
  const real = globalThis.fetch, seen = [];
  const good = JSON.parse(JSON.stringify(EXAMPLE_JOB));
  for (const k of ['$schema', 'server', 'ref_server', 'backend', 'poll', 'timeout', 'output', 'model']) delete good[k];
  let n = 0;
  globalThis.fetch = async (url, init) => { seen.push({ url, body: JSON.parse(init.body) }); n += 1; return ok(reply(n === 1 ? { template: 'zoom' } : good)); };
  try {
    await assert.rejects(plan({ idea: 'i', model: 'gpt-6.1-terra', apiKey: '' }), /OpenAI API 키를 넣어/);
    const res = await plan({ idea: '30초 카페 브이로그', model: 'gpt-6.1-terra', apiKey: KEY, connection: { configured: true, messagesURL: 'https://hub/creative-ai/api/messages' } });
    assert.equal(res.attempts, 2);
    assert.ok(seen.every((r) => r.url === 'https://api.openai.com/v1/responses'));
    assert.equal(seen[1].body.input.length, 3);
    assert.match(JSON.stringify(seen[1].body.input[2]), /검증에 실패했습니다/);
  } finally { globalThis.fetch = real; }
});

// 키는 저장하지 않는다(영상 만들기 '생성 방식'과 같은 틀): 메모리에만, 예전 판이 저장한 키 칸은 열 때 두 저장소에서 지운다.
test('API keys are never stored: shared OpenAI slot stays in memory, old entries are removed', async () => {
  const { keyStore, OLD_KEY_ENTRIES } = await import('../../../src/h3video/studio/ai-keys.js');
  const memory = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), map: m }; };
  const session = memory(), local = memory();
  for (const s of [session, local]) for (const k of OLD_KEY_ENTRIES) s.setItem(k, KEY);
  const store = keyStore({ session, local });
  assert.equal(session.map.size + local.map.size, 0);
  store.setKey('openai', KEY);
  assert.equal(store.key('openai'), KEY);
  for (const s of [session, local]) for (const v of s.map.values()) assert.ok(!v.includes(KEY));
  store.clear();
  assert.equal(store.key('openai'), '');
  const { readFileSync } = await import('node:fs');
  const main = readFileSync(new URL('../../src/main.js', import.meta.url), 'utf8');
  const html = readFileSync(new URL('../../index.html', import.meta.url), 'utf8');
  assert.doesNotMatch(main, /LS\.set\('shorts\.anthropicKey'|LS\.get\('shorts\.anthropicKey'|setRemember|openaiRemember/);
  assert.match(main, /removeItem\(OLD_CLAUDE_KEY\)/);
  assert.doesNotMatch(html, /이 기기에 저장|openaiRemember|localStorage\)에만 저장/);
  assert.equal(html.split('키는 저장하지 않습니다. 새로고침하면 다시 붙여 넣어야 합니다.').length - 1, 2);
});
