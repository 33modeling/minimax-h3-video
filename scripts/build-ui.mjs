import { mkdir, copyFile, writeFile } from 'node:fs/promises';
const output=new URL('../dist-ui/',import.meta.url);
await mkdir(output,{recursive:true});
await copyFile(new URL('../src/h3video/ui.html',import.meta.url),new URL('index.html',output));
await writeFile(new URL('build.json',output),JSON.stringify({profile:process.env.GAME_PROFILE||'pages',source:'h3video/ui.html'}));
