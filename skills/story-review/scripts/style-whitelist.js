'use strict';

const fs = require('fs');
const path = require('path');

// Book-local only: never inherit an unrelated workspace or another book's choices.
function loadStyleWhitelist(file) {
  const parent = path.dirname(path.resolve(file));
  const book = path.basename(parent) === '正文' ? path.dirname(parent) : parent;
  try {
    return fs.readFileSync(path.join(book, '.deslop-whitelist'), 'utf8')
      .split(/\r?\n/).map(line => line.trim())
      .filter(line => line && !line.startsWith('#'))
      .sort((a, b) => b.length - a.length);
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }
}

function styleSpans(text, whitelist) {
  const spans = [];
  for (const literal of whitelist) {
    for (let at = text.indexOf(literal); at !== -1; at = text.indexOf(literal, at + 1)) {
      spans.push([at, at + literal.length]);
    }
  }
  return spans;
}

function maskStyleText(text, whitelist) {
  const chars = text.split('');
  for (const [start, end] of styleSpans(text, whitelist)) {
    chars.fill('？', start, end);
  }
  return chars.join('');
}

module.exports = { loadStyleWhitelist, styleSpans, maskStyleText };
