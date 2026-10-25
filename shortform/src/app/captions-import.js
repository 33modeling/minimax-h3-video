// 받아쓰기 결과 → 작업 JSON 의 captions. 받아쓰기 작업실(asr-studio)의 SRT·VTT·JSON 내보내기와
// '숏폼 자막으로 보내기' 넘기기 묶음을 읽는다. 순수 함수 — node 테스트가 직접 부른다.
// 결과: [{ text, start, end }] (초, 소수 셋째 자리, 시작 순)

// 받는 쪽 약속(asr-studio 와 같게): localStorage['shorts-captions-handoff'] = {v:1, from:'asr-studio', at, title, segments:[{start,end,speaker,text}]}
// 숏폼은 '#from=asr' 로 열리면 이 값을 읽고 지운다.
export const CAPTION_HANDOFF_KEY = 'shorts-captions-handoff';
export const CAPTION_HANDOFF_HASH = '#from=asr';

const r3 = (x) => Math.round(x * 1000) / 1000;
const extOf = (name) => (/\.([^./\\]+)$/.exec(String(name || '')) || [, ''])[1].toLowerCase();

export const isCaptionFileName = (name) => ['srt', 'vtt'].includes(extOf(name));
// asr-studio JSON 내보내기({app:'asr-studio', segments}) 와 넘기기 묶음({from:'asr-studio', segments})
export const isTranscriptJson = (v) => !!v && typeof v === 'object' && !Array.isArray(v)
  && (v.app === 'asr-studio' || v.from === 'asr-studio') && Array.isArray(v.segments);
export function looksLikeTranscriptText(text) {
  try {
    return isTranscriptJson(JSON.parse(String(text).replace(/^﻿/, '')));
  } catch {
    return false;
  }
}

// 00:01:02,345 · 01:02.345 · 1:02:03.4 → 초 (못 읽으면 NaN)
export function parseClock(s) {
  const m = /^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?$/.exec(String(s).trim());
  if (!m) return NaN;
  const [, h = '0', mm, ss, frac = '0'] = m;
  if (Number(mm) > 59 || Number(ss) > 59) return NaN;
  return Number(h) * 3600 + Number(mm) * 60 + Number(ss) + Number(frac.padEnd(3, '0')) / 1000;
}

const unescapeHtml = (t) => t.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&');
// VTT: '<' 는 &lt; 로 적히므로 <v 화자>·<c.x>·<00:00:01.000> 같은 꼬리표는 모두 뺀다.
// SRT: 글이 그대로 적히므로(받아쓰기의 '<중요한>' 같은 글) 서식 꼬리표(<i>·<b>·<u>·<s>·<font>)와 {\an8} 만 뺀다.
const stripVttTags = (t) => t.replace(/<[^>]*>/g, '');
const stripSrtTags = (t) => t.replace(/<\/?(?:i|b|u|s|font)(?:\s[^>]*)?>/gi, '').replace(/\{\\[^}]*\}/g, '');
const joinLines = (lines) => lines.map((l) => l.trim()).filter(Boolean).join('\n');

// SRT·VTT 공통: 빈 줄로 나눈 덩어리마다 'A --> B' 줄을 찾고 그 뒤를 글로 본다.
function parseCues(text, { vtt }) {
  const out = [];
  const body = String(text).replace(/^﻿/, '').replace(/\r\n?/g, '\n');
  for (const block of body.split(/\n[ \t]*\n+/)) {
    const lines = block.split('\n');
    if (vtt && /^(NOTE|STYLE|REGION)\b/.test(lines[0].trim())) continue;
    const at = lines.findIndex((l) => l.includes('-->'));
    if (at < 0) continue;
    const [a, b] = lines[at].split('-->');
    const start = parseClock(a);
    const end = parseClock(String(b).trim().split(/\s+/)[0]);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) continue;
    const t = joinLines(lines.slice(at + 1).map((l) => (vtt ? unescapeHtml(stripVttTags(l)) : stripSrtTags(l))));
    if (t) out.push({ text: t, start: r3(start), end: r3(end) });
  }
  return out;
}
export const parseSrt = (text) => parseCues(text, { vtt: false });
export const parseVtt = (text) => parseCues(text, { vtt: true });

// segments: [{start,end,text,speaker}] — 빈 글·시간이 이상한 구간은 뺀다. 화자 이름은 showSpeakers 일 때만 앞에 붙인다.
export function segmentsToCaptions(segments, { showSpeakers = false } = {}) {
  const out = [];
  for (const s of segments || []) {
    const text = joinLines(String(s?.text ?? '').replace(/\r/g, '').split('\n'));
    const start = Number(s?.start);
    const end = Number(s?.end);
    if (!text || !Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) continue;
    const who = showSpeakers && s.speaker ? `${String(s.speaker).trim()}: ` : '';
    out.push({ text: who + text, start: r3(start), end: r3(end) });
  }
  return out;
}

const finish = (captions, name) => {
  if (!captions.length) throw new Error(`${name || '자막'}: 시간이 있는 자막 줄이 없습니다`);
  return captions.sort((a, b) => a.start - b.start);
};

// 파일 하나 → { captions, title, kind }. 알아볼 수 없으면 Error.
export function parseCaptionFile(text, name = '') {
  const ext = extOf(name);
  const raw = String(text).replace(/^﻿/, '');
  if (ext === 'vtt' || (ext !== 'srt' && /^WEBVTT\b/.test(raw))) return { captions: finish(parseVtt(raw), name), title: '', kind: 'VTT' };
  if (ext === 'srt') return { captions: finish(parseSrt(raw), name), title: '', kind: 'SRT' };
  let v = null;
  try {
    v = JSON.parse(raw);
  } catch {
    /* 아래에서 안내 */
  }
  if (!isTranscriptJson(v)) throw new Error(`${name || '파일'}: 받아쓰기 작업실의 SRT·VTT·JSON 이 아닙니다`);
  return fromTranscript(v, name);
}

// 넘기기 묶음·JSON 내보내기 객체 → { captions, title, kind }
export function fromTranscript(v, name = '받아쓰기') {
  if (!isTranscriptJson(v)) throw new Error('받아쓰기 결과 형식이 아닙니다');
  return { captions: finish(segmentsToCaptions(v.segments), name), title: typeof v.title === 'string' ? v.title.trim() : '', kind: 'JSON' };
}

// 화면 안내용: "12줄(0:01~1:23)"
export function captionSummary(captions) {
  const mmss = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
  if (!captions.length) return '0줄';
  return `${captions.length}줄(${mmss(captions[0].start)}~${mmss(Math.max(...captions.map((c) => c.end)))})`;
}
