import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Catch missing selection updates, destructive imports, lost browser persistence,
// and changes to annotation boundaries/history when choosing a caption.
const source = fs.readFileSync(new URL('../static/app.mjs', import.meta.url), 'utf8')
  .replace(/^import[^\n]+\n/gm, '').replace(/init\(\)\.catch[^\n]*;\s*$/, '');
const saved = new Map();
function element(tag='div') {
  return {tagName:tag.toUpperCase(), children:[], value:'', textContent:'', dataset:{},
    get options(){return this.children;}, style:{setProperty(){}}, classList:{toggle(){},add(){},remove(){}},
    append(...items){this.children.push(...items);},
    replaceChildren(...items){this.children=items;}, setAttribute(key,value){this[key]=value;},
    querySelectorAll(){return this.children.flatMap(child=>[child,...(child.querySelectorAll?.() || [])]);}};
}
function page() {
  const nodes = new Map();
  const node = id => {if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
  const ctx = vm.createContext({URL,URLSearchParams,structuredClone,
    location:{origin:'http://localhost',search:'?episode=0'},
    document:{getElementById:node,createElement:element},
    Option:class {constructor(text,value){this.text=text;this.value=value;}},
    localStorage:{getItem:key=>saved.get(key)||null,setItem:(key,value)=>saved.set(key,value),removeItem:key=>saved.delete(key)},
    fetch:async()=>({ok:true,json:async()=>JSON.parse(fs.readFileSync(new URL('../static/caption-vocabulary.json',import.meta.url),'utf8'))})});
  vm.runInContext(source,ctx);
  return {ctx,node,run:code=>vm.runInContext(code,ctx)};
}
const first=page();
assert.equal(first.run('typeof initializeVocabulary'),'function','Caption vocabulary initialization is missing');
const helpers=await import('../static/caption-vocabulary.mjs');
Object.assign(first.ctx,helpers);
first.run("info={dataset_name:'laundry',episode_index:0,fps:30,frame_count:20};segments=[{start_frame:0,end_frame:10,caption:'',category:''},{start_frame:10,end_frame:20,caption:'Old manual caption',category:''}];render=()=>renderCards();updatePlayback=()=>{};updateButtons=()=>{};");
await first.run('initializeVocabulary()');
assert.equal(first.run('captionVocabulary.items.length'),8);
first.run('renderCards()');
const cards=first.node('segment-list').children;
const choice=card=>card.children.find(el=>el.className==='caption-choice');
assert.equal(choice(cards[0]).value,'','Blank segments must not choose the first caption');
assert.equal(choice(cards[1]).value,'','Old free captions remain custom');
choice(cards[0]).value='washer_open'; choice(cards[0]).onchange({stopPropagation(){}});
assert.equal(first.node('segment-list').children[0],cards[0], 'Choosing a caption must retain the mounted card and its focused control');
assert.equal(cards[0].children.find(el=>el.tagName==='TEXTAREA').value,'Open the door of the washing machine below');
assert.equal(first.run('segments[0].caption'),'Open the door of the washing machine below');
assert.deepEqual(JSON.parse(first.run('JSON.stringify(segments.map(s=>[s.start_frame,s.end_frame]))')),[[0,10],[10,20]]);
first.run('restore(past,future)');
assert.equal(first.run('segments[0].caption'),'');
first.run('restore(future,past)');
assert.equal(first.run('segments[0].caption'),'Open the door of the washing machine below');
const current=first.node('segment-list').children[0];
const input=current.children.find(el=>el.tagName==='TEXTAREA');
input.onfocus();input.value='Free custom caption';input.oninput();
assert.equal(choice(current).value,'','Editing a standard caption must clear the selected option');
input.value='Open the door of the washing machine below';input.oninput();
assert.equal(choice(current).value,'washer_open');input.onblur();
const custom={id:'other',name:'另一个任务',version:'1',items:[{id:'open',caption:'Open the box',label_zh:'打开盒子'}]};
first.ctx.custom=custom;
const before=first.run('JSON.stringify(segments)');
await first.run('importVocabularyFile({text:async()=>JSON.stringify(custom)})');
assert.equal(first.run('captionVocabulary.id'),'other');
assert.equal(first.run('JSON.stringify(segments)'),before,'Changing vocabulary must not edit annotations');
assert.equal(choice(first.node('segment-list').children[0]).value,'');
await first.run('importVocabularyFile({text:async()=>"broken JSON"})');
assert.equal(first.run('captionVocabulary.id'),'other','Invalid input must preserve the active vocabulary');
assert.ok(first.node('vocabulary-feedback').textContent.includes('失败'));
for (const bad of [{...custom,items:[]},{...custom,items:[custom.items[0],custom.items[0]]},{...custom,items:[{id:'x',caption:''}]}]) {
  assert.throws(()=>helpers.validateVocabulary(bad));
}
const second=page();Object.assign(second.ctx,helpers);
second.run("info={dataset_name:'laundry',episode_index:7};");
await second.run('initializeVocabulary()');
assert.equal(second.run('captionVocabulary.id'),'other','Imported files persist across episode reloads');
second.run("info.dataset_name='different';");await second.run('initializeVocabulary()');
assert.equal(second.run('captionVocabulary.id'),'other','The selected vocabulary must be shared across datasets');
const store=first.ctx.localStorage.setItem;
first.ctx.localStorage.setItem=()=>{throw Error('storage quota');};
await first.run('importVocabularyFile({text:async()=>JSON.stringify({...custom,id:"failed"})})');
assert.equal(first.run('captionVocabulary.id'),'other','Storage failures preserve the loaded vocabulary');
first.ctx.localStorage.setItem=store;
first.run("kind='fine_action';updateVocabularyControls();renderCards()");
assert.equal(first.node('vocabulary-bar').hidden,true);
assert.ok(first.node('segment-list').children.every(card=>!choice(card)));
first.run("kind='subtask'");
await first.run('resetVocabulary()');
assert.equal(first.run('captionVocabulary.id'),'laundry_drying');
assert.equal(first.run('JSON.stringify(segments)'),before);
await second.run('initializeVocabulary()');
assert.equal(second.run('captionVocabulary.id'),'laundry_drying','Reset applies globally after switching datasets');
first.run("info.dataset_name='laundry'");await first.run('initializeVocabulary()');
assert.equal(first.run('captionVocabulary.id'),'laundry_drying','Reset must not resurrect an old dataset-specific import');
// Migrate an old per-dataset import once; the global selection wins afterward.
saved.clear();
saved.set(JSON.stringify(['annotation-editor-vocabulary','laundry','subtask']),JSON.stringify(custom));
await first.run('initializeVocabulary()');
assert.equal(first.run('captionVocabulary.id'),'other');
await second.run('initializeVocabulary()');
assert.equal(second.run('captionVocabulary.id'),'other','Legacy imports migrate to the shared selection');
await first.run('resetVocabulary()');await first.run('initializeVocabulary()');
assert.equal(first.run('captionVocabulary.id'),'laundry_drying','Legacy imports stay superseded after reset');
console.log('PASS: closed captions, free edits, Undo/Redo, non-destructive imports/reset, validation and episode persistence');
