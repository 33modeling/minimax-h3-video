// 생성 방식: 로컬 서버(기본) · OpenAI(코덱스) API 키 · Claude API 키.
// 키는 저장하지 않는다: 이 페이지 메모리(모듈 변수)에만 두고 sessionStorage·localStorage 에 쓰지 않는다. 새로고침하면 다시 붙여 넣어야 하고,
// 그 전에는 로컬 서버가 맡는다. 이 화면이 공급자 API(api.openai.com·api.anthropic.com)로 직접 보내고, 로컬 서버·주소(URL)·로그에는 넣지 않는다.
// (그림 만들기 image-maker/web/ai-keys.js 와 같은 틀)
// OpenAI 영상 API(Sora 2, /v1/videos)는 2026-09-24에 닫혔고 대체 API가 없다(OpenAI 공식 문서: video-generation 안내·API 참조·deprecations).
// Claude 도 영상을 만들지 않는다. 그래서 키는 글 쓰는 단계(영상용 프롬프트 쓰기, 장면 수정 지시 반영)에 쓰고 영상은 지금처럼 로컬 서버가 만든다.
export const METHODS = ['local', 'openai', 'claude'];
export const NAMES = {local: '로컬 서버', openai: 'OpenAI', claude: 'Claude'};
export const MODELS = {
  openai: {'gpt-6.1-terra': 'GPT-6.1 Terra · 빠름', 'gpt-6-astra': 'GPT-6 Astra · 좋음'},
  claude: {'claude-opus-5-5': 'Claude Opus 5.5 · 좋음', 'claude-sonnet-5-5': 'Claude Sonnet 5.5 · 빠름'},
};
export const DEFAULT_MODELS = {openai: 'gpt-6.1-terra', claude: 'claude-opus-5-5'};   // claude 는 숏폼(shortform/src/core/claude.js)과 같은 모델
export const ENDPOINTS = {openai: 'https://api.openai.com/v1/responses', claude: 'https://api.anthropic.com/v1/messages'};
export const ANTHROPIC_VERSION = '2023-06-01';
export const STORE_KEYS = {method: 'h3video.ai.method', openaiModel: 'h3video.ai.openaiModel', claudeModel: 'h3video.ai.claudeModel'};
// 예전 판이 키를 저장하던 이름. 열 때마다 두 저장소에서 지운다.
export const OLD_KEY_ENTRIES = ['h3video.ai.remember', 'h3video.ai.openaiKey', 'h3video.ai.claudeKey'];
export class AiError extends Error {}

const attempt = (fn, fallback) => { try { return fn(); } catch { return fallback; } };
const ownStorage = name => attempt(() => globalThis[name] || null, null);

// 키는 이 변수에만 있다(새로고침하면 사라진다).
const memoryKeys = {openai: '', claude: ''};
// 방식·모델만 localStorage 에 둔다. 저장소가 막혀도(사생활 모드·미리보기) 화면은 돈다: 모든 읽기·쓰기를 try 로 감싼다.
export function keyStore({session = ownStorage('sessionStorage'), local = ownStorage('localStorage')} = {}) {
  const get = (s, k) => attempt(() => (s ? s.getItem(k) : null), null);
  const put = (s, k, v) => attempt(() => { if (!s) return false; if (v == null || v === '') s.removeItem(k); else s.setItem(k, v); return true; }, false);
  for (const s of [session, local]) for (const k of OLD_KEY_ENTRIES) attempt(() => s && s.removeItem(k), null);
  const key = p => (p === 'openai' || p === 'claude' ? memoryKeys[p] : '');
  const setKey = (p, value) => { if (p !== 'openai' && p !== 'claude') return false; memoryKeys[p] = String(value || '').trim(); return true; };
  return {
    key, setKey,
    clear() { memoryKeys.openai = ''; memoryKeys.claude = ''; },
    method() { const m = get(local, STORE_KEYS.method); return METHODS.includes(m) ? m : 'local'; },
    setMethod: m => put(local, STORE_KEYS.method, METHODS.includes(m) && m !== 'local' ? m : null),
    model(p) { const m = get(local, STORE_KEYS[p + 'Model']); return MODELS[p]?.[m] ? m : DEFAULT_MODELS[p]; },
    setModel: (p, m) => put(local, STORE_KEYS[p + 'Model'], MODELS[p]?.[m] && m !== DEFAULT_MODELS[p] ? m : null),
  };
}

