export function splitAt(segments, frame) {
  frame = Math.round(frame);
  const i = segments.findIndex(s => s.start_frame < frame && frame < s.end_frame);
  if (i < 0) return segments;
  const s = segments[i];
  return [...segments.slice(0,i), {...s,end_frame:frame}, {...s,start_frame:frame}, ...segments.slice(i+1)];
}
export function moveBoundary(segments, index, frame) {
  if (index <= 0 || index >= segments.length) return segments;
  const result = segments.map(s => ({...s}));
  frame = Math.max(result[index-1].start_frame+1, Math.min(result[index].end_frame-1,Math.round(frame)));
  result[index-1].end_frame=frame;
  result[index].start_frame=frame;
  return result;
}
export function mergeAt(segments,index) {
  if (index<=0 || index>=segments.length) return segments;
  const a=segments[index-1],b=segments[index];
  const caption=[...new Set([a.caption,b.caption].filter(Boolean))].join('\n');
  return [...segments.slice(0,index-1),{...a,end_frame:b.end_frame,caption,category:a.category===b.category?a.category:''},...segments.slice(index+1)];
}
export function mergeSelected(segments, indices) {
  const selected = [...new Set(indices)].sort((a,b) => a-b);
  if (selected.length < 2 || selected.some((index,i) => !Number.isInteger(index) ||
      index < 0 || index >= segments.length || (i && index !== selected[i-1]+1))) return segments;
  const first = selected[0], last = selected[selected.length-1];
  const group = segments.slice(first,last+1);
  if (group.some((segment,i) => i && group[i-1].end_frame !== segment.start_frame)) return segments;
  const caption = [...new Set(group.map(s => s.caption).filter(Boolean))].join('\n');
  const category = group.every(s => s.category === group[0].category) ? group[0].category : '';
  return [...segments.slice(0,first), {...group[0],end_frame:group[group.length-1].end_frame,caption,category},
    ...segments.slice(last+1)];
}
