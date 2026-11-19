import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../static/app.mjs',import.meta.url),'utf8')
  .replace(/^import[^\n]+\n/gm,'').replace(/init\(\)\.catch[^\n]*;\s*$/,'');
const nodes=new Map();
const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'1',options:[{value:'0',text:''},{value:'1',text:''}],title:''});return nodes.get(id);};
let reply,fail=false;
const ctx=vm.createContext({URL,URLSearchParams,structuredClone,
  location:{origin:'http://localhost',search:'?episode=1'},document:{getElementById:node},
  fetch:async()=>{if(fail)throw Error('offline');return {ok:true,json:async()=>reply};}});
vm.runInContext(source,ctx);
vm.runInContext("info={fps:30,episode_index:1,episodes:[{episode_index:0,frame_count:60},{episode_index:1,frame_count:90}]};kind='subtask';segments=[{caption:'Unsaved manual draft'}];",ctx);
reply={annotation_type:'subtask',episodes:[{episode_index:0,human_count:2,needs_review:true},{episode_index:1,human_count:0,needs_review:false}]};
await vm.runInContext('refreshEpisodeStatuses()',ctx);
assert.match(node('dataset').options[0].text,/异常.*已人工标注 2 份/);
assert.match(node('dataset').options[1].text,/未人工标注/);
assert.equal(node('dataset').value,'1','Status updates must not switch the episode');
assert.equal(vm.runInContext('segments[0].caption',ctx),'Unsaved manual draft');
let optionWrites=0;
for(const option of node('dataset').options){
  let text=option.text;
  Object.defineProperty(option,'text',{get(){return text;},set(value){text=value;optionWrites++;}});
}
await vm.runInContext('refreshEpisodeStatuses()',ctx);
assert.equal(optionWrites,0,'Polling identical statuses must not mutate native select options');
ctx.document.activeElement=node('dataset');
reply.episodes[0].human_count=3;
await vm.runInContext('refreshEpisodeStatuses()',ctx);
assert.equal(optionWrites,0,'Focused/open select must not be mutated during scrolling');
assert.match(node('dataset').options[0].text,/已人工标注 2 份/);
vm.runInContext('wireEpisodeSelector()',ctx);
ctx.document.activeElement=null;
node('dataset').onblur();
assert.match(node('dataset').options[0].text,/已人工标注 3 份/,'Blur must apply the latest cached statuses');
assert.equal(node('dataset').value,'1');
assert.equal(vm.runInContext('segments[0].caption',ctx),'Unsaved manual draft');
vm.runInContext("kind='fine_action';renderEpisodeChoices()",ctx);
assert.doesNotMatch(node('dataset').options[0].text,/已人工标注 2/,'Subtask count cannot leak into fine action');
reply={annotation_type:'fine_action',episodes:[{episode_index:0,human_count:0,needs_review:true},{episode_index:1,human_count:1,needs_review:false}]};
await vm.runInContext('refreshEpisodeStatuses()',ctx);
assert.match(node('dataset').options[0].text,/异常.*未人工标注/);
assert.match(node('dataset').options[1].text,/已人工标注 1 份/);
fail=true;await vm.runInContext('refreshEpisodeStatuses()',ctx);
assert.match(node('dataset').options[1].text,/已人工标注 1 份/,'An outage must retain last known statuses');
assert.match(node('dataset').title,/失败/);
fail=false;
let resolveOld;
ctx.fetch=async()=>new Promise(resolve=>{resolveOld=resolve;});
const old=vm.runInContext('refreshEpisodeStatuses()',ctx);
vm.runInContext("kind='subtask'",ctx);
resolveOld({ok:true,json:async()=>reply});await old;
vm.runInContext('renderEpisodeChoices()',ctx);
assert.doesNotMatch(node('dataset').options[1].text,/已人工标注 1 份/,'Late response for another type must be ignored');
console.log('PASS: episode status labels, counts by type, anomaly flag, selection and draft preserved, outage and stale responses');