// 고른 방식과 넣은 키 → 글·영상을 누가 맡는가. 키가 없으면 지금처럼 로컬 서버.
export function resolveProviders({method = 'local', openaiKey = '', claudeKey = ''} = {}) {
  const want = METHODS.includes(method) ? method : 'local';
  const key = want === 'openai' ? openaiKey : want === 'claude' ? claudeKey : '';
  const text = want !== 'local' && String(key || '').trim() ? want : 'local';
  return {method: want, text, video: 'local', missingKey: want !== 'local' && text === 'local'};
}

export const redact = s => String(s ?? '').replace(/sk-[\w\-*.]+/g, 'sk-…');

export const WRITE_SYSTEM = `You write prompts for MiniMax H3, a video model that generates picture and sound together.
Turn the user's request into one detailed English prompt for the requested video.
- Describe what is on screen shot by shot: composition, subject, setting, action, camera movement and lighting.
- Describe the sound: dialogue, sound effects, ambience and music.
- Keep every detail the user asked for and add only concrete details. Do not change the subject, setting or story.
- Keep dialogue, lyrics and on-screen text in their original language (for example Korean) inside double quotes.
- Keep input labels exactly as given (<Picture 1>, <Video 1>, <Audio 1>).
- Match the requested duration and aspect ratio.
- Output only the prompt text. No title, no headings, no markdown, no explanations.`;

export const REVISE_SYSTEM = `You edit prompts for a video generation model. Apply the user's edit instruction to the prompt.
- Change only what the instruction asks for. Keep every other detail, the language, labels such as <Picture 1>, and the layout of the prompt (keep field names such as "integrated_multimodal_description:" when present).
- Output only the revised prompt. No headings, no markdown, no explanations.`;

// 입력 번호는 서버 다듬기와 같은 규칙: 종류별로 넣은 순서대로 <Picture 1>·<Video 1>·<Audio 1>.
export function referenceLabels(refs = []) {
  const n = {image: 0, video: 0, audio: 0}, word = {image: 'Picture', video: 'Video', audio: 'Audio'};
  return refs.filter(r => word[r.kind]).map(r => ({...r, label: `${word[r.kind]} ${++n[r.kind]}`}));
}

export function writeUserText({prompt, seconds, aspect, mode, hasFirst = false, hasLast = false, refs = []}) {
  const lines = [`Duration: ${seconds} seconds.`, `Aspect ratio: ${aspect}.`];
  if (mode === 'fl') {
    if (hasFirst && hasLast) lines.push('<Picture 1> (shown first) is the first frame and <Picture 2> (shown second) is the last frame of the video.');
    else if (hasFirst) lines.push('<Picture 1> (shown) is the first frame of the video.');
    else if (hasLast) lines.push('<Picture 1> (shown) is the last frame of the video.');
  }
  if (mode === 'ref' && refs.length) {
    lines.push('Reference inputs in upload order. The user may call them 1번 사진, 1번 영상, 1번 소리 and so on: '
      + referenceLabels(refs).map(r => `<${r.label}> = reference ${r.kind === 'image' ? 'picture' : r.kind}${r.shown ? ' (shown)' : ''}`).join('; ') + '.');
  }
  lines.push('User request (it may be in Korean):', String(prompt || '').trim());
  return lines.join('\n');
}

export function reviseUserText({prompt, instructions}) {
  return `Prompt:\n${String(prompt || '').trim()}\n\nEdit instruction (it may be in Korean):\n${String(instructions || '').trim()}`;
}

