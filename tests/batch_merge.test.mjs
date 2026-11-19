import assert from 'node:assert/strict';
import * as segments from '../static/segments.mjs';
assert.equal(typeof segments.mergeSelected, 'function', 'Continuous batch merge must be implemented');
const original = [
  {start_frame:0,end_frame:10,caption:'Pick up',category:'grasp'},
  {start_frame:10,end_frame:20,caption:'Place',category:'place'},
  {start_frame:20,end_frame:30,caption:'Place',category:'place'},
  {start_frame:30,end_frame:40,caption:'Return',category:'move'},
];
const merged=segments.mergeSelected(original,[2,0,1]);
assert.deepEqual(merged,[
  {start_frame:0,end_frame:30,caption:'Pick up\nPlace',category:''},
  {start_frame:30,end_frame:40,caption:'Return',category:'move'},
]);
assert.equal(original.length,4);
assert.equal(original[0].end_frame,10,'Undo snapshot must remain intact');
assert.equal(segments.mergeSelected(original,[0,2]),original,'Disjoint selection must not erase intermediate segments');
assert.equal(segments.mergeSelected(original,[1]),original);
assert.equal(segments.mergeSelected(original,[-1,0]),original);
assert.equal(segments.mergeSelected(original,[2,4]),original);
assert.equal(segments.mergeSelected(original,[0,.5]),original);
assert.equal(segments.mergeSelected(original,[0,0]),original);
assert.equal(segments.mergeSelected(original,[]),original);
assert.equal(segments.mergeSelected(original,[1,2])[1].category,'place');
assert.equal(segments.mergeSelected([{start_frame:0,end_frame:5,caption:'a'},
  {start_frame:6,end_frame:10,caption:'b'}],[0,1]).length,2,'Do not silently bridge gaps');
console.log('PASS: batch merge, chronological captions, deduplication, categories, invalid/disjoint selection, immutability');
