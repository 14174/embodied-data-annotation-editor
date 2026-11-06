import { splitAt, moveBoundary, mergeAt } from './segments.mjs';

const $ = id => document.getElementById(id);
const colors = ['#5a95d4', '#5eaf94', '#9e89db', '#d18c77', '#baa265'];
const pageEpisode = new URLSearchParams(location.search).get('episode');
function apiUrl(path) {
  const url = new URL('/editor-api/' + path, location.origin);
  if (pageEpisode !== null) url.searchParams.set('episode', pageEpisode);
  return url;
}
const api = async (path, options) => {
  const response = await fetch(apiUrl(path), {cache:'no-store', ...options});
  if (!response.ok) {
    const {detail} = await response.json().catch(() => ({}));
    const message = typeof detail === 'string' ? detail : detail?.message;
    throw Object.assign(new Error(message || response.statusText), {status:response.status, detail});
  }
  return response.json();
};
let info, preset, signals;
let segments = [], past = [], future = [], submitted = [];
let author = '', kind = 'subtask', source = null, videos = [], active = -1, zoom = 1, drag = null;
let loading = false, saving = false;
let humanAnnotationCount = 0, annotationRead = 0;
const master = () => videos[0];
const duration = () => info.frame_count / info.fps;
const frame = () => Math.min(info.frame_count - 1, Math.floor((master()?.currentTime || 0) * info.fps + 0.0001));
const seconds = f => (f / info.fps).toFixed(2);
const percent = f => f / info.frame_count * 100 + '%';
const draftKey = () => JSON.stringify(['annotation-editor-workspace', info.dataset_name, info.episode_index, kind]);
const legacyDraftKey = name => JSON.stringify(['annotation-editor', info.dataset_name, info.episode_index, name, kind]);
const blank = () => [{start_frame:0, end_frame:info.frame_count, caption:'', category:''}];
const snapshot = () => ({segments:structuredClone(segments), source});
const status = text => { $('save-status').textContent = text; };
function warn(text = '') {
  $('notice').hidden = !text;
  $('notice').textContent = text;
}
function persist() {
  try {
    localStorage.setItem(draftKey(), JSON.stringify(snapshot()));
    status('本地草稿已保存');
    return true;
  } catch {
    status('本地草稿保存失败');
    return false;
  }
}

function switchEpisode(value) {
  if (saving || loading) return;
  if (!persist()) {
    $('dataset').value = String(info.episode_index);
    warn('当前草稿保存失败，已保留在页面中。请导出 JSON 后再切换。');
    return;
  }
  const url = new URL(location.href);
  url.searchParams.set('episode', value);
  url.searchParams.set('kind', kind);
  location.href = url.href;
}

