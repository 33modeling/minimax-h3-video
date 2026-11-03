// Persistent per-endpoint video-frame editor. Uses the existing shared provider;
// no new model, server process, quality preset, or GPU allocation is started here.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import readline from 'node:readline';
import {createRequire} from 'node:module';
import {pathToFileURL,fileURLToPath} from 'node:url';
const shared=path.resolve(process.env.STORYBOOK_MAKER_ROOT||path.join(path.dirname(fileURLToPath(import.meta.url)),'../../storybook-maker'));
const require=createRequire(path.join(shared,'package.json')),sharp=require('sharp');
const {createQwenProvider}=await import(pathToFileURL(path.join(shared,'src/providers/qwen-image.mjs')));
const {memoryDimensions}=await import(pathToFileURL(path.join(shared,'src/image-memory.mjs')));
const {redactLog}=await import(pathToFileURL(path.join(shared,'src/server-logs.mjs')));
const provider=process.env.H3_FRAME_PROVIDER||'qwen-image';
if(!['qwen-image','qwen-image-turbo','qwen-image-quantized'].includes(provider))throw Error('지원하지 않는 프레임 provider');
const turbo=provider==='qwen-image-turbo',quantized=provider==='qwen-image-quantized';
const prefix=quantized?'QWEN_IMAGE_QUANTIZED':turbo?'QWEN_IMAGE_TURBO':'QWEN_IMAGE';
if(process.env.H3_FRAME_ENDPOINT)process.env[prefix+'_BASE_URL']=process.env.H3_FRAME_ENDPOINT;
const endpoint=process.env[prefix+'_BASE_URL']||'default',key=provider+':'+endpoint;
const model=createQwenProvider({id:provider,prefix,model:quantized?'abenzerps/Qwen-Image-2.1-Uncensored-Quantized':turbo?'Qwen/Qwen-Image-2.1-Turbo':'Qwen/Qwen-Image-2.1',port:quantized?8094:turbo?8093:8091,turbo,defaultCfg:turbo?1:4});
for await(const line of readline.createInterface({input:process.stdin,crlfDelay:Infinity})){
 if(!line.trim())continue;
 try{
  const options=JSON.parse(line);
  if(path.resolve(options.input)===path.resolve(options.output))throw Error('원본과 출력 파일을 분리하세요.');
  const original=await fs.readFile(options.input),metadata=await sharp(original).metadata();
  const memoryFile=path.join(path.dirname(options.output),'.qwen-memory-'+crypto.createHash('sha256').update(key).digest('hex').slice(0,12)+'.json');
  let safe;try{const saved=JSON.parse(await fs.readFile(memoryFile,'utf8'));if(saved.key===key&&Date.now()-saved.at<10*60*1000&&saved.edge>=256&&saved.edge<=4096&&saved.referenceMaxEdge>=128&&saved.referenceMaxEdge<=1024)safe=saved;}catch{}
  const dimensions=safe?memoryDimensions(metadata.width,metadata.height,safe.edge):{width:metadata.width,height:metadata.height};
  const result=await model.edit({prompt:options.prompt,...dimensions,seed:options.seed??0,memorySaving:Boolean(safe),referenceMaxEdge:safe?.referenceMaxEdge,references:[{data:original,name:'frame.png',type:'image/png'}]});
  if(result.memoryRecovery||safe){const limit={key,at:Date.now(),edge:Math.max(result.width,result.height),referenceMaxEdge:result.memoryRecovery?.referenceMaxEdge||safe.referenceMaxEdge};await fs.writeFile(memoryFile+'.tmp',JSON.stringify(limit),{mode:0o600});await fs.rename(memoryFile+'.tmp',memoryFile);}
  const output=path.resolve(options.output),temporary=output+'.working.png';
  try{await sharp(result.data).resize(metadata.width,metadata.height,{fit:'fill'}).removeAlpha().png().toFile(temporary);await fs.rename(temporary,output);}catch(error){await fs.rm(temporary,{force:true});throw error;}
  process.stdout.write(JSON.stringify({ok:true,result:{provider,width:metadata.width,height:metadata.height,generatedWidth:result.width,generatedHeight:result.height,memoryRecovery:result.memoryRecovery||null}})+'\n');
 }catch(error){process.stdout.write(JSON.stringify({ok:false,error:redactLog(error.message)})+'\n');}
}
