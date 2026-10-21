import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {presets,createDraft,draftProject,directPrompt} from '../../../src/h3video/studio/prompt-library.js';
import {storyToSpec} from '../../src/core/story.js';
import {checkSpec} from '../../src/core/spec.js';

test('every production template exports a valid storyboard and native shots without truncating the requested length',()=>{
  for(const preset of presets)for(const duration of [4,5,14,15,16,17,30,60,1000]){
    const draft=createDraft({preset:preset.id,subject:'사용자가 적은 주인공',duration,ratio:'9:16'});
    assert.equal(draft.shots.reduce((sum,shot)=>sum+shot.duration,0),duration);
    assert.ok(draft.shots.every(shot=>shot.duration>=4&&shot.duration<=15&&shot.videoPrompt.includes('사용자가 적은 주인공')));
    const {spec,info}=storyToSpec(draftProject(draft));
    assert.deepEqual(checkSpec(spec).errors,[]);assert.equal(info.total,duration);
    assert.ok(spec.scenes.every(shot=>shot.prompt.includes('Avoid:')));
  }
  for(const duration of [0,3,4.5,NaN,Infinity])assert.throws(()=>createDraft({duration}));
});
test('changing the direction preserves the subject and replaces old camera and lighting instructions',()=>{
  const first=directPrompt('A person opens a window.',{camera:'push',light:'window'});
  const changed=directPrompt(first,{camera:'static',light:'night'});
  assert.ok(changed.startsWith('A person opens a window.'));
  assert.equal(changed.match(/Camera direction:/g).length,1);
  assert.equal(changed.match(/Lighting direction:/g).length,1);
  assert.ok(changed.includes('locked-off'));assert.ok(!changed.includes('push-in'));
});
test('FRAME handoff keeps edited captions, duration and negative instructions in both browser and Python imports',()=>{
  const project=draftProject(createDraft({duration:30,subject:'한글 주인공'}));
  project.board.scenes[0].caption='직접 고친 첫 자막';project.board.scenes[0].negativePrompt='No red clothing.';
  const {spec}=storyToSpec(project);
  assert.equal(spec.captions[0].text,'직접 고친 첫 자막');
  const py=JSON.parse(execFileSync('python3',['-c','import sys,json;sys.path[:0]=["src","shortform"];from shorts.story import story_to_spec;d=json.load(sys.stdin);print(json.dumps(story_to_spec(d)[0],ensure_ascii=False))'],{cwd:new URL('../../../',import.meta.url),input:JSON.stringify(project),encoding:'utf8'}));
  assert.deepEqual(spec,py);
});
