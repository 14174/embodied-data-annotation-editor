import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const script = fs.readFileSync(new URL('../static/app.mjs', import.meta.url), 'utf8')
  .replace(/^import[^\n]+\n/gm, '').replace(/init\(\)\.catch[^\n]*;\s*$/, '');
const storage = new Map();
const row = caption => [{start_frame:0, end_frame:10, caption, category:''}];

function page(index, record = row('jby ' + index)) {
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {value:'', textContent:'', options:[],
      replaceChildren(...options) { this.options = options; this.value = options[0]?.value || ''; }});
    return nodes.get(id);
  };
  let offline = false;
  const ctx = vm.createContext({URL, URLSearchParams, structuredClone,
    location:{origin:'http://localhost', search:'?episode=' + index},
    document:{getElementById:node},
    Option:class { constructor(text, value) { this.text=text; this.value=value; } },
    localStorage:{getItem:key => storage.get(key) || null, setItem:(key,value) => storage.set(key,value),
      removeItem:key => storage.delete(key)},
    fetch:async input => {
      if (offline) throw Error('offline');
      const found = new URL(input).searchParams.get('author') === 'jby' ? record : null;
      return {ok:true, json:async () => found && {source_annotation:'FLORA', result:{segments:found}}};
    }});
  vm.runInContext(script, ctx);
  vm.runInContext(`info={dataset_name:'test',episode_index:${index},frame_count:10,fps:30,episodes:[{}]};
    preset={source_annotation:'FLORA',result:{segments:${JSON.stringify(row('flora ' + index))}}};
    submitted=[{annotator:'jby',annotation_type:'subtask'}];
    render=()=>{};renderEpisodeChoices=()=>{};updateButtons=()=>{};`, ctx);
  node('kind').value = 'subtask';
  return {ctx,node,offline:() => { offline=true; }};
}

const first = page(0);
await vm.runInContext('context()', first.ctx);
assert.equal(first.node('source').value, 'flora');
first.node('source').value = 'person:jby';
await vm.runInContext('importSource({restoreDraft:true})', first.ctx);
assert.equal(vm.runInContext('segments[0].caption', first.ctx), 'jby 0');
assert.equal(first.node('source').value, 'person:jby');
vm.runInContext("segments[0].caption='edited jby';persist()", first.ctx);

storage.set(JSON.stringify(['annotation-editor-workspace','test',1,'subtask']),
  JSON.stringify({source:'FLORA',segments:row('unrelated legacy draft')}));
const second = page(1);
await vm.runInContext('context()', second.ctx);
assert.equal(second.node('source').value, 'person:jby');
assert.equal(vm.runInContext('segments[0].caption', second.ctx), 'jby 1');

const back = page(0);
await vm.runInContext('context()', back.ctx);
assert.equal(vm.runInContext('segments[0].caption', back.ctx), 'edited jby');
back.node('source').value = 'flora';
await vm.runInContext('importSource({restoreDraft:true})', back.ctx);
assert.equal(back.node('source').value, 'flora');
vm.runInContext('restore(past,future)', back.ctx);
assert.equal(back.node('source').value, 'person:jby');
assert.equal(vm.runInContext('segments[0].caption', back.ctx), 'edited jby');

// Explicitly select jby again to make it the cross-episode preference.
await vm.runInContext('importSource({restoreDraft:true})', back.ctx);
const absent = page(2, null);
await vm.runInContext('context()', absent.ctx);
assert.equal(absent.node('source').value, 'flora');
assert.equal(vm.runInContext('segments[0].caption', absent.ctx), 'flora 2');
assert.match(absent.node('notice').textContent, /已加载/);
const next = page(3);
await vm.runInContext('context()', next.ctx);
assert.equal(next.node('source').value, 'person:jby');

// A failed request must restore the selector to the content still on screen.
next.node('source').value = 'flora';
await vm.runInContext('importSource()', next.ctx);
next.offline();
next.node('source').value = 'person:jby';
await vm.runInContext('importSource()', next.ctx);
assert.equal(next.node('source').value, 'flora');
assert.equal(vm.runInContext('segments[0].caption', next.ctx), 'flora 3');
assert.match(next.node('notice').textContent, /offline/);

const types = page(4);
await vm.runInContext('context()', types.ctx);
types.node('source').value = 'person:jby';
await vm.runInContext('importSource()', types.ctx);
types.node('kind').value = 'fine_action';
await vm.runInContext('context()', types.ctx);
assert.equal(types.node('source').value, 'blank');
types.node('kind').value = 'subtask';
await vm.runInContext('context()', types.ctx);
assert.equal(types.node('source').value, 'person:jby');
storage.delete(JSON.stringify(['annotation-editor-source','test','subtask']));
const oldKey = JSON.stringify(['annotation-editor-workspace','test',5,'subtask']);
storage.set(oldKey, JSON.stringify({source:'jby',segments:row('legacy jby draft')}));
const migrated = page(5);
await vm.runInContext('context()', migrated.ctx);
assert.equal(vm.runInContext('segments[0].caption', migrated.ctx), 'legacy jby draft');
assert.equal(migrated.node('source').value, 'person:jby');
assert.equal(storage.has(oldKey), false);

const preference = JSON.stringify(['annotation-editor-source','test','subtask']);
storage.set(preference, 'person:missing');
const otherHuman = page(6);
await vm.runInContext('context()', otherHuman.ctx);
assert.equal(otherHuman.node('source').value, 'person:jby');
assert.equal(vm.runInContext('segments[0].caption', otherHuman.ctx), 'jby 6');
assert.equal(storage.get(preference), 'person:missing');
const modelOnly = page(7, null);
vm.runInContext("preset.result.segments=[];modelPreset={source_annotation:'TempSeg-SFT-v1',result:{segments:[{start_frame:0,end_frame:10,caption:'',category:''}]}}", modelOnly.ctx);
await vm.runInContext('context()', modelOnly.ctx);
assert.equal(modelOnly.node('source').value, 'model:tempseg-sft-v1');
assert.equal(vm.runInContext('segments.length', modelOnly.ctx), 1);
console.log('PASS: persistent source, matching drafts, selector synchronization, missing source and failure');
