/** Collection UI and navigation. All changes leave the current annotation intact. */
export function migrateLegacyWorkspace(storage, info) {
  if (info.dataset_id !== 'default' || !info.legacy_dataset_name) return;
  const marker=JSON.stringify(['annotation-editor-migrated',info.dataset_id,info.legacy_dataset_name]);
  if (storage.getItem(marker)) return;
  const prefixes = new Set(['annotation-editor-workspace','annotation-editor','annotation-editor-source','annotation-editor-vocabulary']);
  const keys=Array.from({length:storage.length},(_,i)=>storage.key(i));
  for (const key of keys) {
    let parts;try {parts=JSON.parse(key);} catch {continue;}
    if (!Array.isArray(parts) || !prefixes.has(parts[0]) || parts[1]!==info.legacy_dataset_name) continue;
    parts[1]=info.dataset_id;
    const next=JSON.stringify(parts);
    if (storage.getItem(next)===null) storage.setItem(next,storage.getItem(key));
  }
  storage.setItem(marker,'1');
}
export function datasetUrl(href, item, kind, storage) {
  const url=new URL(href);
  let saved;try {saved=JSON.parse(storage.getItem(JSON.stringify(['annotation-editor-position',item.id])));} catch {}
  url.searchParams.set('dataset',item.id);
  url.searchParams.set('episode',Number.isInteger(saved?.episode) && item.episode_indexes?.includes(saved.episode) ? saved.episode : item.first_episode);
  url.searchParams.set('kind',kind);
  return url;
}
export async function mountCollections({info,api,beforeLeave,getKind,isBusy}) {
  const $=id=>document.getElementById(id);
  let catalog=null, scannedPath=null, busy=false;
  const feedback=text=>{$('collection-feedback').textContent=text;$('collection-dialog-feedback').textContent=text;};
  const post=(path,data)=>api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  function buttons() {
    for (const id of ['collection-scan','collection-confirm','collection-refresh','collection-archive']) $(id).disabled=busy;
    $('collection-confirm').disabled=busy||!scannedPath;
  }
  function currentCollection() {return catalog?.collections.find(c=>c.id===$('collection-select').value);}
  function showDates() {
    const collection=currentCollection();
    const options=(collection?.datasets||[]).map(row=>{
      const label=row.name+' · '+(row.available ? row.episode_count+' 条 · 已标 '+row.annotated_count+' 条' : '不可用：'+row.reason)+(row.archived?' · 只读':'');
      const option=new Option(label,row.id);option.disabled=!row.available;return option;
    });
    if (!collection?.datasets.some(row=>row.id===info.dataset_id)) options.unshift(new Option('请选择日期数据集',''));
    $('date-select').replaceChildren(...options);
    if (collection?.datasets.some(row=>row.id===info.dataset_id)) $('date-select').value=info.dataset_id;
    $('collection-refresh').disabled=busy||!collection||collection.id==='legacy';
    const selected=collection?.datasets.find(row=>row.id===$('date-select').value);
    $('collection-archive').textContent=selected?.archived?'取消归档':'设为只读';
    $('collection-archive').disabled=busy||!selected;
  }
  async function reload(preferredCollection) {
    catalog=await api('collections?'+new URLSearchParams({kind:getKind()}));
    $('collection-select').replaceChildren(...catalog.collections.map(c=>new Option(c.name,c.id)));
    const current=catalog.collections.find(c=>c.datasets.some(row=>row.id===info.dataset_id));
    $('collection-select').value=preferredCollection||current?.id||catalog.collections[0]?.id||'';
    showDates();
  }
  async function operation(action) {
    if (busy||isBusy()) return;
    busy=true;buttons();
    try {await action();} catch(error) {feedback('操作失败：'+error.message);}
    finally {busy=false;buttons();showDates();}
  }
  $('collection-select').onchange=()=>{showDates();feedback('选择日期后切换；当前标注会先保存为草稿。');};
  $('date-select').onchange=()=>{
    const item=currentCollection()?.datasets.find(row=>row.id===$('date-select').value);
    if (!item?.available || item.id===info.dataset_id) return;
    if (busy||isBusy()||!beforeLeave()) {showDates();return;}
    location.href=datasetUrl(location.href,item,getKind(),localStorage).href;
  };
  $('collection-add').onclick=()=>{
    if (isBusy()) return;
    scannedPath=null;$('collection-preview').replaceChildren();feedback('');buttons();
    $('collection-dialog').showModal();
  };
  $('collection-close').onclick=()=>{if(!busy)$('collection-dialog').close();};
  $('collection-dialog').addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  $('collection-path').oninput=()=>{scannedPath=null;buttons();};
  $('collection-scan').onclick=()=>operation(async()=>{
    const path=$('collection-path').value.trim();scannedPath=null;
    const data=await post('collections/scan',{path});
    $('collection-preview').replaceChildren(...data.datasets.map(row=>{
      const label=document.createElement('label');label.className='collection-preview-row';
      const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.value=row.name;
      checkbox.checked=row.available;checkbox.disabled=!row.available;
      const text=document.createElement('span');text.textContent=row.name+' · '+(row.available?row.episode_count+' 条 episode':'不可用：'+row.reason);
      label.append(checkbox,text);return label;
    }));
    scannedPath=path;feedback('扫描完成，请勾选日期，再点击“确认添加”。');
  });
  $('collection-confirm').onclick=()=>operation(async()=>{
    if (!scannedPath||scannedPath!==$('collection-path').value.trim()) throw Error('路径改变，请重新扫描');
    const dates=[...$('collection-preview').querySelectorAll('input:checked')].map(input=>input.value);
    await post('collections',{name:$('collection-name').value.trim(),path:scannedPath,dates});
    await reload();$('collection-dialog').close();scannedPath=null;feedback('合集已添加，可选择合集与日期切换。');
  });
  $('collection-refresh').onclick=()=>operation(async()=>{
    const collection=currentCollection();if(!collection||collection.id==='legacy') return;
    await post('collections/refresh',{collection_id:collection.id});
    await reload(collection.id);feedback('列表已刷新，当前页面和草稿保持不变。');
  });
  $('collection-archive').onclick=()=>operation(async()=>{
    const item=currentCollection()?.datasets.find(row=>row.id===$('date-select').value);
    if (!item) return;
    await post('datasets/archive',{dataset_id:item.id,archived:!item.archived});
    await reload(currentCollection().id);
    feedback(item.archived?'已取消归档。':'已归档，仅可查看和导出；已有标注保留。');
  });
  await reload();buttons();showDates();
  return {refresh:()=>reload($('collection-select').value)};
}
