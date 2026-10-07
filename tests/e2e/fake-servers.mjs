// 웹 e2e 용 가짜 서버(같은 node 프로세스 안에서 뜬다). 모두 CORS 를 허용한다.
// - h3video : minimax-h3-video `h3video web` 흉내 (/api/spec, /api/health, POST /api/jobs multipart, /api/jobs/{id}, /files/{id}/{name})
// - sglang  : SGLang /v1/videos 흉내 (POST JSON, GET 상태, /content, DELETE, /v1/models)
// - anthropic : POST /v1/messages — 정해 둔 응답을 차례로 돌려준다
// 프롬프트에 FAIL 이 있으면 생성 실패, FLAKY 면 상태 조회 1번째를 503, NOPROG 면 progress 를 안 준다.
import http from 'node:http';

function cors(res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Private-Network', 'true');
}

function send(res, code, body, type = 'application/json') {
  cors(res);
  const buf = Buffer.isBuffer(body) ? body : Buffer.from(typeof body === 'string' ? body : JSON.stringify(body));
  res.writeHead(code, { 'Content-Type': type, 'Content-Length': buf.length });
  res.end(buf);
}

function readBody(req) {
  return new Promise((res) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => res(Buffer.concat(chunks)));
  });
}

// multipart 에서 필드 이름·파일 이름·텍스트 값만 뽑는다(검사용)
function parseMultipart(ctype, body) {
  const boundary = /boundary=(?:"([^"]+)"|([^;]+))/.exec(ctype);
  const b = '--' + (boundary[1] || boundary[2]);
  const out = [];
  const text = body.toString('latin1');
  for (const part of text.split(b).slice(1, -1)) {
    const [head, ...rest] = part.split('\r\n\r\n');
    const name = /name="([^"]+)"/.exec(head)?.[1];
    const filename = /filename="([^"]*)"/.exec(head)?.[1];
    const val = rest.join('\r\n\r\n').replace(/\r\n$/, '');
    out.push({ name, filename, value: filename ? `${val.length}B` : Buffer.from(val, 'latin1').toString('utf8') });
  }
  return out;
}

function listen(handler) {
  const srv = http.createServer(handler);
  return new Promise((res) => srv.listen(0, '127.0.0.1', () => res({ srv, url: `http://127.0.0.1:${srv.address().port}` })));
}

export async function startH3video(mp4) {
  const jobs = new Map();
  const log = [];
  let n = 0;
  const { srv, url } = await listen(async (req, res) => {
    if (req.method === 'OPTIONS') return send(res, 204, '');
    const u = new URL(req.url, 'http://x');
    const p = u.pathname;
    if (req.method === 'GET' && p === '/api/spec') return send(res, 200, { tasks: { t2va: 'text', fl2va: 'first', ref2va: 'ref' }, short_edge: 768 });
    if (req.method === 'GET' && p === '/api/health') return send(res, 200, { fl2va: true, ref2va: true, queue: 0, current: null });
    if (req.method === 'POST' && p === '/api/jobs') {
      const fields = parseMultipart(req.headers['content-type'], await readBody(req));
      const prompt = fields.find((f) => f.name === 'prompt')?.value || '';
      const id = `job${++n}`;
      jobs.set(id, { id, prompt, polls: 0 });
      log.push({ kind: 'submit', id, fields });
      return send(res, 201, { id, status: 'pending', prompt, scenes: [] });
    }
    let m = /^\/api\/jobs\/([^/]+)$/.exec(p);
    if (req.method === 'GET' && m) {
      const j = jobs.get(m[1]);
      if (!j) return send(res, 404, { error: '없음' });
      j.polls += 1;
      log.push({ kind: 'poll', id: j.id, n: j.polls });
      if (/FLAKY/.test(j.prompt) && j.polls === 1) return send(res, 503, { error: '잠시 끊김' });
      const noprog = /NOPROG/.test(j.prompt);
      const steps = [
        { status: 'queued', scenes: [{ status: 'queued', progress: 0 }] },
        { status: 'in_progress', scenes: [{ status: 'in_progress', progress: noprog ? undefined : 0.4 }] },
        { status: 'in_progress', scenes: [{ status: 'in_progress', progress: noprog ? undefined : 0.8 }] },
      ];
      const k = j.polls - (/FLAKY/.test(j.prompt) ? 2 : 1);
      if (k < steps.length) return send(res, 200, { id: j.id, ...steps[Math.max(0, k)] });
      if (/FAIL/.test(j.prompt)) return send(res, 200, { id: j.id, status: 'failed', error: 'CUDA out of memory (가짜)', scenes: [{ status: 'failed', progress: 0.8 }] });
      return send(res, 200, { id: j.id, status: 'completed', output: `outputs/${j.id}/final.mp4`, scenes: [{ status: 'completed', progress: 1 }] });
    }
    m = /^\/files\/([^/]+)\/final\.mp4$/.exec(p);
    if (req.method === 'GET' && m) {
      log.push({ kind: 'download', id: m[1] });
      return send(res, 200, mp4, 'video/mp4');
    }
    send(res, 404, { error: 'not found' });
  });
  return { url, log, close: () => srv.close() };
}

