// zip 읽기(순수 — 브라우저와 node 테스트가 같이 쓴다). 동화책 만들기의 "파일 받기" zip(book.json + images/*,
// 압축 없이 담김)을 한꺼번에 넣을 때 쓴다. 저장(방식 0)과 deflate(방식 8, DecompressionStream('deflate-raw') 가 있을 때)만 푼다.
const SIG_EOCD = 0x06054b50;
const SIG_CEN = 0x02014b50;
const SIG_LOC = 0x04034b50;

export class ZipError extends Error {}

let TABLE = null;
export function crc32(bytes) {
  if (!TABLE) {
    TABLE = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      TABLE[n] = c >>> 0;
    }
  }
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

// 이름: UTF-8 표시(비트 11)가 있으면 UTF-8, 없으면 UTF-8 로 읽어 보고 안 되면 윈도우 한글(EUC-KR/CP949)
function decodeName(bytes, utf8) {
  if (utf8) return new TextDecoder('utf-8').decode(bytes);
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    try {
      return new TextDecoder('euc-kr').decode(bytes);
    } catch {
      return String.fromCharCode(...bytes);
    }
  }
}

async function inflateRaw(data) {
  if (typeof DecompressionStream !== 'function') throw new ZipError('이 브라우저는 압축된 zip을 풀 수 없어요. zip을 풀어서 파일들을 넣어 주세요');
  let ds;
  try {
    ds = new DecompressionStream('deflate-raw');
  } catch {
    throw new ZipError('이 브라우저는 압축된 zip을 풀 수 없어요. zip을 풀어서 파일들을 넣어 주세요');
  }
  const stream = new Blob([data]).stream().pipeThrough(ds);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

async function readEntry(u8, dv, e) {
  if (e.flags & 1) throw new ZipError(`${e.name}: 암호가 걸린 zip은 열 수 없어요`);
  if (e.off + 30 > u8.length || dv.getUint32(e.off, true) !== SIG_LOC) throw new ZipError(`${e.name}: zip 안의 파일 위치가 깨졌어요`);
  const start = e.off + 30 + dv.getUint16(e.off + 26, true) + dv.getUint16(e.off + 28, true);
  if (start + e.csize > u8.length) throw new ZipError(`${e.name}: zip 끝이 잘렸어요`);
  const raw = u8.subarray(start, start + e.csize);
  let data;
  if (e.method === 0) data = raw.slice();
  else if (e.method === 8) data = await inflateRaw(raw);
  else throw new ZipError(`${e.name}: 이 압축 방식(${e.method})은 못 풀어요. zip을 풀어서 넣어 주세요`);
  if (data.length !== e.size || crc32(data) !== e.crc) throw new ZipError(`${e.name}: zip 안의 파일이 깨졌어요`);
  return data;
}

// 반환: [{ name(전체 경로), size, method, read: async () => Uint8Array }] — 폴더 항목은 뺀다
export function listZip(buf) {
  const u8 = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  let eocd = -1;
  for (let i = u8.length - 22; i >= Math.max(0, u8.length - 22 - 0xffff); i--) {
    if (dv.getUint32(i, true) === SIG_EOCD) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new ZipError('zip 파일이 아니거나 끝이 잘렸어요');
  const count = dv.getUint16(eocd + 10, true);
  const cdSize = dv.getUint32(eocd + 12, true);
  let p = dv.getUint32(eocd + 16, true);
  if (count === 0xffff || p === 0xffffffff || cdSize === 0xffffffff) throw new ZipError('아주 큰 zip(ZIP64)은 아직 못 열어요. zip을 풀어서 파일들을 넣어 주세요');
  if (p + cdSize > eocd) throw new ZipError('zip 목록이 깨졌어요');
  const out = [];
  for (let k = 0; k < count; k++) {
    if (p + 46 > eocd || dv.getUint32(p, true) !== SIG_CEN) throw new ZipError('zip 목록이 깨졌어요');
    const e = {
      flags: dv.getUint16(p + 8, true),
      method: dv.getUint16(p + 10, true),
      crc: dv.getUint32(p + 16, true),
      csize: dv.getUint32(p + 20, true),
      size: dv.getUint32(p + 24, true),
      off: dv.getUint32(p + 42, true),
    };
    const nlen = dv.getUint16(p + 28, true);
    e.name = decodeName(u8.subarray(p + 46, p + 46 + nlen), (e.flags & 0x800) !== 0).replace(/\\/g, '/');
    p += 46 + nlen + dv.getUint16(p + 30, true) + dv.getUint16(p + 32, true);
    if (e.name.endsWith('/')) continue;
    out.push({ name: e.name, size: e.size, method: e.method, read: () => readEntry(u8, dv, e) });
  }
  return out;
}
