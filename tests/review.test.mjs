import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../static/app.mjs',import.meta.url),'utf8')
  .replace(/^import[^\n]+\n/,'').replace(/init\(\)\.catch[^\n]*;\s*$/,'');
function page(server){
  const nodes=new Map();
  function element(){return {children:[],value:'',open:false,hidden:false,disabled:false,textContent:'',
    replaceChildren(){this.children=[];this.textContent='';},append(...children){this.children.push(...children);},
    showModal(){this.open=true;},close(){this.open=false;},focus(){this.focused=true;}};}
  const node=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
  const context=vm.createContext({URL,URLSearchParams,structuredClone,
    location:{origin:'http://localhost',search:'?episode=9'},
    document:{getElementById:node,createElement:element},localStorage:{setItem(){}},
    fetch:async(url,options={})=>{
      if(options.method==='POST'){
        if(server.fail)throw Error('offline');
        const body=JSON.parse(options.body);
        const flag={...body,report_id:String(server.flags.length+1),created_at:1700000000,status:'needs_review'};
        server.flags.unshift(flag);return {ok:true,json:async()=>structuredClone(flag)};
      }
      return {ok:true,json:async()=>({flags:structuredClone(server.flags)})};
    },
  });
  vm.runInContext(source,context);
  vm.runInContext("info={dataset_name:'demo',episode_index:9};kind='subtask';segments=[{start_frame:0,end_frame:10,caption:'Pick green'}];videos=[{pause(){this.paused=true;}}];humanAnnotationCount=1;",context);
  node('author').value='甲';
  return {context,node};
}
const server={flags:[],fail:false};const a=page(server);
await vm.runInContext('refreshReviewFlags()',a.context);assert.equal(a.node('review-status').hidden,true);
vm.runInContext('openReview()',a.context);
assert.equal(a.node('review-dialog').open,true);assert.equal(a.node('review-author').value,'甲');
assert.equal(vm.runInContext('videos[0].paused',a.context),true);
await vm.runInContext('submitReview()',a.context);assert.equal(server.flags.length,0);
assert.equal(a.node('review-note').focused,true);
a.node('review-note').value='Instruction mismatch <script>alert(1)</script>';
server.fail=true;await vm.runInContext('submitReview()',a.context);
assert.equal(a.node('review-note').value,'Instruction mismatch <script>alert(1)</script>');
assert.equal(a.node('submit-review').disabled,false);
server.fail=false;await vm.runInContext('submitReview()',a.context);
assert.equal(server.flags.length,1);assert.equal(a.node('review-note').value,'');
assert.equal(a.node('review-status').hidden,false);
assert.match(a.node('review-feedback').textContent,/已标记异常/);
assert.equal(vm.runInContext('humanAnnotationCount',a.context),1);
assert.equal(vm.runInContext('segments[0].caption',a.context),'Pick green');
assert.equal(a.node('review-flags').children[0].children[1].textContent,'Instruction mismatch <script>alert(1)</script>');
const b=page(server);await vm.runInContext('refreshReviewFlags()',b.context);
assert.equal(b.node('review-status').hidden,false);assert.match(b.node('review-status-button').textContent,/1 条/);
assert.equal(vm.runInContext('segments[0].caption',b.context),'Pick green');
console.log('PASS: required note, failed-submit retry, episode-wide flag visibility, literal note rendering, annotations and counts preserved');
