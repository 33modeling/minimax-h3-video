export const QWEN_MODEL = 'Qwen/Qwen3.8-27B';
export const QWEN_LABEL = 'Qwen3.8-27B · LLM / 코딩';
export function chatEndpoint(baseUrl) {
  const url = new URL(String(baseUrl || 'http://127.0.0.1:8000/v1').trim());
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw Error('LLM 서버 주소는 http 또는 https 주소로 입력해 주세요.');
  url.pathname = url.pathname.replace(/\/+$/, '').replace(/\/chat\/completions$/, '');
  if (!url.pathname.endsWith('/v1')) url.pathname += '/v1';
  url.pathname += '/chat/completions';url.search='';url.hash='';return url.href;
}
function content(value) {
  if (typeof value === 'string') return value;
  return (value || []).filter(b=>b.type!=='thinking').map(b=>b.type==='image' ? {type:'image_url',image_url:{url:`data:${b.source.media_type};base64,${b.source.data}`}} : {type:'text',text:b.text||''});
}
export function chatBody(body, model = QWEN_MODEL) {
  return {model,stream:false,max_tokens:body.max_tokens||16000,chat_template_kwargs:{enable_thinking:false},
    messages:[...(body.system?[{role:'system',content:body.system}]:[]),...body.messages.map(m=>({role:m.role,content:content(m.content)}))],
    ...(body.output_config?.format?.schema?{response_format:{type:'json_schema',json_schema:{name:'creative_output',strict:true,schema:body.output_config.format.schema}}}:{})};
}
export async function qwenMessage({body,baseUrl,apiKey='',model=QWEN_MODEL,signal,fetchImpl=fetch}) {
  const request=chatBody(body,model);
  const res=await fetchImpl(chatEndpoint(baseUrl),{method:'POST',headers:{'Content-Type':'application/json',...(apiKey?{Authorization:'Bearer '+apiKey}:{})},body:JSON.stringify(request),signal});
  if(!res.ok)throw Error(`Qwen LLM 요청 실패 (${res.status}). 서버 주소·실행 중인 모델 ID·연결 상태를 확인해 주세요.`);
  const data=await res.json(),choice=data?.choices?.[0];
  if(!choice?.message)throw Error('Qwen LLM 응답에 생성 결과가 없습니다.');
  const text=typeof choice.message.content==='string'?choice.message.content:(choice.message.content||[]).map(b=>b.text||'').join('');
  return {text,done:true,phase:'text',model:data.model||model,stop_reason:choice.finish_reason==='length'?'max_tokens':choice.finish_reason==='content_filter'?'refusal':'end_turn'};
}
export async function qwenJson(options) {
  const message=await qwenMessage(options);
  if(message.stop_reason!=='end_turn')throw Error('Qwen 응답이 끝까지 생성되지 않았습니다. 저장된 작업에서 다시 이어 만들어 주세요.');
  const text=message.text.replace(/<think>[\s\S]*?<\/think>/g,'').trim();
  const fence=text.match(/```(?:json)?\s*([\s\S]*?)```/);
  return JSON.parse(fence?fence[1]:text.slice(text.indexOf('{'),text.lastIndexOf('}')+1));
}