export async function startSglang(mp4) {
  const vids = new Map();
  const log = [];
  let n = 0;
  const { srv, url } = await listen(async (req, res) => {
    if (req.method === 'OPTIONS') return send(res, 204, '');
    const p = new URL(req.url, 'http://x').pathname;
    if (req.method === 'GET' && p === '/v1/models') return send(res, 200, { data: [{ id: 'MiniMax-H3', owned_by: 'sglang' }] });
    if (req.method === 'POST' && p === '/v1/videos') {
      const body = JSON.parse((await readBody(req)).toString());
      const id = `vid${++n}`;
      vids.set(id, { id, body, polls: 0 });
      log.push({ kind: 'submit', id, body: { ...body, conditions: body.conditions.map((c) => ({ ...c, uri: c.uri.slice(0, 30) })) } });
      return send(res, 200, { id, status: 'queued' });
    }
    let m = /^\/v1\/videos\/([^/]+)$/.exec(p);
    if (m && req.method === 'DELETE') {
      log.push({ kind: 'delete', id: m[1] });
      return send(res, 200, { id: m[1], deleted: true });
    }
    if (m && req.method === 'GET') {
      const v = vids.get(m[1]);
      v.polls += 1;
      const st = v.polls < 2 ? { status: 'queued', progress: 0 } : v.polls < 4 ? { status: 'in_progress', progress: v.polls * 20 } : { status: 'completed', progress: 100 };
      return send(res, 200, { id: v.id, ...st });
    }
    m = /^\/v1\/videos\/([^/]+)\/content$/.exec(p);
    if (m && req.method === 'GET') return send(res, 200, mp4, 'video/mp4');
    send(res, 404, { error: 'not found' });
  });
  return { url, log, close: () => srv.close() };
}

export async function startAnthropic(replies) {
  const log = [];
  let i = 0;
  const { srv, url } = await listen(async (req, res) => {
    if (req.method === 'OPTIONS') return send(res, 204, '');
    if (req.method === 'POST' && new URL(req.url, 'http://x').pathname === '/v1/messages') {
      const body = JSON.parse((await readBody(req)).toString());
      log.push({ headers: req.headers, body });
      const r = replies[Math.min(i, replies.length - 1)];
      i += 1;
      return send(res, 200, r);
    }
    send(res, 404, { error: 'not found' });
  });
  return { url, log, close: () => srv.close() };
}

export function toolReply(input, id = 'toolu_1') {
  return {
    id: 'msg_fake',
    type: 'message',
    role: 'assistant',
    model: 'claude-opus-5-5',
    stop_reason: 'tool_use',
    content: [{ type: 'tool_use', id, name: 'write_job', input }],
    usage: { input_tokens: 10, output_tokens: 10 },
  };
}
