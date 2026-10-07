// Claude 기획(웹). shorts/claude.py 와 같은 시스템 프롬프트·스키마 변환을 쓴다(tests/unit/web.test.mjs 가 비교).
// 웹은 브라우저에서 Messages API 를 직접 부른다(anthropic-dangerous-direct-browser-access).
// 결과는 write_job 도구 호출(tool use)로 받는다. Opus 5.5 는 tool_choice 강제(type:'tool')를 400 으로 거절하므로
// tool_choice 는 auto 로 두고 프롬프트로 도구 호출을 지시한다. 받은 JSON 은 전체 스키마+의미 검사로 다시 검증하고,
// 실패하면 오류를 tool_result(is_error)로 돌려주며 한 번만 다시 요청한다.
import { schema, checkSpec } from './spec.js';

export const DEFAULT_MODEL = 'claude-opus-5-5';
export const API_VERSION = "2023-06-01";
export const FALLBACK_BETA = "server-side-fallback-2026-07-01";
export const RUNTIME_FIELDS = ["$schema", "server", "ref_server", "backend", "poll", "timeout", "output", "model"];
export const UNSUPPORTED = ["minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "pattern", "title", "$id", "$schema", "x-pattern", "x-presets", "x-hint", "description"];
export const SYSTEM_PROMPT = "너는 세로형 숏폼(9:16, 60초 이하) 기획자다. 사용자의 아이디어(와 소스 영상 프레임)를 보고 작업 명세 JSON 하나를 만든다.\n명세는 두 단계로 실행된다: (1) 사용자의 영상 생성 서버(MiniMax-H3 같은 모델)가 장면 영상을 만들고, (2) 템플릿으로 9:16 숏폼을 합성한다.\n\n규칙\n- scenes: 장면 1~4개. 각 장면 prompt 는 영상 생성용 영어 프롬프트(피사체·동작·카메라·조명·분위기, 1~3문장). 대사가 필요하면 따옴표 안에 한국어로.\n- 장면 duration 은 4~15초 정수. 장면 길이 합계는 15~45초가 적당하다.\n- ratio 는 \"9:16\".\n- title: 상단 훅 문구, 한국어 18자 이내, 궁금증을 만드는 말.\n- captions: 한국어 자막, 한 줄에 한 장면/한 생각, 줄당 22자 이내, 4~10줄. 영상 내용과 맞춘다.\n- 소스 영상이 주어졌을 때:\n  * 소스를 AI 참조로 써서 새 장면을 만들려면 scenes[].sources 에 파일 이름을 넣는다(장면당 영상 3개 이하).\n  * 소스 자체를 주 화면으로 살리려면 base 에 파일 이름을 넣고 template 을 cutaway(소스 위로 AI 장면이 사이사이), split(위 소스·아래 AI), pip(소스 전체·AI 작은 창) 중에서 고른다.\n  * 소스를 보지 않고 지어내지 말고, 프레임에서 보이는 내용에 맞춰 자막과 프롬프트를 쓴다.\n- 소스가 없으면 template 은 \"montage\"(AI 장면을 이어 붙임).\n- 서버 주소·출력 파일 같은 실행 설정은 넣지 않는다.\n- JSON 만 출력한다.";
export const TOOL_NAME = 'write_job';
const TOOL_RULE = '\n- 결과는 텍스트로 쓰지 말고 write_job 도구를 한 번 호출해 낸다. 도구 입력이 곧 작업 명세 JSON 이다.';

function deref(node, root) {
  if (Array.isArray(node)) return node.map((x) => deref(x, root));
  if (node && typeof node === 'object') {
    if (node.$ref) {
      const target = node.$ref.slice(2).split('/').reduce((o, k) => o[k], root);
      return deref(JSON.parse(JSON.stringify(target)), root);
    }
    const out = {};
    for (const [k, v] of Object.entries(node)) if (k !== '$defs') out[k] = deref(v, root);
    return out;
  }
  return node;
}

function strip(node) {
  if (Array.isArray(node)) return node.map(strip);
  if (node && typeof node === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(node)) if (!UNSUPPORTED.includes(k)) out[k] = strip(v);
    return out;
  }
  return node;
}

// 도구 입력 스키마: $ref 펼치기 + 지원 안 되는 제약 제거 + 실행 설정 필드 제거(받은 뒤 전체 스키마로 다시 검사).
export function apiSchema() {
  const sch = deref(JSON.parse(JSON.stringify(schema)), schema);
  for (const k of RUNTIME_FIELDS) delete sch.properties[k];
  return strip(sch);
}

// sources = [{ name, duration, width, height, frames: [{ t, b64 }] }]
export function userContent(idea, sources) {
  const blocks = [];
  const lines = [`아이디어: ${String(idea).trim()}`];
  if (sources.length) {
    lines.push('소스 영상:');
    for (const s of sources) {
      const fr = s.frames || [];
      lines.push(`- ${s.name}: ${(s.duration || 0).toFixed(1)}초, ${s.width || 0}×${s.height || 0}, 프레임 ${fr.length}장 (시점: ${fr.map((f) => `${f.t.toFixed(1)}초`).join(', ')})`);
      for (const f of fr) blocks.push({ type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: f.b64 } });
    }
  } else {
    lines.push('소스 영상: 없음 (AI 장면만으로 만든다)');
  }
  blocks.push({ type: 'text', text: lines.join('\n') });
  return blocks;
}

