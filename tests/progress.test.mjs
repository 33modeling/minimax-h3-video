import test from 'node:test';import assert from 'node:assert/strict';import {videoProgress,clipProgress} from '../src/h3video/studio/progress.js';
test('resumed video generation shows its actual scene rather than a stale completed edit task',()=>{
 const p={title:'My movie',busy:true,task:{status:'done',progress:1,message:'old done'},clips:[{label:'First',pendingCandidates:[{status:'completed',progress:1}]},{label:'Second',pendingCandidates:[{status:'running',progress:.4,stage:'디코딩'}]}]};
 const view=videoProgress(p);assert.match(view.message,/Second/);assert.match(view.message,/1\/2/);assert.match(view.message,/40%/);assert.doesNotMatch(view.message,/old done/);assert.equal(view.fraction,.7);assert.equal(clipProgress(p.clips[1]).active,true);
 p.clips[1].pendingCandidates[0].progress=null;assert.equal(videoProgress(p).fraction,null);assert.doesNotMatch(videoProgress(p).message,/0%/);
 assert.match(videoProgress(p,{requesting:true,action:'resume'}).message,/이어 만들기 요청 중/);
});
test('paused, failed and queued scenes remain distinguishable and edits name their operation',()=>{
 const p={title:'My movie',busy:false,clips:[{label:'First',pendingCandidates:[{status:'failed',error:'fixture failure'}]}]};assert.equal(videoProgress(p).status,'error');assert.match(videoProgress(p).message,/fixture failure/);assert.match(clipProgress(p.clips[0]).message,/실패/);
 p.clips[0].pendingCandidates[0].status='paused';assert.equal(videoProgress(p).status,'paused');p.busy=true;p.clips=[];p.task={status:'queued',operation:'upscale',progress:.25};assert.match(videoProgress(p).message,/업스케일.*대기/);
});
