import {StillFrames} from './media.js';
import {drawFrame,frameCount} from './draw.js';
export function safeInsets(preset){if(preset==='off')return null;if(preset==='action')return {top:10,right:10,bottom:10,left:10};if(preset==='vertical')return {top:12,right:16,bottom:22,left:8};throw Error('안전 여백 설정을 확인하세요.');}
export async function exportStill(job,k){
 const {plan,segs,fileOfSeg}=job||{};if(!plan||!Number.isInteger(k)||k<0||k>=frameCount(plan))throw Error('미리보기 장면과 시각을 먼저 선택하세요.');
 if(!Number.isInteger(plan.width)||!Number.isInteger(plan.height)||plan.width<1||plan.height<1||plan.width*plan.height>16000000)throw Error('프레임 해상도가 너무 큽니다.');
 const frames=new StillFrames(plan,segs,fileOfSeg,1);await frames.load(k);for(const seg of segs.filter(s=>k>=s.k0&&k<s.k1))if(!frames.get(seg))throw Error('원본 프레임을 읽지 못했습니다. 빈 이미지는 저장하지 않았습니다.');
 const canvas=document.createElement('canvas'),scratch=document.createElement('canvas');canvas.width=plan.width;canvas.height=plan.height;try{drawFrame(canvas.getContext('2d'),plan,segs,k,s=>frames.get(s),scratch,1);const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!blob)throw Error('프레임 이미지 생성에 실패했습니다.');return blob;}finally{canvas.width=canvas.height=1;scratch.width=scratch.height=1;frames.cur.clear();frames.sinks.clear();}
}