export function buildRequest(idea, sources, model = DEFAULT_MODEL, maxTokens = 16000) {
  return {
    model,
    max_tokens: maxTokens,
    system: SYSTEM_PROMPT + TOOL_RULE,
    messages: [{ role: 'user', content: userContent(idea, sources) }],
    tools: [{ name: TOOL_NAME, description: '숏폼 작업 명세 JSON 을 제출한다. 입력 전체가 명세다.', input_schema: apiSchema() }],
    tool_choice: { type: 'auto' },
    output_config: { effort: 'medium' },
    fallbacks: 'default',
  };
}

export function headers(apiKey) {
  return {
    'content-type': 'application/json',
    'x-api-key': apiKey,
    'anthropic-version': API_VERSION,
    'anthropic-beta': FALLBACK_BETA,
    'anthropic-dangerous-direct-browser-access': 'true',
  };
}

export class PlanError extends Error {}

// 응답 → { obj, errors, toolUseId }
export function parseReply(resp) {
  if (resp.stop_reason === 'refusal') return { obj: null, errors: ['Claude 가 이 요청을 거절했습니다. 아이디어를 바꿔 보세요'] };
  if (resp.stop_reason === 'max_tokens') return { obj: null, errors: ['응답이 max_tokens 에서 잘렸습니다'] };
  const content = resp.content || [];
  const use = content.find((b) => b.type === 'tool_use' && b.name === TOOL_NAME);
  let obj = null;
  if (use) obj = use.input;
  else {
    const raw = content.filter((b) => b.type === 'text').map((b) => b.text).join('').trim();
    const m = raw.match(/\{[\s\S]*\}/);
    try {
      obj = JSON.parse(m ? m[0] : raw);
    } catch (e) {
      return { obj: null, errors: [`write_job 도구 호출도, 읽을 수 있는 JSON 도 없습니다`] };
    }
  }
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return { obj: null, errors: ['JSON 객체가 아닙니다'], toolUseId: use && use.id };
  const { errors } = checkSpec(obj);
  return { obj, errors, toolUseId: use && use.id };
}

async function defaultPost(url, body, apiKey, signal) {
  let r;
  try {
    r = await fetch(url, { method: 'POST', headers: headers(apiKey), body: JSON.stringify(body), signal });
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    throw new PlanError(`Anthropic API 에 연결하지 못했습니다: ${e.message}`);
  }
  if (!r.ok) {
    const detail = (await r.text().catch(() => '')).slice(0, 300);
    if (r.status === 401) throw new PlanError('Anthropic API 키가 맞지 않습니다(401). 키를 확인하세요');
    if (r.status === 429) throw new PlanError('요청 한도에 걸렸습니다(429). 잠시 뒤 다시 하세요');
    throw new PlanError(`Anthropic API 오류 HTTP ${r.status}: ${detail}`);
  }
  return r.json();
}

// 기획 → 검증 → (실패 시 1회 재요청). 반환 { spec, attempts }
export async function plan({ idea, sources = [], apiKey, model = DEFAULT_MODEL, baseUrl, signal, post = defaultPost, log = () => {} }) {
  if (!apiKey) throw new PlanError('Anthropic API 키를 넣어 주세요');
  if (!String(idea || '').trim()) throw new PlanError('아이디어를 적어 주세요');
  const url = (baseUrl || 'https://api.anthropic.com').replace(/\/+$/, '') + '/v1/messages';
  let body = buildRequest(idea, sources, model);
  let attempts = 0;
  let last = [];
  for (let attempt = 0; attempt < 2; attempt++) {
    attempts += 1;
    const resp = await post(url, body, apiKey, signal);
    const { obj, errors, toolUseId } = parseReply(resp);
    if (obj && !errors.length) return { spec: obj, attempts };
    last = errors;
    log(`검증 실패 ${errors.length}건${attempt === 0 ? ' — 다시 요청합니다' : ''}: ${errors.slice(0, 3).join('; ')}`);
    if (attempt > 0 || resp.stop_reason === 'refusal') break;
    const fix = '위 JSON 이 검증에 실패했습니다. 아래 오류를 모두 고친 전체 명세로 write_job 을 다시 호출하세요.\n- ' + errors.join('\n- ');
    // 응답의 tool_use 마다 tool_result 를 하나씩 돌려줘야 한다(첫 번째에 오류 목록).
    const uses = (resp.content || []).filter((b) => b.type === 'tool_use');
    const results = uses.map((b) => ({ type: 'tool_result', tool_use_id: b.id, is_error: true, content: b.id === toolUseId || uses.length === 1 ? fix : '이 호출은 무시합니다. 위 오류를 고쳐 다시 호출하세요' }));
    const next = { role: 'user', content: results.length ? results : [{ type: 'text', text: fix }] };
    body = { ...body, messages: [...body.messages, { role: 'assistant', content: resp.content || [] }, next] };
  }
  throw new PlanError(`Claude 가 쓴 명세가 두 번 모두 검증에 실패했습니다: ${last.slice(0, 3).join('; ')}`);
}
