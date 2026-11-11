import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../static/app.mjs', import.meta.url), 'utf8')
  .replace(/^import[^\n]+\n/, '').replace(/init\(\)\.catch[^\n]*;\s*$/, '');
const nodes = new Map();
function element() { return {value:'',textContent:'',open:false,disabled:false,children:[],
  showModal(){this.open=true;},close(){this.open=false;},focus(){},
  replaceChildren(...children){this.children=children;},append(...children){this.children.push(...children);}}; }
const node = id => { if(!nodes.has(id)) nodes.set(id,element());return nodes.get(id); };
let resolveRequest, rejectRequest;
let sentBody;
const ctx = vm.createContext({URL,URLSearchParams,structuredClone,
  location:{origin:'http://localhost',search:'?episode=41'},
  document:{getElementById:node,createElement:element},
  localStorage:{setItem(){}},
  fetch:async(url,options)=>{sentBody=JSON.parse(options.body);return new Promise((resolve,reject)=>{resolveRequest=resolve;rejectRequest=reject;});},
});
vm.runInContext(source,ctx);
vm.runInContext("info={dataset_name:'demo',episode_index:41};kind='subtask';segments=[{start_frame:0,end_frame:100,caption:'Pick up white. Put white in dryer.',category:''}];videos=[{pause(){this.paused=true;}}];render=()=>{};",ctx);
const before = vm.runInContext('JSON.stringify(segments)',ctx);
vm.runInContext('openCaptionAssist(0)',ctx);
assert.equal(node('caption-assist-dialog').open,true);
const pending = vm.runInContext('generateCaptionAssist()',ctx);
assert.equal(node('caption-assist-apply').disabled,true);
resolveRequest({ok:true,json:async()=>({caption:'Place the white garment in the dryer.',warnings:['检查区间。']})});
await pending;
assert.equal(vm.runInContext('JSON.stringify(segments)',ctx),before,'Generation must not edit labels');
assert.equal(node('caption-assist-result').value,'Place the white garment in the dryer.');
node('caption-assist-result').value='Place the white garment fully in the dryer.';
vm.runInContext('applyCaptionAssist()',ctx);
assert.equal(vm.runInContext('segments[0].caption',ctx),'Place the white garment fully in the dryer.');
assert.equal(vm.runInContext('segments[0].start_frame',ctx),0);
assert.equal(vm.runInContext('segments[0].end_frame',ctx),100);
vm.runInContext('restore(past,future)',ctx);
assert.equal(vm.runInContext('JSON.stringify(segments)',ctx),before,'Adoption must be undoable');
vm.runInContext('openCaptionAssist(0)',ctx);
const late = vm.runInContext('generateCaptionAssist()',ctx);
vm.runInContext('closeCaptionAssist()',ctx);
resolveRequest({ok:true,json:async()=>({caption:'Late result',warnings:[]})});await late;
assert.equal(vm.runInContext('JSON.stringify(segments)',ctx),before,'Cancelled requests must not edit labels');
vm.runInContext('openCaptionAssist(0)',ctx);
const failed=vm.runInContext('generateCaptionAssist()',ctx);
rejectRequest(Error('offline'));await failed;
assert.equal(node('caption-assist-apply').disabled,true);
assert.equal(vm.runInContext('JSON.stringify(segments)',ctx),before);
vm.runInContext('openCaptionAssist(0)',ctx);
const stale=vm.runInContext('generateCaptionAssist()',ctx);
resolveRequest({ok:true,json:async()=>({caption:'Outdated suggestion',warnings:[]})});await stale;
vm.runInContext("segments[0].caption='New manual edit';applyCaptionAssist()",ctx);
assert.equal(vm.runInContext('segments[0].caption',ctx),'New manual edit','A stale preview must not replace a later edit');
assert.equal(node('caption-assist-apply').disabled,true);
vm.runInContext("closeCaptionAssist();openCaptionAssist(0,'diversify')",ctx);
assert.equal(node('caption-assist-title').textContent,'多样化改写 · Subtask');
const rewrite=vm.runInContext('generateCaptionAssist()',ctx);
assert.equal(sentBody.mode,'diversify');
resolveRequest({ok:true,json:async()=>({caption:'Use the right hand to place the white clothing in the dryer.',warnings:[]})});await rewrite;
assert.equal(vm.runInContext('segments[0].caption',ctx),'New manual edit');
vm.runInContext('applyCaptionAssist()',ctx);
assert.equal(vm.runInContext('segments[0].caption',ctx),'Use the right hand to place the white clothing in the dryer.');
assert.equal(vm.runInContext('segments[0].end_frame',ctx),100);
vm.runInContext('restore(past,future)',ctx);
assert.equal(vm.runInContext('segments[0].caption',ctx),'New manual edit');
console.log('PASS: preview, edited adoption, fixed boundaries, undo, cancellation, failed request preserves draft');
