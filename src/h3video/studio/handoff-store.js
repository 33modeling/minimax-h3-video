// 같은 사이트(허브 77modeling.pages.dev/<앱>/)의 다른 앱으로 그림·영상을 넘기는 칸.
// localStorage(약 5MB)에 담기 어려운 Blob 을 IndexedDB 'creative-handoff' 에 둔다. 출처가 같으면 앱(경로)이 달라도 같은 저장소를 본다.
// 레코드: {key, v:1, from, at(ISO 시각), ...내용}. 받는 쪽은 takeHandoff(key) 로 꺼내면서 지운다.
// 정본은 storybook-maker/web/studio/handoff-store.js. 이 사본(영상 만들기·숏폼이 함께 씀)과 daily-tools/src/shared/handoff-store.js 를 함께 고친다.
const DB='creative-handoff',STORE='items';
export const HANDOFF_TTL=30*60_000;
let opening;
function database(){return opening||=new Promise((resolve,reject)=>{let request;try{request=indexedDB.open(DB,1);}catch(error){reject(error);return;}request.onupgradeneeded=()=>request.result.createObjectStore(STORE,{keyPath:'key'});request.onsuccess=()=>resolve(request.result);request.onerror=()=>{opening=null;reject(request.error||Error('브라우저 저장소를 열지 못했습니다.'));};});}
function run(mode,action){return database().then(db=>new Promise((resolve,reject)=>{const tx=db.transaction(STORE,mode);let out=null;tx.oncomplete=()=>resolve(out);tx.onerror=tx.onabort=()=>reject(tx.error||Error('브라우저 저장소에 쓰지 못했습니다. 저장 공간을 확인해 주세요.'));action(tx.objectStore(STORE),value=>{out=value;});}));}
export function putHandoff(key,record){return run('readwrite',store=>{store.put({...record,key});});}
export function takeHandoff(key){return run('readwrite',(store,done)=>{const get=store.get(key);get.onsuccess=()=>{if(get.result){done(get.result);store.delete(key);}};});}
export function isFresh(record,now=Date.now()){const at=Date.parse(record?.at||'');return Number.isFinite(at)&&now-at>-60_000&&now-at<HANDOFF_TTL;}
// 허브에 받는 앱이 있는지 확인하고 새 탭으로 연다. 누른 순간 빈 탭부터 열어야 팝업 차단에 걸리지 않는다.
// {blocked:true} 팝업이 막힘, {missing:true} 받는 앱이 없음(허브 밖에서 따로 연 화면), {tab, go} 확인됨 — 준비가 끝나면 go() 로 이동.
export async function openTool(href){
 const tab=window.open('','_blank');if(!tab)return {blocked:true};
 try{const response=await fetch(new URL(href,location.href).href.replace(/#.*$/,''),{method:'HEAD',cache:'no-store'});if(!response.ok)throw Error(String(response.status));}
 catch{try{tab.close();}catch{}return {missing:true};}
 return {tab,go:()=>tab.location.replace(new URL(href,location.href).href)};
}
