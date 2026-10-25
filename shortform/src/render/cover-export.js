// 표지(썸네일) PNG: 미리보기에서 고른 프레임 위에 제목을 얹는다. 글자색·테두리·위치·크기 배율은 자막 모양 설정을 따른다.
import {StillFrames} from './media.js';
import {drawFrame,frameCount,FONT_STACK} from './draw.js';
import {textStyle,captionStyle,layoutCaption} from '../core/plan.js';
export const COVER_SIZES={shorts:{width:1080,height:1920,label:'숏폼 1080×1920'},youtube:{width:1280,height:720,label:'유튜브 1280×720'}};
export const COVER_SCALE=1.6; // 표지 제목은 자막보다 크게
// W×H 표지에 넣을 제목 줄 배치. 위치가 '템플릿 기본'이면 가운데에 둔다.
export function coverLayout(text,W,H,config={}){
 const c={...config};if(!c.position||c.position==='auto')c.position='center';c.scale=(c.scale??1)*COVER_SCALE;
 const style=captionStyle(textStyle(W,H,'base').caption,W,H,c);const t=String(text||'').trim();
 return {style,lines:t?layoutCaption(t,W,style):[]};
}
// 원본 프레임(srcW×srcH)을 W×H 에 가운데 잘라 채우는 원본 쪽 좌표
export function coverCrop(srcW,srcH,W,H){const s=Math.max(W/srcW,H/srcH),sw=Math.min(srcW,W/s),sh=Math.min(srcH,H/s);return {sx:(srcW-sw)/2,sy:(srcH-sh)/2,sw,sh};}
export function drawCoverTitle(ctx,layout){const st=layout.style;ctx.font=`700 ${st.fontSize}px ${FONT_STACK}`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.lineJoin='round';ctx.miterLimit=2;for(const ln of layout.lines){if(st.border>0){ctx.lineWidth=st.border*2;ctx.strokeStyle=st.borderColor;ctx.strokeText(ln.text,ln.cx,ln.cy);}ctx.fillStyle=st.color;ctx.fillText(ln.text,ln.cx,ln.cy);}}
export async function exportCover(job,k,{title='',size='shorts',config={}}={}){
 const {plan,segs,fileOfSeg}=job||{};const out=COVER_SIZES[size];if(!out)throw Error('표지 크기를 선택하세요.');
 if(!plan||!Number.isInteger(k)||k<0||k>=frameCount(plan))throw Error('미리보기 장면과 시각을 먼저 선택하세요.');
 const s=Math.min(4,Math.max(out.width/plan.width,out.height/plan.height)),fw=Math.round(plan.width*s),fh=Math.round(plan.height*s);if(fw*fh>16000000)throw Error('프레임 해상도가 너무 큽니다.');
 const frames=new StillFrames(plan,segs,fileOfSeg,s);await frames.load(k);for(const seg of segs.filter(x=>k>=x.k0&&k<x.k1))if(!frames.get(seg))throw Error('원본 프레임을 읽지 못했습니다. 빈 이미지는 저장하지 않았습니다.');
 const bare={...plan,title:[],captions:[]},frame=document.createElement('canvas'),scratch=document.createElement('canvas'),canvas=document.createElement('canvas');frame.width=fw;frame.height=fh;canvas.width=out.width;canvas.height=out.height;
 try{drawFrame(frame.getContext('2d'),bare,segs,k,x=>frames.get(x),scratch,s);const ctx=canvas.getContext('2d'),c=coverCrop(fw,fh,out.width,out.height);ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';ctx.drawImage(frame,c.sx,c.sy,c.sw,c.sh,0,0,out.width,out.height);drawCoverTitle(ctx,coverLayout(title,out.width,out.height,config));const blob=await new Promise(r=>canvas.toBlob(r,'image/png'));if(!blob)throw Error('표지 이미지 생성에 실패했습니다.');return blob;}
 finally{frame.width=frame.height=1;scratch.width=scratch.height=1;canvas.width=canvas.height=1;frames.cur.clear();frames.sinks.clear();}
}