// 요청 만들기. 키는 헤더에만 넣는다(주소에 넣지 않는다).
export function buildTextRequest(provider, {key, model, system, text, images = [], maxTokens} = {}) {
  const k = String(key || '').trim();
  if (!MODELS[provider]) throw new AiError('글을 쓸 곳(OpenAI 또는 Claude)을 고르세요.');
  if (!k) throw new AiError(`${NAMES[provider]} API 키를 넣어 주세요.`);
  const m = MODELS[provider][model] ? model : DEFAULT_MODELS[provider];
  if (provider === 'openai') {
    const content = [...images.map(im => ({type: 'input_image', image_url: `data:${im.type};base64,${im.data}`})), {type: 'input_text', text}];
    return {url: ENDPOINTS.openai, init: {method: 'POST', headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + k},
      body: JSON.stringify({model: m, instructions: system, input: [{role: 'user', content}], max_output_tokens: maxTokens || 6000, reasoning: {effort: 'low'}, store: false})}};
  }
  // Opus 5.5·Sonnet 5.5 는 생각(adaptive thinking)이 늘 켜져 있고 생각한 토큰도 max_tokens 에 들어가서 넉넉히 둔다(storybook-conti/core.js 와 같은 판단).
  const content = [...images.map(im => ({type: 'image', source: {type: 'base64', media_type: im.type, data: im.data}})), {type: 'text', text}];
  return {url: ENDPOINTS.claude, init: {method: 'POST', headers: {'content-type': 'application/json', 'x-api-key': k, 'anthropic-version': ANTHROPIC_VERSION,
    'anthropic-dangerous-direct-browser-access': 'true'},
    body: JSON.stringify({model: m, max_tokens: maxTokens || 8000, system, messages: [{role: 'user', content}], output_config: {effort: 'low'}})}};
}

// HTTP 오류 → 쉬운 한국어. 원래 메시지는 괄호에(키처럼 보이는 글자는 가린다). 401 은 원래 메시지를 붙이지 않는다(가린 키가 들어 있다).
export function describeError(provider, status, raw = '') {
  const name = NAMES[provider] || 'API';
  let msg = '', code = '', type = '';
  try { const j = JSON.parse(raw); msg = String(j?.error?.message || ''); code = String(j?.error?.code || ''); type = String(j?.error?.type || ''); }
  catch { msg = String(raw || '').replace(/\s+/g, ' ').trim(); }
  msg = redact(msg).slice(0, 160);
  const said = msg ? ` (원래 메시지: ${msg})` : '';
  if (status === 401) return `${name} API 키가 맞지 않아요(401). 키를 확인하세요.`;
  if (status === 403) return `이 키로는 쓸 수 없어요(403). 키의 권한과 결제 상태를 확인하세요.${said}`;
  if (status === 404) return `고른 모델을 이 키로 찾지 못했어요(404). 다른 모델을 고르세요.${said}`;
  if (status === 429 && (code === 'insufficient_quota' || /quota|billing|credit/i.test(msg))) return `${name} 계정의 크레딧이나 사용 한도가 모자라요(429). 결제 상태를 확인하세요.`;
  if (status === 429) return '요청 한도에 걸렸어요(429). 잠시 뒤 다시 하세요.';
  if (status === 400 && /credit balance/i.test(msg)) return `${name} 계정의 크레딧이 모자라요(400). 결제 상태를 확인하세요.`;
  if (status === 529 || status === 503 || type === 'overloaded_error') return `${name} 서버가 붐벼요(${status}). 잠시 뒤 다시 하세요.`;
  if (status >= 500) return `${name} 서버에 잠깐 문제가 있어요(${status}). 잠시 뒤 다시 하세요.`;
  return `${name} API가 요청을 받지 않았어요(${status}).${said}`;
}

