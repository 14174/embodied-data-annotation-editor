import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const script=fs.readFileSync(new URL('../static/app.mjs',import.meta.url),'utf8').replace(/^import[^\n]+\n/gm,'').replace(/init\(\)\.catch[^\n]*;\s*$/,'');
const ctx=vm.createContext({URL,URLSearchParams,structuredClone,location:{origin:'http://localhost',href:'http://localhost/editor?dataset=one:2026-11-18&episode=0',search:'?dataset=one:2026-11-18&episode=0'},document:{getElementById:()=>({})}});
vm.runInContext(script,ctx);
assert.equal(vm.runInContext("apiUrl('video?camera=scene').searchParams.get('dataset')",ctx),'one:2026-11-18','Every media/API request must retain dataset context');
const module=await import('../static/collections.mjs');
const saved=new Map();const storage={get length(){return saved.size},key:i=>[...saved.keys()][i],getItem:key=>saved.get(key)||null,setItem:(key,value)=>saved.set(key,value)};
const oldKey=JSON.stringify(['annotation-editor-workspace','old-name',0,'subtask','person:jby']);
saved.set(oldKey,'draft');saved.set(JSON.stringify(['annotation-editor-vocabulary','old-name','subtask']),'vocab');
module.migrateLegacyWorkspace(storage,{dataset_id:'default',legacy_dataset_name:'old-name'});
assert.equal(saved.get(JSON.stringify(['annotation-editor-workspace','default',0,'subtask','person:jby'])),'draft');
assert.equal(saved.get(JSON.stringify(['annotation-editor-vocabulary','default','subtask'])),'vocab');
saved.set(JSON.stringify(['annotation-editor-position','two:2026-11-19']),JSON.stringify({episode:3}));
const url=module.datasetUrl('http://localhost/editor?dataset=one:2026-11-18&episode=9&kind=subtask',
 {id:'two:2026-11-19',first_episode:0,episode_indexes:[0,3]},'fine_action',storage);
assert.equal(url.searchParams.get('dataset'),'two:2026-11-19');
assert.equal(url.searchParams.get('episode'),'3');assert.equal(url.searchParams.get('kind'),'fine_action');
const migrated=JSON.stringify(['annotation-editor-workspace','default',0,'subtask','person:jby']);
saved.delete(migrated);
module.migrateLegacyWorkspace(storage,{dataset_id:'default',legacy_dataset_name:'old-name'});
assert.equal(saved.has(migrated),false,'Deleted submitted drafts must not be resurrected by migration');
module.migrateLegacyWorkspace(storage,{dataset_id:'two:2026-11-19',legacy_dataset_name:null});
assert.equal(saved.has(JSON.stringify(['annotation-editor-workspace','two:2026-11-19',0,'subtask','person:jby'])),false);
console.log('PASS: dataset in every request, remembered episode, legacy draft/vocabulary migration, dataset isolation');
// A collection with a single date must still offer a change from a placeholder.
const nodes=new Map();
globalThis.Option=class {constructor(text,value){this.text=text;this.value=value;}};
globalThis.document={getElementById(id){
 if (!nodes.has(id)) nodes.set(id,{value:'',textContent:'',disabled:false,addEventListener(){},
   replaceChildren(...children){this.children=children;this.value=children[0]?.value||'';}});
 return nodes.get(id);
}};
const data={collections:[{id:'legacy',name:'原有',root:'/data/original',datasets:[{id:'default',name:'旧数据',available:true,episode_count:1,first_episode:0}]},
 {id:'single',name:'单日期合集',root:'/data/laundry',datasets:[{id:'single:2026-11-18',name:'2026-11-18',available:true,episode_count:1,first_episode:0}]}]};
await module.mountCollections({info:{dataset_id:'default'},api:async()=>data,beforeLeave:()=>true,getKind:()=> 'subtask',isBusy:()=>false});
assert.match(nodes.get('collection-root').textContent,/\/data\/original/);
assert.match(nodes.get('collection-select').children[1].text,/\/data\/laundry/);
nodes.get('collection-select').value='single';nodes.get('collection-select').onchange();
assert.match(nodes.get('collection-root').textContent,/\/data\/laundry/);
assert.equal(nodes.get('date-select').value,'','Single-date collections must await an explicit date choice');
assert.ok(nodes.get('date-select').children.some(option=>option.value==='single:2026-11-18'));
nodes.get('collection-select').value='legacy';nodes.get('collection-select').onchange();
assert.match(nodes.get('collection-root').textContent,/\/data\/original/);
assert.equal(nodes.get('date-select').value,'default');
delete globalThis.document;delete globalThis.Option;

saved.set(JSON.stringify(['annotation-editor-position','stale']),JSON.stringify({episode:99}));
assert.equal(module.datasetUrl('http://localhost/editor',{id:'stale',first_episode:0,episode_indexes:[0,3]},'subtask',storage).searchParams.get('episode'),'0','Removed episodes must fall back to a valid episode');
const recovery=new Map();
const recoveryCtx=vm.createContext({URL,URLSearchParams,structuredClone,location:{origin:'http://localhost',search:'?dataset=offline&episode=0'},
 document:{getElementById:id=>{if(!recovery.has(id))recovery.set(id,{disabled:false,textContent:''});return recovery.get(id);}}});
vm.runInContext(script,recoveryCtx);
let recoveryConfig;
recoveryCtx.mountCollections=async options=>{recoveryConfig=options;};
assert.equal(vm.runInContext('typeof recoverDatasetLoad',recoveryCtx),'function','Offline dataset needs a working dataset selector');
await vm.runInContext("recoverDatasetLoad(Error('dataset unavailable'))",recoveryCtx);
assert.equal(recoveryConfig.info.dataset_id,'offline');
assert.equal(recoveryConfig.beforeLeave(),true);
assert.equal(recovery.get('submit').disabled,true);
