// 생성 방식(studio/ai-keys.js): 고르기·키 저장·요청 만들기·응답 읽기·오류 문장. fetch 는 가짜로 바꿔 끼운다(네트워크 없음).
import test from 'node:test';import assert from 'node:assert/strict';
import {resolveProviders,keyStore,buildTextRequest,generateText,parseText,describeError,redact,writeUserText,reviseUserText,referenceLabels,
 ENDPOINTS,DEFAULT_MODELS,STORE_KEYS,AiError,WRITE_SYSTEM} from '../src/h3video/studio/ai-keys.js';

const memory=()=>{const m=new Map();return {getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>m.set(k,String(v)),removeItem:k=>m.delete(k),map:m};};
const broken={getItem(){throw Error('blocked');},setItem(){throw Error('blocked');},removeItem(){throw Error('blocked');}};
const KEY_O='sk-test-openai-1234567890',KEY_C='sk-ant-test-claude-1234567890';

test('no key or local method keeps the local server for text and video',()=>{
 assert.deepEqual(resolveProviders(),{method:'local',text:'local',video:'local',missingKey:false});
 assert.deepEqual(resolveProviders({method:'local',openaiKey:KEY_O,claudeKey:KEY_C}),{method:'local',text:'local',video:'local',missingKey:false});
 assert.deepEqual(resolveProviders({method:'openai',openaiKey:'  '}),{method:'openai',text:'local',video:'local',missingKey:true});
 assert.deepEqual(resolveProviders({method:'claude',openaiKey:KEY_O}),{method:'claude',text:'local',video:'local',missingKey:true});
 assert.equal(resolveProviders({method:'bogus',claudeKey:KEY_C}).text,'local');
});
test('a key picks that provider for text while video stays on the local server',()=>{
 assert.deepEqual(resolveProviders({method:'openai',openaiKey:KEY_O}),{method:'openai',text:'openai',video:'local',missingKey:false});
 assert.deepEqual(resolveProviders({method:'claude',claudeKey:KEY_C,openaiKey:KEY_O}),{method:'claude',text:'claude',video:'local',missingKey:false});
});
test('keys live in sessionStorage by default and move to localStorage only when remembered',()=>{
 const session=memory(),local=memory(),store=keyStore({session,local});
 assert.equal(store.method(),'local');assert.equal(store.key('openai'),'');
 store.setKey('openai',' '+KEY_O+' ');assert.equal(session.getItem(STORE_KEYS.openai),KEY_O);assert.equal(local.getItem(STORE_KEYS.openai),null);assert.equal(store.key('openai'),KEY_O);
 store.setKey('claude',KEY_C);store.setRemember(true);
 assert.equal(local.getItem(STORE_KEYS.openai),KEY_O);assert.equal(local.getItem(STORE_KEYS.claude),KEY_C);assert.equal(session.getItem(STORE_KEYS.openai),null);assert.equal(store.remember(),true);
 store.setRemember(false);assert.equal(local.getItem(STORE_KEYS.openai),null);assert.equal(session.getItem(STORE_KEYS.claude),KEY_C);
 store.setRemember(true);store.clear();
 for(const s of [session,local])for(const k of [STORE_KEYS.openai,STORE_KEYS.claude])assert.equal(s.getItem(k),null);
 store.setMethod('claude');assert.equal(store.method(),'claude');store.setMethod('local');assert.equal(local.getItem(STORE_KEYS.method),null);
 assert.equal(store.model('claude'),DEFAULT_MODELS.claude);store.setModel('claude','claude-sonnet-5-5');assert.equal(store.model('claude'),'claude-sonnet-5-5');
 store.setModel('openai','not-a-model');assert.equal(store.model('openai'),DEFAULT_MODELS.openai);
});
test('blocked browser storage never throws',()=>{
 const store=keyStore({session:broken,local:broken});
 assert.equal(store.key('openai'),'');assert.equal(store.setKey('openai',KEY_O),false);assert.equal(store.method(),'local');
 store.setRemember(true);store.clear();store.setMethod('openai');store.setModel('openai','gpt-6-astra');assert.equal(store.remember(),false);
 const none=keyStore({session:null,local:null});assert.equal(none.key('claude'),'');
});
test('OpenAI request goes straight to api.openai.com with the key only in the Authorization header',()=>{
 const {url,init}=buildTextRequest('openai',{key:KEY_O,model:'gpt-6-astra',system:'S',text:'T',images:[{type:'image/jpeg',data:'AAAA'}]});
 assert.equal(url,ENDPOINTS.openai);assert.equal(url,'https://api.openai.com/v1/responses');assert.ok(!url.includes(KEY_O));
 assert.equal(init.method,'POST');assert.equal(init.headers.Authorization,'Bearer '+KEY_O);
 const body=JSON.parse(init.body);assert.ok(!init.body.includes(KEY_O));
 assert.equal(body.model,'gpt-6-astra');assert.equal(body.instructions,'S');assert.equal(body.store,false);assert.deepEqual(body.reasoning,{effort:'low'});
 assert.deepEqual(body.input,[{role:'user',content:[{type:'input_image',image_url:'data:image/jpeg;base64,AAAA'},{type:'input_text',text:'T'}]}]);
 assert.equal(JSON.parse(buildTextRequest('openai',{key:KEY_O,model:'nope',system:'S',text:'T'}).init.body).model,DEFAULT_MODELS.openai);
});
test('Claude request uses the Messages API browser header and the pinned model',()=>{
 const {url,init}=buildTextRequest('claude',{key:KEY_C,system:'S',text:'T',images:[{type:'image/jpeg',data:'BBBB'}]});
 assert.equal(url,'https://api.anthropic.com/v1/messages');assert.ok(!url.includes(KEY_C));
 assert.equal(init.headers['x-api-key'],KEY_C);assert.equal(init.headers['anthropic-version'],'2023-06-01');assert.equal(init.headers['anthropic-dangerous-direct-browser-access'],'true');
 const body=JSON.parse(init.body);assert.ok(!init.body.includes(KEY_C));
 assert.equal(body.model,'claude-opus-5-5');assert.equal(body.system,'S');assert.ok(body.max_tokens>=4000);
 assert.deepEqual(body.messages,[{role:'user',content:[{type:'image',source:{type:'base64',media_type:'image/jpeg',data:'BBBB'}},{type:'text',text:'T'}]}]);
 assert.throws(()=>buildTextRequest('claude',{key:'',text:'T'}),/Claude API 키를 넣어/);assert.throws(()=>buildTextRequest('local',{key:KEY_C}),AiError);
});
test('responses become plain prompt text; refusals, filters and truncation are errors',()=>{
 assert.equal(parseText('openai',{status:'completed',output:[{type:'reasoning',summary:[]},{type:'message',content:[{type:'output_text',text:'```\nA wide shot.\n```'}]}]}),'A wide shot.');
 assert.throws(()=>parseText('openai',{status:'completed',output:[{type:'message',content:[{type:'refusal',refusal:'no'}]}]}),/거절/);
 assert.throws(()=>parseText('openai',{status:'incomplete',incomplete_details:{reason:'content_filter'},output:[]}),/안전 기준/);
 assert.throws(()=>parseText('openai',{status:'incomplete',incomplete_details:{reason:'max_output_tokens'},output:[{type:'message',content:[{type:'output_text',text:'cut'}]}]}),/잘렸/);
 assert.throws(()=>parseText('openai',{status:'completed',output:[]}),/빈 글/);
 assert.equal(parseText('claude',{stop_reason:'end_turn',content:[{type:'thinking',thinking:'x'},{type:'text',text:'Close-up of a cat.'}]}),'Close-up of a cat.');
 assert.throws(()=>parseText('claude',{stop_reason:'refusal',content:[]}),/Claude가 이 요청을 거절/);
 assert.throws(()=>parseText('claude',{stop_reason:'max_tokens',content:[{type:'text',text:'cut'}]}),/잘렸/);
});
test('HTTP errors read as plain Korean and never echo a key',()=>{
 const leak=JSON.stringify({error:{message:'Incorrect API key provided: sk-proj-abcd****wxyz.',type:'invalid_request_error',code:'invalid_api_key'}});
 const bad=describeError('openai',401,leak);assert.match(bad,/OpenAI API 키가 맞지 않아요\(401\)/);assert.ok(!bad.includes('sk-'));
 assert.match(describeError('openai',429,JSON.stringify({error:{message:'You exceeded your current quota',code:'insufficient_quota'}})),/크레딧이나 사용 한도/);
 assert.match(describeError('claude',429,'{}'),/요청 한도에 걸렸어요\(429\)/);
 assert.match(describeError('claude',529,JSON.stringify({type:'error',error:{type:'overloaded_error',message:'Overloaded'}})),/붐벼요/);
 assert.match(describeError('claude',500,''),/잠깐 문제/);
 const other=describeError('openai',400,JSON.stringify({error:{message:'bad key sk-live-123456789 in body'}}));assert.ok(!other.includes('123456789'));
 assert.equal(redact('x sk-ant-api03-AbC_d-123 y'),'x sk-… y');
});
test('generateText calls only the provider URL and reports failures in Korean',async()=>{
 const calls=[];const ok=async(url,init)=>{calls.push({url,init});return new Response(JSON.stringify({stop_reason:'end_turn',content:[{type:'text',text:'A slow push-in.'}]}),{status:200});};
 assert.equal(await generateText('claude',{key:KEY_C,system:WRITE_SYSTEM,text:'고양이',fetchImpl:ok}),'A slow push-in.');
 assert.equal(calls.length,1);assert.equal(calls[0].url,ENDPOINTS.claude);assert.ok(calls[0].init.signal);
 await assert.rejects(generateText('openai',{key:KEY_O,text:'x',fetchImpl:async()=>new Response('{"error":{"message":"bad"}}',{status:401})}),/OpenAI API 키가 맞지 않아요/);
 await assert.rejects(generateText('openai',{key:KEY_O,text:'x',fetchImpl:async()=>{throw new TypeError('Failed to fetch');}}),/연결하지 못했어요/);
 await assert.rejects(generateText('openai',{key:KEY_O,text:'x',fetchImpl:async()=>{const e=new Error('t');e.name='TimeoutError';throw e;}}),/너무 늦어/);
 await assert.rejects(generateText('claude',{key:KEY_C,text:'x',fetchImpl:async()=>new Response('not json',{status:200})}),/읽지 못했어요/);
});
test('writing text keeps duration, frames and reference labels the server expects',()=>{
 const fl=writeUserText({prompt:'아이가 웃는다',seconds:'8',aspect:'16:9',mode:'fl',hasFirst:true,hasLast:true});
 assert.match(fl,/Duration: 8 seconds\./);assert.match(fl,/<Picture 1> \(shown first\) is the first frame and <Picture 2>/);assert.match(fl,/아이가 웃는다$/);
 assert.match(writeUserText({prompt:'p',seconds:6,aspect:'9:16',mode:'fl',hasLast:true}),/<Picture 1> \(shown\) is the last frame/);
 const refs=referenceLabels([{kind:'image'},{kind:'video'},{kind:'image',shown:true},{kind:'audio'},{kind:'other'}]);
 assert.deepEqual(refs.map(r=>r.label),['Picture 1','Video 1','Picture 2','Audio 1']);
 const ref=writeUserText({prompt:'1번 사진 사람이 걷는다',seconds:5,aspect:'1:1',mode:'ref',refs:[{kind:'image',shown:true},{kind:'video'}]});
 assert.match(ref,/<Picture 1> = reference picture \(shown\); <Video 1> = reference video\./);
 assert.doesNotMatch(writeUserText({prompt:'p',seconds:5,aspect:'1:1',mode:'text'}),/Picture/);
 assert.match(reviseUserText({prompt:' P ',instructions:' 더 밝게 '}),/^Prompt:\nP\n\nEdit instruction \(it may be in Korean\):\n더 밝게$/);
});
