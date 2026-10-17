const fields=['id','label','prompt','text','seconds','trimIn','trimOut','transition','transitionSeconds','motion','corrections','focus','locked'];
export function draftSettings(project){
 return {title:project.title,clips:project.clips.map(clip=>Object.fromEntries(fields.filter(key=>clip[key]!==undefined).map(key=>[key,clip[key]]))),audio:project.audio,delivery:project.delivery,...(project.captionEdited?{captions:project.captions,captionEdited:true}:{})};
}
export function restoreDraft(project,settings){
 const current=new Map(project.clips.map(clip=>[clip.id,clip]));
 return {...project,...settings,clips:settings.clips.map(clip=>({...current.get(clip.id),...clip,variants:current.get(clip.id)?.variants||[]}))};
}
export function importDraft(value,id){
 if(value?.schema!=='h3video-editor-draft/v1'||value.id!==id)throw Error('이 프로젝트에서 받은 수정본 JSON을 선택하세요.');
 const settings=value.settings,ids=new Set();
 if(!settings||!Array.isArray(settings.clips)||!settings.clips.length||!settings.audio||!settings.delivery)throw Error('수정본의 편집 설정을 확인하세요.');
 for(const clip of settings.clips){
  if(!/^[\w-]+$/.test(clip.id||'')||ids.has(clip.id)||!clip.corrections||!clip.focus||!Number.isFinite(clip.seconds)||clip.seconds<=0)throw Error('수정본의 장면 설정이 잘못됐습니다.');
  ids.add(clip.id);
 }
 return {id,at:Date.now(),settings:draftSettings(settings)};
}
