import test from 'node:test';import assert from 'node:assert/strict';import {videoProgress,clipProgress,nativeProgress} from '../src/h3video/studio/progress.js';
const frameTask=(phase='upscale',completed=2)=>({title:'프레임 보정',busy:true,task:{status:'running',operation:'upscale',progress:.99,metrics:{phase,label:phase,frames:{completed,total:4,current:completed+1,cached:1},fraction:phase==='upscale'?.5:null,elapsedSeconds:40,phaseElapsedSeconds:10,ratePerSecond:.05,etaSeconds:40}},clips:[]});
test('actual completed frames and estimate are distinct from overall completion',()=>{
 const p=frameTask();const v=videoProgress(p);assert.match(v.message,/완료 프레임 2\/4/);assert.match(v.message,/현재 3번/);assert.match(v.message,/저장본 1개 재사용/);assert.match(v.message,/20.0초\/프레임/);assert.match(v.message,/남은 프레임 약 40초/);assert.equal(v.fraction,.5);
 for(const phase of ['assemble','inspect']){p.task.metrics.phase=phase;p.task.metrics.fraction=null;assert.equal(videoProgress(p).fraction,null);assert.equal(videoProgress(p).status,'running');}
 p.busy=false;p.task.status='done';assert.equal(videoProgress(p).fraction,1);
});
test('unknown extraction, idle and stale connection never invent a percent',()=>{
 const p=frameTask('extract');p.task.metrics={phase:'extract',label:'프레임 추출'};assert.equal(videoProgress(p).fraction,null);
 assert.equal(videoProgress({title:'새 프로젝트',clips:[]}).status,'idle');
 const v=videoProgress(frameTask(),{connectionError:true});assert.equal(v.status,'disconnected');assert.equal(v.fraction,null);assert.match(v.message,/마지막 확인/);assert.match(v.message,/완료 프레임 2\/4/);
});
test('pause and error preserve counts and suppress rate/ETA',()=>{
 const p=frameTask();p.busy=false;p.task.status='paused';let v=videoProgress(p);assert.equal(v.status,'paused');assert.match(v.message,/2\/4/);assert.doesNotMatch(v.message,/초\/프레임|남은 프레임 약/);
 p.task.status='error';p.task.error='fixture';v=videoProgress(p);assert.equal(v.status,'error');assert.match(v.message,/fixture/);
});
test('native segment step counters, no arithmetic average over unequal work',()=>{
 const item={kind:'job',status:'running',scenes:[{status:'completed',progress:1},{index:1,status:'in_progress',stage:'디노이징',progress:.9,metrics:{unit:'steps',completed:13,total:49,outputFrames:192,fraction:13/49,retry:1}}]};
 let v=nativeProgress(item);assert.match(v.message,/출력 구간 2\/2/);assert.match(v.message,/계산 13\/49/);assert.match(v.message,/출력 192프레임/);assert.match(v.message,/재시도 1\/2/);assert.equal(v.fraction,13/49);
 item.scenes[1].stage='영상 저장';item.scenes[1].metrics.fraction=null;assert.equal(nativeProgress(item).fraction,null);
 delete item.scenes[1].metrics;assert.equal(nativeProgress(item).fraction,null);assert.match(nativeProgress(item).message,/상세 진척 확인 중/);
 assert.match(nativeProgress(item,{connectionError:true}).message,/마지막 확인/);
});
test('resumed generation takes precedence over stale completed edit task',()=>{
 const p={title:'Movie',busy:true,task:{status:'done',progress:1,message:'old done'},clips:[{label:'First',pendingCandidates:[{status:'completed',progress:1}]},{label:'Second',pendingCandidates:[{status:'running',progress:.4,stage:'디코딩',segments:{current:2,total:2},metrics:{unit:'steps',completed:49,total:49,fraction:null}}]}]};
 const v=videoProgress(p);assert.match(v.message,/Second/);assert.match(v.message,/출력 구간 2\/2/);assert.match(v.message,/계산 49\/49/);assert.doesNotMatch(v.message,/old done|40%/);assert.equal(v.fraction,null);assert.equal(clipProgress(p.clips[1]).active,true);
 assert.match(videoProgress(p,{requesting:true,action:'resume'}).message,/이어 처리 요청 중/);
});
test('failed and queued results retain distinct state',()=>{
 const p={title:'Movie',busy:false,clips:[{pendingCandidates:[{status:'failed',error:'fixture failure'}]}]};assert.equal(videoProgress(p).status,'error');assert.match(videoProgress(p).message,/fixture failure/);
 p.clips[0].pendingCandidates[0].status='paused';assert.equal(videoProgress(p).status,'paused');p.busy=true;p.clips=[];p.task={status:'queued',operation:'upscale',progress:.25};assert.match(videoProgress(p).message,/업스케일.*대기/);assert.equal(videoProgress(p).fraction,null);
});
