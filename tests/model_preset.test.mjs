import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const script=fs.readFileSync(new URL('../static/app.mjs',import.meta.url),'utf8')
  .replace(/^import[^\n]+\n/gm,'').replace(/init\(\)\.catch[^\n]*;\s*$/,'');
const ctx=vm.createContext({URL,URLSearchParams,structuredClone,
  location:{origin:'http://localhost',search:''},document:{getElementById:()=>({})}});
vm.runInContext(script,ctx);
vm.runInContext("info={episode_index:5,fps:30,frame_count:60}",ctx);
const record={episode_index:5,fps:30,frame_count:60,source_annotation:'TempSeg-SFT-v2-epoch07',annotation_type:'subtask',
  result:{segments:[{start_frame:0,end_frame:60,caption:'',category:''}]}};
ctx.bundle={source_annotation:record.source_annotation,episodes:[record]};
assert.equal(vm.runInContext('modelRecord(bundle).source_annotation',ctx),'TempSeg-SFT-v2-epoch07');
vm.runInContext('modelPreset=modelRecord(bundle)',ctx);
assert.equal(vm.runInContext('modelChoice()',ctx),'model:tempseg-sft-v2-epoch07');
assert.equal(vm.runInContext("sourceChoice('TempSeg-SFT-v1')",ctx),'model:tempseg-sft-v1');
vm.runInContext('info.episode_index=0',ctx);
assert.equal(vm.runInContext('modelRecord(bundle)',ctx),null,'Missing episodes in partial bundles need no warning');
vm.runInContext('info.episode_index=5',ctx);
ctx.bundle.episodes[0].result.segments[0].end_frame=59;
assert.throws(()=>vm.runInContext('modelRecord(bundle)',ctx),/末尾/);
console.log('PASS: v2 source identity, v1 compatibility, partial bundles and missing final frame rejection');
