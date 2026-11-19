/** Validate an editable caption vocabulary without altering its English labels. */
export function validateVocabulary(value) {
  const text = x => typeof x === 'string' && x.trim().length > 0;
  if (!value || !text(value.id) || !text(value.name) || !text(value.version) ||
      !Array.isArray(value.items) || !value.items.length) {
    throw Error('词表需要 id、name、version 和非空 items 数组');
  }
  const ids = new Set(), captions = new Set();
  const items = value.items.map(item => {
    if (!item || !text(item.id) || !text(item.caption) ||
        (item.label_zh !== undefined && typeof item.label_zh !== 'string')) {
      throw Error('每项需要 id、caption，label_zh 可选且应为文本');
    }
    if (ids.has(item.id) || captions.has(item.caption)) throw Error('词条 id 和 caption 不能重复');
    ids.add(item.id); captions.add(item.caption);
    return {id:item.id, caption:item.caption, label_zh:item.label_zh || ''};
  });
  return {id:value.id, name:value.name, version:value.version, items};
}