const clean = t => String(t || '').replace(/^```[a-zA-Z]*\s*\n?/, '').replace(/\n?```\s*$/, '').trim();

// 응답 → 글. 거절·안전 기준·잘림은 오류로 알린다(잘린 프롬프트로 영상을 만들지 않는다).
export function parseText(provider, data) {
  const name = NAMES[provider];
  if (provider === 'openai') {
    const parts = (data?.output || []).filter(o => o?.type === 'message').flatMap(o => o.content || []);
    if (parts.some(p => p?.type === 'refusal')) throw new AiError('OpenAI가 이 요청을 거절했어요. 글을 바꿔 다시 하세요.');
    if (data?.status === 'failed') throw new AiError(`OpenAI가 글을 쓰지 못했어요${data?.error?.message ? ` (원래 메시지: ${redact(data.error.message).slice(0, 160)})` : ''}.`);
    if (data?.status === 'incomplete') {
      if (data?.incomplete_details?.reason === 'content_filter') throw new AiError('OpenAI 안전 기준에 걸려 글을 쓰지 않았어요. 글을 바꿔 다시 하세요.');
      throw new AiError('OpenAI 응답이 길이 한도에서 잘렸어요. 다시 하세요.');
    }
    const text = clean(parts.filter(p => p?.type === 'output_text').map(p => p.text || '').join('') || data?.output_text);
    if (!text) throw new AiError('OpenAI가 빈 글을 돌려줬어요. 다시 하세요.');
    return text;
  }
  if (data?.stop_reason === 'refusal') throw new AiError('Claude가 이 요청을 거절했어요. 글을 바꿔 다시 하세요.');
  if (data?.stop_reason === 'max_tokens') throw new AiError('Claude 응답이 길이 한도에서 잘렸어요. 다시 하세요.');
  const text = clean((data?.content || []).filter(b => b?.type === 'text').map(b => b.text || '').join(''));
  if (!text) throw new AiError(`${name}가 빈 글을 돌려줬어요. 다시 하세요.`);
  return text;
}

// 틀린 키로 POST /v1/responses 를 보내면 OpenAI 가 CORS 머리글(access-control-allow-origin) 없는 401 을 돌려줘서, 브라우저에는
// 'Failed to fetch'(연결 실패)로만 보인다(2026-10-29 curl·Chrome 으로 확인). 같은 키로 GET /v1/models/{모델} 은 CORS 머리글이 붙은
// 401·404 를 돌려주므로, 연결 실패 뒤 한 번 물어 원인을 가린다. 키는 Authorization 헤더에만 넣는다. 원인을 모르면 null.
export async function probeOpenAI({key, model, base = 'https://api.openai.com/v1', fetchImpl = globalThis.fetch, timeoutMs = 15000} = {}) {
  try {
    const res = await fetchImpl(`${String(base).replace(/\/+$/, '')}/models/${encodeURIComponent(model)}`,
      {headers: {Authorization: 'Bearer ' + String(key || '').trim()}, signal: AbortSignal.timeout ? AbortSignal.timeout(timeoutMs) : undefined});
    return res.ok ? null : {status: res.status, raw: await res.text().catch(() => '')};
  } catch { return null; }
}

export async function generateText(provider, {fetchImpl = globalThis.fetch, timeoutMs = 120000, ...opts} = {}) {
  const {url, init} = buildTextRequest(provider, opts);
  const name = NAMES[provider];
  let res;
  try { res = await fetchImpl(url, {...init, signal: AbortSignal.timeout ? AbortSignal.timeout(timeoutMs) : undefined}); }
  catch (e) {
    if (e?.name === 'TimeoutError' || e?.name === 'AbortError') throw new AiError(`${name} 응답이 너무 늦어 멈췄어요. 잠시 뒤 다시 하세요.`);
    const why = provider === 'openai' ? await probeOpenAI({key: opts.key, model: JSON.parse(init.body).model, fetchImpl}) : null;
    if (why) throw new AiError(describeError(provider, why.status, why.raw));
    throw new AiError(`${name} API에 연결하지 못했어요. 인터넷 연결을 확인하세요.`);
  }
  const raw = await res.text().catch(() => '');
  if (!res.ok) throw new AiError(describeError(provider, res.status, raw));
  let data;
  try { data = JSON.parse(raw); } catch { throw new AiError(`${name} 응답을 읽지 못했어요.`); }
  return parseText(provider, data);
}

