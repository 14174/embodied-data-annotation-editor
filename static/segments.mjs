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
