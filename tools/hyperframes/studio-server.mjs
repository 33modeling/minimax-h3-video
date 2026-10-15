// Thin host adapter for the pinned, unmodified Apache-2.0 HyperFrames Studio.
import {readdir} from 'node:fs/promises';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {join,dirname} from 'node:path';
import {serve} from '@hono/node-server';
const home=dirname(fileURLToPath(import.meta.url));
const dist=join(home,'node_modules/hyperframes/dist');
const modules=(await readdir(dist)).filter(name=>/^studioServer-[\w-]+\.js$/.test(name));
if(modules.length!==1)throw new Error('Pinned HyperFrames Studio entry is missing; run npm run install:hyperframes.');
const {createStudioServer}=await import(pathToFileURL(join(dist,modules[0])).href);
const studio=createStudioServer({projectDir:process.argv[2],projectName:'h3-motion',browserGpuMode:'software',historyRoot:process.argv[3]});
const server=serve({fetch:studio.app.fetch,hostname:'127.0.0.1',port:0},info=>console.log(JSON.stringify({port:info.port,version:'0.8.158'})));
let closing=false;
async function close(){if(closing)return;closing=true;await studio.shutdown();await studio.watcher.close();server.close(()=>process.exit(0));}
for(const signal of ['SIGINT','SIGTERM','SIGHUP'])process.once(signal,close);
process.on('uncaughtException',error=>{console.error(error);close().finally(()=>process.exit(1));});
