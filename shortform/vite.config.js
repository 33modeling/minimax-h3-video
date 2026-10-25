import { defineConfig } from 'vite';
import { existsSync, readFileSync } from 'node:fs';
import { join, resolve, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

// 허브(33modeling-site)가 모든 앱에 같이 내주는 파일: 사이트 Claude 연결(/creative-ai/client.mjs)과 글꼴(/fonts/…).
// 허브에 올리면 그 자리에 있지만, 이 폴더만 띄우는 vite dev·preview 에는 없어서 404 가 콘솔 오류로 쌓였다.
// 로컬 서버에서도 허브와 같은 주소로 내준다: 연결은 "사이트 연결 없음" 대역(네트워크 요청 없음),
// 글꼴은 옆 허브 체크아웃(SHORTS_HUB_DIR, 기본 ../../33modeling-site)에 있으면 그 파일, 없으면 빈 응답 204(대체 글꼴로 표시).
const HERE = fileURLToPath(new URL('.', import.meta.url));
const HUB = resolve(process.env.SHORTS_HUB_DIR || join(HERE, '../../33modeling-site'));
export const HUB_CLIENT_STUB = 'export async function getConnection(){return {configured:false,standalone:true};}\n';
function hubShared() {
  const serve = (req, res, next) => {
    const path = decodeURIComponent((req.url || '').split('?')[0]);
    if (path === '/creative-ai/client.mjs') {
      res.setHeader('Content-Type', 'text/javascript; charset=utf-8');
      res.end(HUB_CLIENT_STUB);
      return;
    }
    if (path.startsWith('/fonts/')) {
      const file = normalize(join(HUB, path));
      if (file.startsWith(join(HUB, 'fonts')) && existsSync(file)) {
        res.setHeader('Content-Type', file.endsWith('.woff2') ? 'font/woff2' : 'application/octet-stream');
        res.end(readFileSync(file));
      } else {
        res.statusCode = 204;
        res.end();
      }
      return;
    }
    next();
  };
  return {
    name: 'hub-shared-files',
    // 함수를 돌려주면 vite 가 '나중 훅'으로 부르므로 아무것도 돌려주지 않는다
    configureServer(server) {
      server.middlewares.use(serve);
    },
    configurePreviewServer(server) {
      server.middlewares.use(serve);
    },
  };
}

// 허브(/shorts/) 아래에 그대로 얹을 수 있게 자산 경로를 상대 경로로 둔다.
// 소스맵은 만들지 않는다(허브에는 빌드 결과만 올라가고, 비공개 소스가 드러나면 안 된다).
export default defineConfig({
  base: './',
  plugins: [hubShared()],
  build: {
    target: 'es2022',
    sourcemap: false,
    chunkSizeWarningLimit: 2000,
  },
  server: { port: 4251, strictPort: false },
  preview: { port: 4252 },
});
