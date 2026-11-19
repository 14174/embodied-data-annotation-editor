import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {mergeSelected} from '../static/segments.mjs';
const source=fs.readFileSync(new URL('../static/app.mjs',import.meta.url),'utf8')
  .replace(/^import[^\n]+\n/gm,'').replace(/init\(\)\.catch[^\n]*;\s*$/,'');
function element() {
  const classes=new Set();
  return {children:[],dataset:{},style:{setProperty(){}},value:'',disabled:false,checked:false,
    classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),
      toggle(x,value){if(value)classes.add(x);else classes.delete(x);}},
    append(...children){this.children.push(...children);},
    replaceChildren(...children){this.children=children;},setAttribute(k,v){this[k]=v;},
    querySelector(selector){return this.children.flatMap(x=>x.children||[]).find(x=>x.className===selector.slice(1));},
  };
}
const nodes=new Map();
const node=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
const ctx=vm.createContext({document:{getElementById:node,createElement:element},
  location:{origin:'http://localhost',search:'?episode=0'},URL,URLSearchParams,structuredClone,
  localStorage:{setItem(){}},mergeSelected});
vm.runInContext(source,ctx);
vm.runInContext("info={dataset_name:'test',episode_index:0,fps:30,frame_count:40};kind='subtask';segments=[{start_frame:0,end_frame:10,caption:'a',category:''},{start_frame:10,end_frame:20,caption:'b',category:''},{start_frame:20,end_frame:30,caption:'b',category:''},{start_frame:30,end_frame:40,caption:'c',category:''}];render=()=>{renderCards();updateBatchSelection();};render()",ctx);
const original=vm.runInContext('JSON.stringify(segments)',ctx);
function select(index,checked=true,shiftKey=false) {
  const checkbox=node('segment-list').children[index].querySelector('.segment-selection');
  checkbox.checked=checked;
  let stopped=false;checkbox.onclick({shiftKey,stopPropagation(){stopped=true;}});assert.ok(stopped);
  if(checkbox.onchange)checkbox.onchange();
}
select(0);assert.equal(node('merge-selected').disabled,true);
select(2);assert.equal(node('merge-selected').disabled,true);
assert.match(node('batch-selection-status').textContent,/请选择连续/);
vm.runInContext('mergeSelectedSegments()',ctx);
assert.equal(vm.runInContext('JSON.stringify(segments)',ctx),original);
select(1);assert.equal(node('merge-selected').disabled,false);
vm.runInContext('mergeSelectedSegments()',ctx);
assert.equal(vm.runInContext('segments.length',ctx),2);
assert.equal(vm.runInContext('segments[0].caption',ctx),'a\nb');
assert.equal(vm.runInContext('segments[0].end_frame',ctx),30);
assert.equal(node('batch-selection-status').textContent,'已选 0 段');
assert.equal(node('merge-selected').disabled,true);
vm.runInContext('restore(past,future)',ctx);
assert.equal(vm.runInContext('JSON.stringify(segments)',ctx),original);
select(1);select(2);vm.runInContext('clearSegmentSelection()',ctx);
assert.equal(node('batch-selection-status').textContent,'已选 0 段');
assert.ok(node('segment-list').children.every(card=>!card.querySelector('.segment-selection').checked));
assert.equal(vm.runInContext('JSON.stringify(segments)',ctx),original);
select(0);select(3,true,true);
assert.equal(node('batch-selection-status').textContent,'已选 4 段','Shift selects every segment in the interval');
assert.equal(node('merge-selected').disabled,false);
select(1,false,true);
assert.equal(node('batch-selection-status').textContent,'已选 1 段','Shift unchecks the selected interval');
vm.runInContext('clearSegmentSelection()',ctx);
select(3);select(1,true,true);
assert.equal(node('batch-selection-status').textContent,'已选 3 段','Shift works backwards');
vm.runInContext('clearSegmentSelection()',ctx);
select(2,true,true);
assert.equal(node('batch-selection-status').textContent,'已选 1 段','Clearing must reset the range anchor');
vm.runInContext('selectAllSegments()',ctx);
assert.equal(node('batch-selection-status').textContent,'已选 4 段');
assert.ok(node('segment-list').children.every(card=>card.querySelector('.segment-selection').checked));
vm.runInContext('mergeSelectedSegments()',ctx);
assert.equal(vm.runInContext('segments.length',ctx),1);
assert.equal(vm.runInContext('segments[0].end_frame',ctx),40);
vm.runInContext('restore(past,future)',ctx);
assert.equal(vm.runInContext('JSON.stringify(segments)',ctx),original);
console.log('PASS: checkbox events, disjoint rejection, merge, cleared selection, Undo, manual clear');