// 그림을 짧은 변 기준으로 줄여 JPEG base64 로(글 쓰는 모델이 보게). 못 읽으면 null.
export async function imagePart(file, longest = 768) {
  try {
    const bitmap = await createImageBitmap(file);
    const s = Math.min(1, longest / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * s)); canvas.height = Math.max(1, Math.round(bitmap.height * s));
    canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.85));
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let bin = '';
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return {type: 'image/jpeg', data: btoa(bin)};
  } catch { return null; }
}

const DESC = {
  local: '지금처럼 이 PC의 로컬 서버가 글 다듬기와 영상 만들기를 모두 맡아요.',
  openai: 'OpenAI가 2026년 9월 24일에 영상 API(Sora 2)를 닫아서, OpenAI 키로는 영상용 글만 쓰고 영상은 로컬 서버가 만들어요.',
  claude: 'Claude는 영상을 만들지 못해서, Claude 키로는 영상용 글만 쓰고 영상은 로컬 서버가 만들어요.',
};
const NOTE = {
  openai: 'OpenAI 키는 이 화면이 api.openai.com으로 직접 보내요. 로컬 서버로는 보내지 않아요. 사용 요금은 키 주인의 OpenAI 계정에 청구돼요.',
  claude: 'Claude 키는 이 화면이 api.anthropic.com으로 직접 보내요. 로컬 서버로는 보내지 않아요. 사용 요금은 키 주인의 Anthropic 계정에 청구돼요.',
};
const PLACEHOLDER = {openai: 'sk-...', claude: 'sk-ant-...'};
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

