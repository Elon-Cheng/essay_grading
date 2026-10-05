// Render a replayed real report through the actual frontend code.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {parseHTML} = require('linkedom');
const preview = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const {document} = parseHTML(fs.readFileSync('frontend/index.html', 'utf8'));
const context = vm.createContext({document});
vm.runInContext(fs.readFileSync('frontend/annotations.js', 'utf8') + '\nglobalThis.review=EssayReview;', context);
const snapshot = JSON.stringify(preview);
const escape = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
context.review.render(preview, text => '<p>' + escape(text) + '</p>');
assert.equal(document.querySelectorAll('.annotation-card').length, preview.annotations.length);
assert.equal(document.querySelectorAll('.paragraph-review').length,
  preview.review.paragraphs.filter(p => p.feedback.some(f => f.title === '段落点评')).length);
assert.equal(document.querySelectorAll('#evaluation .analysis-section').length, 5);
assert.deepEqual(Array.from(document.querySelectorAll('#evaluation .analysis-section'),
  section => section.querySelectorAll('h5').length), [4,4,5,5,5]);
assert.equal(document.querySelectorAll('#evaluation .review-score').length, 1);
assert.equal(document.querySelectorAll('#evaluation .rubric-reference').length, 1);
assert.equal(JSON.stringify(preview), snapshot);
console.log('Saved failed sample now renders annotations, paragraph feedback, all 23 evaluation fields, score and rubric.');
