// 숏폼 기획을 OpenAI 키로(웹). Claude 기획과 같은 요청 본문(시스템 프롬프트·스키마·검증·1회 재요청, core/claude.js)을
// OpenAI Responses API(POST /v1/responses) 모양으로 바꿔 브라우저에서 api.openai.com 으로 직접 보낸다. 키는 Authorization 헤더에만 넣는다.
// OpenAI 영상 API(Sora 2)는 2026-09-24에 닫혀서 장면 영상은 지금처럼 영상 서버가 만든다. 여기서는 글(작업 JSON)만 쓴다.
import { MODELS } from '../../../src/h3video/studio/ai-keys.js';

export const OPENAI_MODELS = MODELS.openai;   // 영상 만들기 '생성 방식'과 같은 모델 목록
export const OPENAI_BASE = 'https://api.openai.com/v1';
export const isOpenAIModel = (model) => Object.prototype.hasOwnProperty.call(OPENAI_MODELS, model);

const text = (content) => (typeof content === 'string' ? content : (content || []).filter((b) => b.type === 'text').map((b) => b.text || '').join(''));

// Claude 요청 본문(system, messages[{role, content:[text|image(base64)]}], output_config.format.schema, max_tokens) → Responses 요청 본문
export function responsesBody(body, model) {
  const input = (body.messages || []).map((m) => (m.role === 'assistant'
    ? { role: 'assistant', content: text(m.content) }
    : { role: 'user', content: (typeof m.content === 'string' ? [{ type: 'text', text: m.content }] : m.content || []).filter((b) => b.type === 'text' || b.type === 'image')
      .map((b) => (b.type === 'image' ? { type: 'input_image', image_url: `data:${b.source.media_type};base64,${b.source.data}` } : { type: 'input_text', text: b.text || '' })) }));
  const schema = body.output_config?.format?.schema;
  return {
    model, instructions: body.system, input, max_output_tokens: body.max_tokens || 16000, reasoning: { effort: 'medium' }, store: false,
    // strict:false — 스키마를 지시로 쓰고, 받은 JSON 은 core/claude.js 가 전체 스키마+의미 검사로 다시 확인한다.
    ...(schema ? { text: { format: { type: 'json_schema', name: 'shortform_spec', schema, strict: false } } } : {}),
  };
}

export function openaiErrorText(status, raw = '') {
  let msg = '', code = '';
  try { const j = JSON.parse(raw); msg = String(j?.error?.message || ''); code = String(j?.error?.code || ''); } catch { msg = String(raw || '').replace(/\s+/g, ' ').trim(); }
  msg = msg.replace(/sk-[\w\-*.]+/g, 'sk-…').slice(0, 200);
  const tail = msg ? ` (원래 메시지: ${msg})` : '';
  if (status === 401) return 'OpenAI API 키가 맞지 않습니다(401). 키를 확인하세요';
  if (status === 403) return `이 키로는 쓸 수 없습니다(403). 키의 권한·결제 상태를 확인하세요${tail}`;
  if (status === 404) return `고른 모델을 이 키로 찾지 못했습니다(404). 다른 모델을 고르세요${tail}`;
  if (status === 429 && (code === 'insufficient_quota' || /quota|billing/i.test(msg))) return 'OpenAI 계정의 크레딧이나 사용 한도가 모자랍니다(429). 결제 상태를 확인하세요';
  if (status === 429) return '요청 한도에 걸렸습니다(429). 잠시 뒤 다시 하세요';
  if (status >= 500) return `OpenAI 서버에 잠깐 문제가 있습니다(${status}). 잠시 뒤 다시 하세요`;
  return `OpenAI API 오류 HTTP ${status}${tail}`;
}

// → { text, stop_reason } (Qwen 클라이언트와 같은 모양: end_turn · max_tokens · refusal)
export async function openaiMessage({ body, apiKey, model, baseUrl, signal, fetchImpl = globalThis.fetch }) {
  const key = String(apiKey || '').trim();
  if (!key) throw new Error('OpenAI API 키를 넣어 주세요');
  const url = String(baseUrl || OPENAI_BASE).replace(/\/+$/, '') + '/responses';
  let res;
  try {
    res = await fetchImpl(url, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + key }, body: JSON.stringify(responsesBody(body, model)), signal });
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    throw new Error('OpenAI API 에 연결하지 못했습니다. 인터넷 연결을 확인하세요');
  }
  const raw = await res.text().catch(() => '');
  if (!res.ok) throw new Error(openaiErrorText(res.status, raw));
  let data;
  try { data = JSON.parse(raw); } catch { throw new Error('OpenAI 응답을 읽지 못했습니다'); }
  const parts = (data.output || []).filter((o) => o?.type === 'message').flatMap((o) => o.content || []);
  if (parts.some((p) => p?.type === 'refusal') || data.incomplete_details?.reason === 'content_filter') return { text: '', stop_reason: 'refusal' };
  if (data.status === 'failed') throw new Error(`OpenAI 가 기획을 쓰지 못했습니다${data.error?.message ? ` (원래 메시지: ${String(data.error.message).slice(0, 200)})` : ''}`);
  const out = parts.filter((p) => p?.type === 'output_text').map((p) => p.text || '').join('');
  return { text: out, stop_reason: data.status === 'incomplete' ? 'max_tokens' : 'end_turn' };
}
