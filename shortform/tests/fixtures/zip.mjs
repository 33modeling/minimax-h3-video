// 테스트용 zip 만들기 (단위 테스트·e2e 공용). 동화책 만들기 src/zip.mjs 와 같은 모양: 로컬 헤더 + 중앙 목록 + 끝 레코드.
// method 0 = 저장(동화책 만들기 '파일 받기'), 8 = deflate.
import zlib from 'node:zlib';
import { crc32 } from '../../src/app/zip.js';

export function makeZip(entries, { method = 0, utf8 = true } = {}) {
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const { name, data: raw, nameBytes } of entries) {
    const data = Buffer.from(raw);
    const body = method === 8 ? zlib.deflateRawSync(data) : data;
    const fname = nameBytes || Buffer.from(name, 'utf8');
    const flags = utf8 ? 0x0800 : 0;
    const crc = crc32(data);
    const head = Buffer.alloc(30);
    head.writeUInt32LE(0x04034b50, 0); head.writeUInt16LE(20, 4); head.writeUInt16LE(flags, 6); head.writeUInt16LE(method, 8);
    head.writeUInt32LE(crc, 14); head.writeUInt32LE(body.length, 18); head.writeUInt32LE(data.length, 22); head.writeUInt16LE(fname.length, 26);
    const cen = Buffer.alloc(46);
    cen.writeUInt32LE(0x02014b50, 0); cen.writeUInt16LE(20, 4); cen.writeUInt16LE(20, 6); cen.writeUInt16LE(flags, 8); cen.writeUInt16LE(method, 10);
    cen.writeUInt32LE(crc, 16); cen.writeUInt32LE(body.length, 20); cen.writeUInt32LE(data.length, 24); cen.writeUInt16LE(fname.length, 28); cen.writeUInt32LE(offset, 42);
    locals.push(head, fname, body);
    centrals.push(cen, fname);
    offset += 30 + fname.length + body.length;
  }
  const cdir = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(cdir.length, 12); end.writeUInt32LE(offset, 16);
  return new Uint8Array(Buffer.concat([...locals, cdir, end]));
}

