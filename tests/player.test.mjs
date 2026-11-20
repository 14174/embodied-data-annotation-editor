import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync(new URL('../static/app.mjs', import.meta.url), 'utf8')
  .replace(/^import[^\n]+\n/gm, '').replace(/init\(\)\.catch[^\n]*;\s*$/, '');
function page(paused = false) {
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {
      style:{}, children:[], valueAsNumber:5, checked:false, attributes:{},
      listeners:{}, addEventListener(name, fn) { this.listeners[name] = fn; },
      getBoundingClientRect:() => ({left:-100, width:1000}),
      setPointerCapture(id) { this.pointerId = id; },
      releasePointerCapture() { this.pointerId = null; },
      setAttribute(name, value) { this.attributes[name] = value; },
      contains:() => false,
    });
    return nodes.get(id);
  };
  const videos = [0,1].map(() => ({readyState:4, currentTime:2, paused,
    pause() { this.paused = true; }}));
  const context = vm.createContext({URL, URLSearchParams, structuredClone, videos,
    location:{search:''}, window:{addEventListener() {}},
    document:{getElementById:node, querySelectorAll:() => [], activeElement:null}});
  vm.runInContext(source, context);
  context.fixtureVideos = videos;
  vm.runInContext("info={fps:10,frame_count:100};videos=fixtureVideos;segments=[{start_frame:0,end_frame:50,caption:'first'},{start_frame:50,end_frame:100,caption:'second'}]", context);
  const event = (clientX, pointerId = 1, boundary = false) => ({clientX, pointerId, button:0,
    target:{closest:selector => selector === '.boundary' && boundary ? {} : null},
    preventDefault() {}});
  return {context, node, videos, event};
}

test('frame stepping synchronizes views without pausing playback', () => {
  const p = page();
  vm.runInContext('stepFrames(1)', p.context);
  assert.ok(p.videos.every(video => !video.paused));
  assert.ok(p.videos.every(video => Math.abs(video.currentTime - 2.5001) < 0.00001));
  vm.runInContext('stepFrames(-1)', p.context);
  assert.ok(p.videos.every(video => Math.abs(video.currentTime - 2.0001) < 0.00001));
});

test('frame stepping retains pause and clamps to the first and last frame', () => {
  const p = page(true);
  p.node('frame-step').valueAsNumber = 500;
  vm.runInContext('stepFrames(1)', p.context);
  assert.ok(p.videos.every(video => Math.abs(video.currentTime - 9.9001) < 0.00001 && video.paused));
  vm.runInContext('stepFrames(-1)', p.context);
  assert.ok(p.videos.every(video => Math.abs(video.currentTime - 0.0001) < 0.00001 && video.paused));
});

test('stepping across a looping segment continues in the destination segment', () => {
  const p = page();
  p.videos.forEach(video => { video.currentTime = 4.8; });
  p.node('loop').checked = true;
  p.context.requestAnimationFrame = () => {};
  vm.runInContext('master().loopSegment=segments[0];drawSignals=()=>{};stepFrames(1);tick()', p.context);
  assert.ok(p.videos.every(video => Math.abs(video.currentTime - 5.3001) < 0.00001 && !video.paused));
});

test('dragging the segment track seeks precisely across segments without editing annotations', () => {
  const p = page();
  const before = vm.runInContext('JSON.stringify(segments)', p.context);
  vm.runInContext('wireTimelineScrub()', p.context);
  const track = p.node('timeline-content');
  track.listeners.pointerdown(p.event(100));
  track.listeners.pointermove(p.event(650));
  assert.ok(p.videos.every(video => Math.abs(video.currentTime - 7.5001) < 0.00001 && !video.paused));
  track.listeners.pointerup(p.event(800));
  assert.ok(p.videos.every(video => Math.abs(video.currentTime - 9.0001) < 0.00001));
  assert.equal(vm.runInContext('JSON.stringify(segments)', p.context), before);
  assert.equal(vm.runInContext('past.length', p.context), 0);
});

test('scrubbing ignores other pointers and boundary handles, and ends on capture loss', () => {
  const p = page(true);
  vm.runInContext('wireTimelineScrub()', p.context);
  const track = p.node('timeline-content');
  track.listeners.pointerdown(p.event(800, 1, true));
  assert.equal(p.videos[0].currentTime, 2);
  track.listeners.pointerdown(p.event(100));
  track.listeners.pointermove(p.event(900, 2));
  assert.ok(Math.abs(p.videos[0].currentTime - 2.0001) < 0.00001);
  track.listeners.pointercancel(p.event(900, 2));
  track.listeners.pointermove(p.event(1200));
  assert.ok(Math.abs(p.videos[0].currentTime - 9.9001) < 0.00001);
  track.listeners.lostpointercapture(p.event(1200));
  track.listeners.pointermove(p.event(400));
  assert.ok(p.videos.every(video => Math.abs(video.currentTime - 9.9001) < 0.00001 && video.paused));
});
