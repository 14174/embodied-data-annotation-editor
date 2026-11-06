import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Run the production page logic with small DOM/network substitutes; no video is loaded.
const source = fs.readFileSync(new URL('../static/app.mjs', import.meta.url), 'utf8')
  .replace(/^import[^\n]+\n/, '').replace(/init\(\)\.catch[^\n]*;\s*$/, '');
class Events {
  constructor() { this.listeners=new Map(); }
  addEventListener(name,listener) { const list=this.listeners.get(name)||[];list.push(listener);this.listeners.set(name,list); }
  emit(name) { for(const listener of this.listeners.get(name)||[]) listener(); }
}
function page() {
  const elements = new Map();
  const node = id => {
    if (!elements.has(id)) elements.set(id, {
      textContent:'', title:'', value:'', options:[], disabled:false,
      replaceChildren(...options) { this.options=options; this.value=options[0]?.value || ''; },
    });
    return elements.get(id);
  };
  let records=[], fail=false, interval;
  const document = Object.assign(new Events(), {hidden:false, getElementById:node});
  const window = new Events();
  const location = {href:'http://localhost/editor?episode=0',origin:'http://localhost',search:'?episode=0'};
  const context = vm.createContext({document,window,location,URL,URLSearchParams,structuredClone,
    Option:class { constructor(text,value) { this.text=text;this.value=value; } },
    localStorage:{setItem(){}},
    setInterval(callback) { interval=callback;return 1; },
    fetch:async()=>{ if(fail) throw Error('offline');return {ok:true,json:async()=>structuredClone(records)}; },
  });
  vm.runInContext(source, context);
  vm.runInContext("info={dataset_name:'test',episode_index:0,episodes:[{},{}]};preset={result:{segments:[{}]}};submitted=[];segments=[{start_frame:0,end_frame:10,caption:'未提交编辑'}];source='FLORA';",context);
  return {context,node,window,document,location,
    records(value){records=value;}, offline(){fail=true;}, poll(){return interval();}};
}
const record=(annotator,annotation_type='subtask')=>({annotator,annotation_type,created_at:1});
const p=page();
vm.runInContext('sourceChoices()',p.context);
assert.equal(p.node('human-annotation-count').textContent,'人工标注：0 份');
p.records([record('甲'),record('乙','fine_action')]);
await vm.runInContext('refreshAnnotations()',p.context);
assert.equal(p.node('human-annotation-count').textContent,'人工标注：1 份');
p.node('source').value='person:甲';
const original=vm.runInContext('JSON.stringify({segments,source})',p.context);
p.records([record('甲'),record('丙'),record('乙','fine_action')]);
await vm.runInContext('refreshAnnotations()',p.context);
assert.equal(p.node('human-annotation-count').textContent,'人工标注：2 份');
assert.equal(p.node('source').value,'person:甲');
assert.equal(vm.runInContext('JSON.stringify({segments,source})',p.context),original);
vm.runInContext("kind='fine_action';sourceChoices()",p.context);
assert.equal(p.node('human-annotation-count').textContent,'人工标注：1 份');
p.offline();await vm.runInContext('refreshAnnotations()',p.context);
assert.match(p.node('human-annotation-count').textContent,/1 份.*同步失败/);

const q=page();vm.runInContext('startAnnotationSync()',q.context);
q.records([record('另一位用户')]);await q.poll();
assert.equal(q.node('human-annotation-count').textContent,'人工标注：1 份');
q.records([record('另一位用户'),record('新用户')]);
q.window.emit('focus');
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(q.node('human-annotation-count').textContent,'人工标注：2 份');

const allDone=page();
allDone.context.fetch=async()=>({ok:true,json:async()=>({episode_index:1,unannotated:false})});
await vm.runInContext('nextEpisode()',allDone.context);
assert.equal(allDone.location.href,'http://localhost/editor?episode=0');
assert.match(allDone.node('notice').textContent,/已.*人工标注/);
console.log('PASS: counts by type, background/focus sync, selection and edits preserved, stale status, no automatic repeat');
