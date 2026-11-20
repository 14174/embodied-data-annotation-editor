import assert from 'node:assert/strict';
import {mountCollections} from '../static/collections.mjs';

const nodes=new Map();
globalThis.Option=class {constructor(text,value){this.text=text;this.value=value;}};
globalThis.document={hidden:false,activeElement:null,getElementById(id){
  if (!nodes.has(id)) nodes.set(id,{value:'',textContent:'',disabled:false,open:false,
    addEventListener(){},replaceChildren(...children){this.children=children;this.value=children[0]?.value||'';}});
  return nodes.get(id);
}};
let tick,close,interval,cleared=false,editing=false,calls=0,left=0;
globalThis.window={setInterval(callback,ms){tick=callback;interval=ms;return 77;},
  addEventListener(name,callback){if(name==='pagehide')close=callback;},
  clearInterval(id){assert.equal(id,77);cleared=true;}};
const data={fixed_root:'/data1/huggingface/raw_data',scan_interval_seconds:30,
  collections:[{id:'fixed',name:'采集数据',root:'/data1/huggingface/raw_data',fixed:true,datasets:[{id:'default',name:'20261118_144854',available:true,episode_count:6,first_episode:0}]}]};
await mountCollections({info:{dataset_id:'default'},api:async()=>{calls++;return structuredClone(data);},
  beforeLeave:()=>{left++;return true;},getKind:()=> 'subtask',isBusy:()=>editing});
assert.equal(nodes.get('collection-add').hidden,true);
assert.equal(nodes.get('collection-select').disabled,true);
assert.equal(nodes.get('collection-path').readOnly,true);
assert.match(nodes.get('collection-root').textContent,/\/data1\/huggingface\/raw_data/);
assert.equal(interval,30000);
data.collections[0].datasets.push({id:'fixed:new',name:'20261120_120000',available:false,status:'needs_preparation',episode_count:2,reason:'需要准备播放视频'});
document.activeElement=nodes.get('date-select');
await tick();assert.equal(calls,1,'Do not replace an open native date dropdown');
document.activeElement=null;editing=true;
await tick();assert.equal(calls,1,'Do not refresh during edits or requests');
editing=false;await tick();
assert.equal(calls,2);
assert.equal(nodes.get('date-select').value,'default','Automatic scans retain the selected episode/dataset');
const option=nodes.get('date-select').children.find(o=>o.value==='fixed:new');
assert.equal(option.disabled,true);assert.match(option.text,/待准备/);
assert.equal(left,0,'Background scans must never navigate or persist/switch drafts');
data.collections.push({id:'previous',name:'历史合集',root:'/data/previous',datasets:[{id:'previous:one',name:'one',available:true,episode_count:2,first_episode:0}]});
await tick();
assert.equal(nodes.get('collection-select').disabled,false,'Registered roots must remain selectable in fixed-root mode');
nodes.get('collection-select').value='previous';nodes.get('collection-select').onchange();
assert.match(nodes.get('collection-root').textContent,/\/data\/previous/);
assert.equal(nodes.get('date-select').value,'');
await tick();
assert.equal(nodes.get('collection-select').value,'previous','Background scans retain the selected collection path');
assert.match(nodes.get('collection-root').textContent,/\/data\/previous/);
nodes.get('collection-select').value='fixed';nodes.get('collection-select').onchange();
assert.equal(nodes.get('date-select').value,'default');
assert.match(nodes.get('collection-root').textContent,/自动扫描/);
close();assert.equal(cleared,true);
delete globalThis.document;delete globalThis.window;delete globalThis.Option;
console.log('PASS: fixed root UI, automatic scan, unchanged selection, pending uploads, dropdown/edit protection');
