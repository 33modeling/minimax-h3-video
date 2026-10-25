// 영상 만들기(video-maker)의 '숏폼으로 보내기'로 받은 영상 확인(보내는 쪽: src/h3video/ui.html sendToShorts).
// 같은 출처 IndexedDB('creative-handoff')의 key 'shorts-video-input' = {v:1, from:'video-maker', at, title, ratio, seconds, file:File}, 주소 #from=video
import {isFresh} from '../../../src/h3video/studio/handoff-store.js';
export const VIDEO_HANDOFF_KEY='shorts-video-input',VIDEO_HANDOFF_HASH='#from=video';
const VIDEO_NAME=/\.(mp4|mov|webm|m4v|mkv)$/i;
// 맞으면 {file, title}, 아니면 한국어 오류를 던진다
export function checkVideoHandoff(record,now=Date.now()){
 if(!record)throw new Error('영상 만들기에서 넘긴 영상을 찾지 못했어요. 영상 만들기의 ‘받기’로 내려받은 파일을 여기에 놓아 주세요.');
 if(record.v!==1||record.from!=='video-maker')throw new Error('받은 자료의 형식을 알 수 없어 넣지 않았어요(옛 화면에서 보냈을 수 있어요). 영상 만들기를 새로 고친 뒤 다시 보내 주세요.');
 if(!isFresh(record,now))throw new Error('30분이 넘게 지난 영상이라 넣지 않았어요. 영상 만들기에서 다시 보내 주세요.');
 const blob=record.file;
 if(!(blob instanceof Blob)||!blob.size)throw new Error('받은 영상 파일이 비어 있어 넣지 않았어요. 영상 만들기에서 다시 보내 주세요.');
 const name=typeof blob.name==='string'&&blob.name?blob.name:'영상.mp4';
 if(!String(blob.type||'').startsWith('video/')&&!VIDEO_NAME.test(name))throw new Error('받은 파일이 영상이 아니라 넣지 않았어요.');
 const file=blob instanceof File?blob:new File([blob],name,{type:blob.type||'video/mp4'});
 return {file,title:typeof record.title==='string'?record.title.trim():''};
}
