import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const cwd=fileURLToPath(new URL('../tools/hyperframes/',import.meta.url));
const result=spawnSync('npm',['ci','--no-audit','--no-fund'],{cwd,stdio:'inherit'});
if(result.status!==0)process.exit(result.status||1);
const check=spawnSync(`${cwd}/node_modules/node/bin/node`,[`${cwd}/node_modules/hyperframes/bin/hyperframes.mjs`,'--version'],{stdio:'inherit',env:{...process.env,DO_NOT_TRACK:'1'}});
if(check.status!==0)process.exit(check.status||1);
console.log('Hyperframes Studio/renderer ready. FFmpeg, Chromium and Noto Sans CJK KR are required on the web server. No generation model is started.');
