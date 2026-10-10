import { defineConfig } from 'vite';

// 허브(/shorts/) 아래에 그대로 얹을 수 있게 자산 경로를 상대 경로로 둔다.
// 소스맵은 만들지 않는다(허브에는 빌드 결과만 올라가고, 비공개 소스가 드러나면 안 된다).
export default defineConfig({
  base: './',
  build: {
    target: 'es2022',
    sourcemap: false,
    chunkSizeWarningLimit: 2000,
  },
  server: { port: 4251, strictPort: false },
  preview: { port: 4252 },
});
