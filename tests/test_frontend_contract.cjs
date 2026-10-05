const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const {document}=parseHTML(fs.readFileSync('static/index.html','utf8'));
const context=vm.createContext({document});
vm.runInContext(fs.readFileSync('static/annotations.js','utf8')+'\nglobalThis.review=EssayReview;',context);
vm.runInContext(fs.readFileSync('static/review-language.js','utf8')+'\nglobalThis.language=ReviewLanguage;',context);
const preview=JSON.parse(fs.readFileSync('output/frontend-contract-preview.json','utf8'));
const snapshot=JSON.stringify(preview),render=p=>context.review.render(p,t=>'<p>'+t+'</p>');
(async()=>{
  await context.language.show('contract',preview,render,()=>{throw Error('No translation request permitted');});
  assert.match(document.querySelector('#essay-prompt').textContent,/介绍学校活动/);
  assert.doesNotMatch(document.querySelector('#source').textContent,/题目/);
  assert.equal(document.querySelectorAll('.annotation-card').length,1);
  assert.equal(document.querySelectorAll('#panel-paragraphs .paragraph-review').length,2);
  assert.equal(document.querySelectorAll('#evaluation .analysis-section').length,5);
  assert.deepEqual(Array.from(document.querySelectorAll('#evaluation .analysis-section'),s=>s.querySelectorAll('h5').length),[4,4,5,5,5]);
  assert.equal(document.querySelectorAll('#evaluation .review-score').length,1);
  assert.equal(document.querySelectorAll('#evaluation .rubric-reference').length,1);
  assert.doesNotMatch(document.querySelector('#panel-paragraphs').textContent,/语言提升/);
  for(const block of preview.review.evaluation.blocks) {
    context.language.toggle('evaluation',block.title);
    assert.match(document.querySelector('#evaluation').textContent,/中文点评/);
    context.language.toggle('evaluation',block.title);
  }
  context.language.toggle('annotation',preview.annotations[0].id);
  assert.match(document.querySelector('.annotation-card').textContent,/中文点评/);
  context.language.toggle('paragraph','2');
  assert.match(document.querySelector('#paragraph-2').textContent,/中文点评/);
  assert.equal(JSON.stringify(preview),snapshot);
  const letter = structuredClone(preview);
  letter.annotations = [];
  letter.original = ['Dear Student Union,', 'I am writing to suggest a school activity.', 'We could invite an expert to explain how to manage stress.', 'I hope you will consider my suggestion.', 'Yours sincerely,', 'Li Hua'];
  // Historical models may have written full content feedback for formatting lines.
  letter.review.paragraphs = letter.original.map((text,i) => ({paragraph:i+1, feedback:[{title:'段落点评',text:'Comment on '+text},{title:'问题建议',text:'A practical suggestion.'}]}));
  render(letter);
  assert.equal(document.querySelector('#paragraph-count').textContent,'3');
  assert.deepEqual(Array.from(document.querySelectorAll('.paragraph-review'),s=>s.id),['paragraph-2','paragraph-3','paragraph-4']);
  assert.match(document.querySelector('#source').textContent,/Dear Student Union/);
  assert.match(document.querySelector('#source').textContent,/Li Hua/);
  assert.ok(document.querySelector('#source-paragraph-4'));
  letter.original[4] = 'Best regards,\nLi Hua';
  letter.original.pop();
  letter.review.paragraphs.pop();
  render(letter);
  assert.equal(document.querySelector('#paragraph-count').textContent,'3');
  // A short substantive conclusion is still a content paragraph.
  letter.original[3] = 'Please consider this proposal.';
  render(letter);
  assert.ok(document.querySelector('#paragraph-4'));
  letter.review.paragraphs[0].feedback = [{title:'格式说明',text:'Keep the salutation.'}];
  render(letter);
  assert.doesNotMatch(document.querySelector('#panel-paragraphs').textContent,/格式说明/);
  console.log('Actual preview renders all three columns, 23 detail sections, scores and local translation.');
  console.log('Letter formatting is excluded from paragraph reviews while short content conclusions and source anchors remain.');
})().catch(error=>{console.error(error);process.exitCode=1;});