// '생성 방식' 칸. root 는 <fieldset>. 돌려주는 값으로 글쓰기를 부른다.
export function mountAiMethod(root, {onChange = () => {}, getMode = () => '', store = keyStore(), fetchImpl} = {}) {
  let method = store.method();
  const keys = {openai: store.key('openai'), claude: store.key('claude')};
  root.innerHTML = `<legend class="lab">생성 방식</legend>
    <div class="ai-opts" role="radiogroup" aria-label="생성 방식">${METHODS.map(m => `<label class="ai-opt"><input type="radio" name="ai-method" value="${m}"><span>${m === 'local' ? '로컬 서버' : m === 'openai' ? 'OpenAI(코덱스) API 키' : 'Claude API 키'}</span></label>`).join('')}</div>
    <p class="help" data-ai-desc></p>
    <div class="ai-key" data-ai-key hidden>
      <label class="lab" for="ai-key-input" data-ai-key-label>API 키</label>
      <div class="ai-row"><input id="ai-key-input" type="password" autocomplete="off" spellcheck="false" autocapitalize="off" aria-describedby="ai-key-note"><select id="ai-model" aria-label="글 쓰는 모델"></select></div>
      <div class="ai-row"><button type="button" class="btn" id="ai-clear">키 지우기</button></div>
      <p class="help" data-ai-nostore>키는 저장하지 않습니다. 새로고침하면 다시 붙여 넣어야 합니다.</p>
      <p class="help" id="ai-key-note" data-ai-note></p>
    </div>
    <p class="help ai-status" data-ai-status role="status" aria-live="polite"></p>`;
  const q = s => root.querySelector(s), input = q('#ai-key-input'), model = q('#ai-model');
  const providers = () => resolveProviders({method, openaiKey: keys.openai, claudeKey: keys.claude});
  const status = (text, bad = false) => { const el = q('[data-ai-status]'); el.textContent = text; el.classList.toggle('bad', bad); };
  function summary() {
    const p = providers();
    if (p.method === 'local') return '';
    if (p.missingKey) return '키를 넣기 전에는 지금처럼 로컬 서버가 다 맡아요.';
    const story = getMode() === 'story' ? ' JSON 한번에는 장면 글을 JSON에서 그대로 가져와 키를 쓰지 않아요.' : '';
    return `지금 설정: 글은 ${MODELS[p.text][store.model(p.text)].split(' · ')[0]}, 영상은 로컬 서버가 맡아요.${story}`;
  }
  function render() {
    for (const r of root.querySelectorAll('input[name=ai-method]')) r.checked = r.value === method;
    q('[data-ai-desc]').textContent = DESC[method];
    const keyed = method !== 'local';
    q('[data-ai-key]').hidden = !keyed;
    if (keyed) {
      q('[data-ai-key-label]').textContent = `${NAMES[method]} API 키`;
      input.placeholder = PLACEHOLDER[method]; input.value = keys[method];
      model.innerHTML = Object.entries(MODELS[method]).map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join('');
      model.value = store.model(method);
      q('[data-ai-note]').textContent = NOTE[method];
    }
    status(summary());
  }
  root.addEventListener('change', e => {
    if (e.target.name === 'ai-method') { method = METHODS.includes(e.target.value) ? e.target.value : 'local'; store.setMethod(method); render(); onChange(); }
    else if (e.target === model && method !== 'local') { store.setModel(method, model.value); status(summary()); onChange(); }
  });
  input.addEventListener('keydown', e => { if (e.key === 'Enter') e.preventDefault(); });   // 폼 안: Enter 가 영상 만들기를 누르지 않게
  input.addEventListener('input', () => { if (method === 'local') return; keys[method] = input.value.trim(); store.setKey(method, keys[method]); status(summary()); onChange(); });
  q('#ai-clear').addEventListener('click', () => {
    store.clear(); keys.openai = ''; keys.claude = ''; input.value = '';
    status('OpenAI·Claude 키를 지웠어요. 키를 넣기 전에는 로컬 서버가 다 맡아요.'); onChange();
  });
  render();
  const call = (system, text, images = []) => {
    const p = providers();
    if (p.text === 'local') throw new AiError('키가 없어요. 생성 방식에서 키를 넣어 주세요.');
    return generateText(p.text, {key: keys[p.text], model: store.model(p.text), system, text, images, fetchImpl});
  };
  return {
    providers, refresh: () => status(summary()),
    // '생성 방식' 요약 줄(접힌 칸 제목 옆)
    label() { const p = providers(); return p.method === 'local' ? '로컬 서버' : `${NAMES[p.method]} 키 · ${p.missingKey ? '키 없음, 로컬 서버' : `글은 ${NAMES[p.text]}, 영상은 로컬 서버`}`; },
    active: () => providers().text !== 'local',
    name: () => NAMES[providers().text],
    // 영상용 글 쓰기. first/last/refs 는 File(그림만 모델에 보여 준다, 최대 4장).
    async write({prompt, seconds, aspect, mode, first = null, last = null, refs = []}) {
      const shown = [];
      if (mode === 'fl') for (const f of [first, last]) if (f) shown.push(f);
      const labelled = mode === 'ref' ? referenceLabels(refs) : [];
      if (mode === 'ref') for (const r of labelled) if (r.kind === 'image' && shown.length < 4) { shown.push(r.file); r.shown = true; }
      const images = (await Promise.all(shown.map(f => imagePart(f)))).filter(Boolean);
      return call(WRITE_SYSTEM, writeUserText({prompt, seconds, aspect, mode, hasFirst: !!first, hasLast: !!last, refs: labelled}), images);
    },
    revise: ({prompt, instructions}) => call(REVISE_SYSTEM, reviseUserText({prompt, instructions})),
  };
}