async function nextEpisode() {
  if (saving || loading) return;
  const button = $('next-episode');
  const requestedKind = kind;
  button.disabled = true;
  try {
    const next = await api('next-episode?' + new URLSearchParams({kind}));
    if (kind !== requestedKind) return;
    if (next.episode_index === null) warn('没有其他 episode 可切换。');
    else if (!next.unannotated) warn('其余 episode 的当前类型都已有人工标注。如需复标，请从顶部列表手动选择。');
    else switchEpisode(next.episode_index);
  } catch (error) {
    warn('读取下一条失败：' + error.message);
  } finally {
    button.disabled = !info.episodes || info.episodes.length < 2;
  }
}
function seek(target) {
  target = Math.max(0, Math.min(info.frame_count - 1, target));
  const time = (target + 0.001) / info.fps;
  videos.forEach(video => { if (video.readyState) video.currentTime = time; });
  updatePlayback(target);
}
function frameStep() {
  const value = $('frame-step').valueAsNumber;
  const limit = Math.max(1, info.frame_count - 1);
  return Number.isFinite(value) ? Math.max(1, Math.min(limit, Math.trunc(value))) : 1;
}
function stepFrames(direction) {
  if (!master()?.readyState) return;
  videos.forEach(video => video.pause());
  seek(frame() + direction * frameStep());
}
function wireFrameButton(button, direction) {
  let delay, interval, pointerId, repeated = false;
  const stop = event => {
    if (event.pointerId !== undefined && event.pointerId !== pointerId) return;
    clearTimeout(delay);
    clearInterval(interval);
    pointerId = undefined;
  };
  button.addEventListener('pointerdown', event => {
    if (event.button !== 0 || pointerId !== undefined) return;
    repeated = false;
    pointerId = event.pointerId;
    button.setPointerCapture(pointerId);
    delay = setTimeout(() => {
      repeated = true;
      stepFrames(direction);
      interval = setInterval(() => stepFrames(direction), 110);
    }, 350);
  });
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture', 'blur']) {
    button.addEventListener(type, stop);
  }
  window.addEventListener('blur', stop);
  button.addEventListener('contextmenu', event => event.preventDefault());
  button.addEventListener('click', event => {
    if (event.detail === 0 || !repeated) stepFrames(direction);
    repeated = false;
  });
}
function selectSegment(index) {
  const segment = segments[index];
  if (!segment || !master()?.readyState || drag) return;
  master().loopSegment = segment;
  seek(segment.start_frame);
}
function change(next, nextSource = source, previous = snapshot()) {
  if (next === segments && nextSource === source) return;
  past.push(previous);
  future = [];
  segments = next;
  source = nextSource;
  persist();
  render();
}
function restore(from, to) {
  if (loading || saving || drag || !from.length) return;
  to.push(snapshot());
  ({segments, source} = from.pop());
  persist();
  render();
}
function updatePlayback(at = frame(), force = false) {
  const index = segments.findIndex(s => s.start_frame <= at && at < s.end_frame);
  $('clock').textContent = seconds(at) + ' / ' + duration().toFixed(2) + ' s';
  $('frame-info').textContent = '帧 ' + at + ' / ' + (info.frame_count - 1);
  $('scrub').value = at;
  $('playhead').style.left = percent(at);
  if (index === active && !force) return;
  const changed = index !== active;
  active = index;
  $('prev-segment').disabled = index <= 0;
  $('next-segment').disabled = index < 0 || index >= segments.length - 1;
  $('caption-preview').textContent = segments[index]?.caption || '当前区间尚无 caption';
  document.querySelectorAll('[data-segment]').forEach(el => el.classList.toggle('active', Number(el.dataset.segment) === index));
  const list = $('segment-list');
  const card = list.children[index];
  if (changed && card && $('follow').checked && !drag && !list.contains(document.activeElement)) {
    const bounds = list.getBoundingClientRect();
    const row = card.getBoundingClientRect();
    if (row.top < bounds.top) list.scrollTop += row.top - bounds.top;
    else if (row.bottom > bounds.bottom) list.scrollTop += row.bottom - bounds.bottom;
  }
}
function tick() {
  const video = master();
  if (video && !video.paused) {
    const loop = video.loopSegment;
    if ($('loop').checked && loop && video.currentTime >= loop.end_frame / info.fps) seek(loop.start_frame);
    for (const follower of videos.slice(1)) {
      if (!follower.seeking && follower.readyState >= 2 && Math.abs(follower.currentTime - video.currentTime) > .12) {
        follower.currentTime = video.currentTime;
      }
    }
  }
  const at = frame();
  updatePlayback(at);
  if (at !== lastSignalFrame) drawSignals(at);
  requestAnimationFrame(tick);
}
function mountVideos() {
  const labels = {scene:'场景 / SCENE', left_wrist:'左腕 / LEFT WRIST', right_wrist:'右腕 / RIGHT WRIST'};
  const rank = ['left_wrist', 'scene', 'right_wrist'];
  const suffix = key => key.split('.').at(-1);
  const cams = [...info.cameras].sort((a,b) => rank.indexOf(suffix(a)) - rank.indexOf(suffix(b)));
  videos = cams.map(key => {
    const view = document.createElement('div');
    view.className = 'view';
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.preload = 'auto';
    video.src = apiUrl('video?' + new URLSearchParams({camera:key}));
    video.addEventListener('click', togglePlay);
    video.addEventListener('error', () => warn('无法读取相机 ' + key + ' 的视频'));
    const label = document.createElement('div');
    label.className = 'view-label';
    label.textContent = labels[suffix(key)] || suffix(key);
    view.append(video,label);
    $('views').append(view);
    return video;
  });
  const leader = master();
  leader.addEventListener('play', () => {
    $('play').textContent = '❚❚';
    $('play').setAttribute('aria-label', '暂停');
  });
  leader.addEventListener('pause', () => {
    $('play').textContent = '▶';
    $('play').setAttribute('aria-label', '播放');
    videos.slice(1).forEach(video => video.pause());
  });
  leader.addEventListener('ended', () => {
    if ($('loop').checked && leader.loopSegment) {
      seek(leader.loopSegment.start_frame);
      togglePlay();
    }
  });
}
async function togglePlay() {
  const leader = master();
  if (!leader) return;
  if (!leader.paused) {
    videos.forEach(video => video.pause());
    return;
  }
  if (leader.ended) seek(0);
  leader.loopSegment = segments.find(s => s.start_frame <= frame() && frame() < s.end_frame);
  const time = leader.currentTime;
  const requests = videos.map(video => {
    if (video !== leader && video.readyState) video.currentTime = time;
    return video.play();
  });
  if ((await Promise.allSettled(requests)).some(result => result.status === 'rejected')) {
    videos.forEach(video => video.pause());
    warn('播放启动失败，请刷新后重试。');
  }
}
function positionBlocks() {
  const track = $('segments-track');
  const blocks = track.querySelectorAll('.block');
  const handles = track.querySelectorAll('.boundary');
  segments.forEach((s,i) => {
    blocks[i].style.left = percent(s.start_frame);
    blocks[i].style.width = percent(s.end_frame - s.start_frame);
    if (i) {
      handles[i-1].style.left = percent(s.start_frame);
      handles[i-1].title = '边界 ' + seconds(s.start_frame) + ' 秒，可拖动';
    }
    const stamp = $('segment-list').children[i]?.querySelector('.time-btn');
    if (stamp) stamp.textContent = seconds(s.start_frame) + '–' + seconds(s.end_frame) + ' s';
  });
}
function frameAt(event, element) {
  const rect = element.getBoundingClientRect();
  return Math.round((event.clientX - rect.left) / rect.width * info.frame_count);
}
function renderTimeline() {
  const track = $('segments-track');
  track.replaceChildren();
  for (const [i] of segments.entries()) {
    const block = document.createElement('button');
    block.className = 'block';
    block.dataset.segment = i;
    block.style.setProperty('--color',colors[i % colors.length]);
    block.textContent = i + 1;
    block.onclick = () => selectSegment(i);
    track.append(block);
  }
  for (let i=1; i<segments.length; i++) {
    const handle = document.createElement('button');
    handle.className = 'boundary';
    handle.setAttribute('aria-label', '拖动第 ' + i + ' 个边界');
    handle.onpointerdown = event => {
      if (event.button !== 0 || loading || saving || drag) return;
      videos.forEach(video => video.pause());
      handle.setPointerCapture(event.pointerId);
      drag = {previous:snapshot(), start:segments[i].start_frame, pointerId:event.pointerId};
      event.preventDefault();
    };
    handle.onpointermove = event => {
      if (drag?.pointerId !== event.pointerId || !handle.hasPointerCapture(event.pointerId)) return;
      segments = moveBoundary(segments, i, frameAt(event,track));
      positionBlocks();
      seek(segments[i].start_frame);
    };
    handle.onpointerup = event => {
      if (drag?.pointerId !== event.pointerId) return;
      const {previous,start} = drag;
      drag = null;
      if (segments[i].start_frame !== start) {
        past.push(previous);
        future = [];
        persist();
      }
      render();
    };
    const cancelDrag = event => {
      if (drag?.pointerId !== event.pointerId) return;
      ({segments,source} = drag.previous);
      drag = null;
      render();
    };
    handle.onpointercancel = cancelDrag;
    handle.onlostpointercapture = cancelDrag;
    handle.onkeydown = event => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      event.stopPropagation();
      if (loading || saving || drag) return;
      change(moveBoundary(segments,i,segments[i].start_frame + (event.key === 'ArrowLeft' ? -1 : 1)));
      $('segments-track').querySelectorAll('.boundary')[i-1]?.focus();
      seek(segments[i].start_frame);
    };
    track.append(handle);
  }
  positionBlocks();
}
function renderCards() {
  $('segment-list').replaceChildren();
  segments.forEach((segment,i) => {
    const card = document.createElement('article');
    card.className = 'segment-card';
    card.dataset.segment = i;
    card.style.setProperty('--color',colors[i % colors.length]);
    const head = document.createElement('div');
    head.className = 'card-head';
    const number = document.createElement('b');
    number.textContent = String(i+1).padStart(2,'0');
    const timestamp = document.createElement('button');
    timestamp.className = 'time-btn';
    timestamp.onclick = () => selectSegment(i);
    head.append(number,timestamp);
    if (i) {
      const merge = document.createElement('button');
      merge.textContent = '与上一段合并';
      merge.onclick = () => change(mergeAt(segments,i));
      head.append(merge);
    }
    card.append(head);
    const field = (el,key) => {
      el.value = segment[key] || '';
      el.onfocus = () => {
        const previous = snapshot();
        el.oninput = () => {
          if (el.value === segments[i][key]) return;
          if (!el.edited) {
            past.push(previous);
            future = [];
            el.edited = true;
          }
          segments[i] = {...segments[i],[key]:el.value};
          persist();
          updatePlayback(frame(),true);
          updateButtons();
        };
      };
      el.onblur = () => { el.edited = false; if (key === 'category') updateCategories(); };
      return el;
    };
    const caption = document.createElement('textarea');
    caption.placeholder = '填写这段的动作描述…';
    caption.setAttribute('aria-label','第 ' + (i+1) + ' 段 caption');
    card.append(field(caption,'caption'));
    if (kind === 'fine_action') {
      const category = document.createElement('input');
      category.className = 'category';
      category.placeholder = '选择或输入动作类别';
      category.setAttribute('list','categories');
      card.append(field(category,'category'));
    }
    $('segment-list').append(card);
  });
}
function updateCategories() {
  const values = [...new Set(segments.map(s => s.category).filter(Boolean))];
  $('categories').replaceChildren(...values.map(value => {
    const option = document.createElement('option');
    option.value = value;
    return option;
  }));
}
function updateButtons() {
  for (const field of $('segment-list').querySelectorAll('textarea,input,button')) field.disabled = loading || saving;
  $('undo').disabled = !past.length || loading || saving;
  $('redo').disabled = !future.length || loading || saving;
  for (const id of ['submit','mark','blank','import','export','kind','author']) $(id).disabled = loading || saving;
}
function render() {
  renderCards();
  renderTimeline();
  updateCategories();
  updatePlayback(frame(),true);
  updateButtons();
}
function ruler() {
  $('timeline-content').style.width = zoom * 100 + '%';
  $('zoom-label').textContent = zoom + '×';
  const ticks = [];
  for (let i=0;i<=5*zoom;i++) {
    const label = document.createElement('span');
    label.className = 'tick';
    label.style.left = i/(5*zoom)*100 + '%';
    label.textContent = (duration()*i/(5*zoom)).toFixed(1) + ' s';
    ticks.push(label);
  }
  $('ruler').replaceChildren(...ticks);
}
function sourceChoices() {
  const records = submitted.filter(r => r.annotation_type === kind);
  humanAnnotationCount = new Set(records.map(r => r.annotator)).size;
  $('human-annotation-count').textContent = '人工标注：' + humanAnnotationCount + ' 份';
  $('human-annotation-count').title = '当前标注类型下已提交的人工标注人数；预标注与本地草稿不计入。每 3 秒自动同步。';
  $('annotation-stats').textContent = kind + ' · ' + humanAnnotationCount + ' 份已提交';
  const select = $('source'), selected = select.value;
  const options = [...(kind === 'subtask' && preset.result.segments.length ? [new Option('FLORA 预标注','flora')] : []),
    ...records.map(r => new Option(r.annotator + ' 的标注', 'person:' + r.annotator))];
  if (select.options.length !== options.length || options.some((option,i) =>
      option.value !== select.options[i].value || option.text !== select.options[i].text)) {
    select.replaceChildren(...options);
    if (options.some(option => option.value === selected)) select.value = selected;
  }
}
async function refreshAnnotations() {
  const request = ++annotationRead;
  try {
    const records = await api('annotations');
    if (request !== annotationRead) return false;
    if (!Array.isArray(records)) throw Error('标注列表格式无效');
    submitted = records;
    sourceChoices();
    return true;
  } catch {
    if (request === annotationRead) {
      $('human-annotation-count').textContent = '人工标注：' + humanAnnotationCount + ' 份 · 同步失败';
      $('human-annotation-count').title = '显示上次同步的数量，连接恢复后自动重试；正在编辑的内容保留。';
    }
    return false;
  }
}
function startAnnotationSync() {
  setInterval(() => { if (!document.hidden) return refreshAnnotations(); }, 3000);
  window.addEventListener('focus', () => refreshAnnotations());
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshAnnotations(); });
}
function updateAuthor() {
  author = $('author').value.trim();
  localStorage.setItem('annotation-editor-author', author);
}
function context() {
  kind = $('kind').value;
  sourceChoices();
  warn();
  let draft = null;
  try {
    const key = draftKey();
    const currentDraft = localStorage.getItem(key);
    const legacyKey = [legacyDraftKey(author), legacyDraftKey('')].find(k => localStorage.getItem(k));
    const legacy = !currentDraft && legacyKey ? localStorage.getItem(legacyKey) : null;
    draft = JSON.parse(currentDraft || legacy || 'null');
    if (legacy) {
      localStorage.setItem(key, legacy);
      localStorage.removeItem(legacyKey);
    }
  } catch (error) {
    warn('读取本地草稿时遇到问题：' + error.message);
  }
  const usePreset = kind === 'subtask' && preset.result.segments.length;
  segments = draft ? structuredClone(draft.segments) : usePreset ? structuredClone(preset.result.segments) : blank();
  source = draft ? draft.source : usePreset ? 'FLORA' : null;
  if (preset.warning && kind === 'subtask' && !draft) warn('预标注暂不可用：' + preset.warning);
  past = [];
  future = [];
  status(draft ? '已恢复本地草稿' : '可开始标注');
  render();
}
function askOverwrite() {
  const dialog = $('overwrite-dialog');
  $('overwrite-message').textContent = 'Episode ' + info.episode_index + ' 已有「' + author +
    '」的' + (kind === 'subtask' ? '子任务' : '细粒度动作') + '标注。要用当前标注覆盖吗？';
  return new Promise(resolve => {
    dialog.returnValue = 'cancel';
    dialog.addEventListener('close', () => resolve(dialog.returnValue), {once:true});
    dialog.showModal();
  });
}
function payload() {
  return {dataset_name:info.dataset_name, episode_index:info.episode_index, fps:info.fps,
    frame_count:info.frame_count, annotation_type:kind, annotator:author,
    source_annotation:source, result:{segments}};
}
async function submit() {
  if (saving || loading || drag) return;
  updateAuthor();
  if (!author) { warn('请先填写标注人姓名'); $('author').focus(); return; }
  if (segments.some(s => !s.caption.trim() || (kind === 'fine_action' && !s.category.trim()))) {
    warn('请补齐每段 caption 和所需的动作类别。');
    return;
  }
  saving = true;
  updateButtons();
  warn();
  try {
    const body = payload();
    for (;;) {
      try {
        await api('annotation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        break;
      } catch (error) {
        if (error.status !== 409 || typeof error.detail?.created_at !== 'number') throw error;
        persist();
        const decision = await askOverwrite();
        if (decision !== 'yes') {
          if (decision === 'no') status('已保留原提交和当前草稿');
          return;
        }
        body.expected_created_at = error.detail.created_at;
      }
    }
    localStorage.removeItem(draftKey());
    status('已提交');
    await refreshAnnotations();
  } catch(error) { warn(error.message); }
  finally { saving = false; updateButtons(); }
}
async function importSource() {
  const selected = $('source').value;
  if (!selected || loading || saving) return;
  loading = true;
  updateButtons();
  try {
    const record = selected === 'flora' ? preset : await api('annotation?' + new URLSearchParams({author:selected.slice(7),kind}));
    if (!record) throw Error('这份标注已不可用');
    change(structuredClone(record.result.segments), selected === 'flora' ? 'FLORA' : selected.slice(7));
  } catch(error) { warn(error.message); }
  finally { loading = false; updateButtons(); }
}
function mark() {
  if (loading || saving) return;
  if (drag) {
    status('请先松开正在拖动的边界');
    return;
  }
  const video = master();
  if (!video || video.readyState < 1) {
    status('等待视频时间轴加载');
    return;
  }
  if (video.ended) {
    status('视频末尾已有边界');
    return;
  }
  const current = frame();
  const next = splitAt(segments,current);
  if (next === segments) status('此帧已有边界');
  else change(next);
}
function renderSignals() {
  $('signal-options').replaceChildren();
  $('signal-plots').replaceChildren();
  if (!signals?.names.length) {
    $('signal-options').textContent = '这条样例没有可用信号。';
    return;
  }
  signals.names.forEach((name,index) => {
    const label = document.createElement('label');
    const toggle = document.createElement('input');
    toggle.type = 'checkbox';
    toggle.checked = index === 0;
    const plot = document.createElement('div');
    plot.className = 'signal';
    const title = document.createElement('span');
    title.textContent = name;
    const canvas = document.createElement('canvas');
    canvas.width = 800;
    canvas.height = 100;
    canvas.onclick = event => seek(frameAt(event,canvas));
    label.append(toggle,document.createTextNode(name));
    plot.append(title,canvas);
    $('signal-options').append(label);
    $('signal-plots').append(plot);
    toggle.onchange = () => { plot.hidden = !toggle.checked; drawSignals(frame()); };
    plot.hidden = !toggle.checked;
  });
}
let lastSignalFrame = -1;
function drawSignals(at) {
  if (!signals || !$('signal-plots').closest('details').open) return;
  for (const [i,plot] of [...$('signal-plots').children].entries()) {
    if (plot.hidden) continue;
    const canvas = plot.querySelector('canvas');
    const ctx = canvas.getContext('2d');
    const values = signals.values.map(row => row[i]);
    const finite = values.filter(Number.isFinite);
    const [min,max] = [Math.min(...finite), Math.max(...finite)];
    const width = canvas.width, height = canvas.height;
    ctx.clearRect(0,0,width,height);
    ctx.fillStyle = '#0a1322';
    ctx.fillRect(0,0,width,height);
    ctx.strokeStyle = colors[i % colors.length];
    ctx.lineWidth = 2;
    ctx.beginPath();
    let started = false;
    values.forEach((v,j) => {
      if (!Number.isFinite(v)) { started = false; return; }
      const x = j/info.frame_count*width;
      const y = max === min ? height/2 : height-8-(v-min)/(max-min)*(height-16);
      if (started) ctx.lineTo(x,y);
      else ctx.moveTo(x,y);
      started = true;
    });
    ctx.stroke();
    ctx.fillStyle = '#29baf4';
    ctx.fillRect(at/info.frame_count*width,0,2,height);
  }
  lastSignalFrame = at;
}
function wire() {
  $('play').onclick = togglePlay;
  $('prev-segment').onclick = () => selectSegment(active - 1);
  $('next-segment').onclick = () => selectSegment(active + 1);
  const player = $('player');
  const fullscreen = $('fullscreen');
  fullscreen.hidden = !document.fullscreenEnabled;
  fullscreen.onclick = async () => {
    try {
      if (document.fullscreenElement === player) await document.exitFullscreen();
      else await player.requestFullscreen();
    } catch {
      warn('当前浏览器无法切换全屏');
    }
  };
  document.addEventListener('fullscreenchange', () => {
    const label = document.fullscreenElement === player ? '退出全屏' : '全屏';
    fullscreen.setAttribute('aria-label', label);
    fullscreen.title = label;
  });
  $('frame-step').max = Math.max(1, info.frame_count - 1);
  $('frame-step').onchange = () => { $('frame-step').value = frameStep(); };
  wireFrameButton($('prev-frame'), -1);
  wireFrameButton($('next-frame'), 1);
  $('speed').onchange = event => videos.forEach(v => { v.playbackRate = Number(event.target.value); });
  $('loop').onchange = () => { master().loopSegment = segments[active]; };
  $('mark').onclick = mark;
  $('scrub').oninput = event => seek(Number(event.target.value));
  $('ruler').onclick = event => seek(frameAt(event,$('ruler')));
  $('zoom-in').onclick = () => { zoom = Math.min(8,zoom*2); ruler(); };
  $('zoom-out').onclick = () => { zoom = Math.max(1,zoom/2); ruler(); };
  $('undo').onclick = () => restore(past,future);
  $('redo').onclick = () => restore(future,past);
  $('author').onchange = updateAuthor;
  $('author').onkeydown = event => { if (event.key === 'Enter') $('author').blur(); };
  $('kind').onchange = () => { context(); refreshAnnotations(); };
  $('dataset').onchange = event => switchEpisode(event.target.value);
  $('next-episode').onclick = nextEpisode;
  $('next-episode').disabled = !info.episodes || info.episodes.length < 2;
  $('submit').onclick = submit;
  $('import').onclick = importSource;
  $('blank').onclick = () => change(blank(),null);
  $('signal-plots').closest('details').ontoggle = () => drawSignals(frame());
  $('export').onclick = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload(),null,2)], {type:'application/json'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'episode_' + info.episode_index + '_' + kind + '.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url),1000);
  };
  document.addEventListener('keydown', event => {
    if (event.target.matches('textarea,input,select,[contenteditable]')) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
      event.preventDefault();
      event.shiftKey ? restore(future,past) : restore(past,future);
    } else if (!event.ctrlKey && !event.metaKey && !event.altKey && !event.repeat && event.key.toLowerCase() === 'm') {
      event.preventDefault();
      mark();
    } else if (event.code === 'Space' && !event.target.closest('button')) {
      event.preventDefault();
      togglePlay();
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      stepFrames(event.key === 'ArrowLeft' ? -1 : 1);
    }
  });
}
async function init() {
  [info,preset,submitted] = await Promise.all([api('info'),api('source'),api('annotations')]);
  {
    $('episode-selector-label').textContent = 'Episode（共 ' + info.episodes.length + ' 条）';
    $('dataset').replaceChildren(...info.episodes.map(episode => new Option(
      'Episode ' + String(episode.episode_index).padStart(3,'0') + ' · ' +
      (episode.frame_count / info.fps).toFixed(1) + ' s', String(episode.episode_index))));
    $('dataset').value = String(info.episode_index);
  }
  $('author').value = localStorage.getItem('annotation-editor-author') || '';
  const requestedKind = new URLSearchParams(location.search).get('kind');
  if (['subtask', 'fine_action'].includes(requestedKind)) $('kind').value = requestedKind;
  $('instruction').textContent = info.instruction || '—';
  $('episode-info').textContent = 'Episode ' + info.episode_index + ' · ' + info.frame_count + ' 帧 · ' + duration().toFixed(2) + ' s';
  $('scrub').max = info.frame_count - 1;
  mountVideos();
  ruler();
  wire();
  updateAuthor();
  context();
  startAnnotationSync();
  requestAnimationFrame(tick);
  try {
    signals = await api('signals');
    renderSignals();
    drawSignals(frame());
  } catch {
    $('signal-options').textContent = '状态曲线暂不可用。';
  }
}
init().catch(error => { warn('编辑页加载失败：' + error.message); status('加载失败'); });
