// Run with linkedom available locally or via NODE_PATH; no server or AI calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {parseHTML} = require('linkedom');
const root = path.resolve(__dirname, '..');
const {document} = parseHTML(fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8'));
const context = vm.createContext({document});
vm.runInContext(fs.readFileSync(path.join(root, 'frontend/annotations.js'), 'utf8') + '\nglobalThis.review = EssayReview;', context);
const render = preview => context.review.render(preview, text => `<p>${text}</p>`);
const annotation = {paragraph:2, start:0, end:6, quote:'He go.', level:'sentence',
  kind:'error', correction:'He goes.', comment:'独立解释 <script>bad()</script>', id:'P2.1'};
const preview = {original:['First paragraph.', 'He go.'], annotations:[annotation],
  channels:{annotations:'ready', report:'running'}};
render(preview);
assert.equal(document.querySelectorAll('#panel-corrections .annotation-card').length, 1);
assert.equal(document.querySelectorAll('#panel-paragraphs .annotation-card').length, 0);
assert.equal(document.querySelector('#note-P2\\.1'), document.getElementById('note-P2.1'));
assert.equal(document.querySelector('#panel-corrections script'), null);
assert.match(document.querySelector('#panel-paragraphs').textContent, /正在生成/);
assert.equal(document.getElementById('mark-P2.1').getAttribute('href'), '#note-P2.1');

// A later report with different/no edits must never remove an independent card.
const before = document.querySelector('#panel-corrections').innerHTML;
render({...preview, channels:{annotations:'ready',report:'ready'}, review:{paragraphs:[
  {paragraph:1, marked:'First paragraph.', feedback:[{title:'段落点评',text:'内容反馈'}, {title:'语言提升',text:'不应混入段落栏'}]},
  {paragraph:2, marked:'He go.', feedback:[]}
], overall:''}});
assert.equal(document.querySelector('#panel-corrections').innerHTML, before);
assert.doesNotMatch(document.querySelector('#panel-paragraphs').textContent, /不应混入段落栏/);

// Failed paragraphs leave corrections usable, and failed corrections leave paragraphs usable.
render({...preview, channels:{annotations:'ready',report:'failed'}});
assert.equal(document.querySelector('#panel-corrections').innerHTML, before);
assert.match(document.querySelector('#panel-paragraphs').textContent, /生成失败/);
render({original:['He go.'], annotations:[], channels:{annotations:'failed',report:'ready'},
  review:{paragraphs:[{feedback:[{title:'段落点评',text:'内容仍可见'}]}],overall:''}});
assert.match(document.querySelector('#panel-corrections').textContent, /生成失败/);
assert.match(document.querySelector('#panel-paragraphs').textContent, /内容仍可见/);
assert.equal(document.querySelector('#correction-count').textContent, '0');
assert.equal(document.querySelector('#tab-paragraphs').getAttribute('aria-selected'), 'true');

// No fallback cards from Word edits, even for legacy reports without JSON.
render({original:['He go.'], review:{paragraphs:[{marked:'He ~~go~~{++goes++}.',feedback:[]}],overall:''}, channels:{annotations:'unavailable',report:'ready'}});
assert.equal(document.querySelectorAll('#panel-corrections .annotation-card').length, 0);
assert.match(document.querySelector('#panel-corrections').textContent, /历史报告/);
// Structured evaluation arrives through the same preview update, without touching annotations.
const overview = ['全文优势','关键问题','学习建议','提分路径'].map(title => ({title,text:`${title}的依据和行动。`}));
const dimensions = ['审题与内容','结构与逻辑','词汇表达','语法准确性','亮点表达'].map(title => ({title,text:`${title}的依据和行动。`}));
render({...preview, review:{paragraphs:[], overall:'本篇文章打分估计为：18–19分', evaluation:{version:2,intro:'',overview,dimensions}}});
assert.equal(document.querySelectorAll('#evaluation .evaluation-group').length, 1);
assert.equal(document.querySelectorAll('#evaluation .evaluation-dimensions').length, 0);
assert.equal(document.querySelectorAll('#evaluation .analysis-section').length, 4);
assert.equal(document.querySelectorAll('#evaluation .review-score').length, 1);
assert.equal(document.querySelector('#panel-corrections').innerHTML, before);
render({original:[],review:{paragraphs:[],overall:'旧报告的综合评语',evaluation:{version:1,intro:'旧报告的综合评语',overview:[],dimensions:[]}}});
assert.match(document.querySelector('#evaluation').textContent, /旧报告的综合评语/);
assert.equal(document.querySelectorAll('#evaluation .evaluation-dimensions').length, 0);
// All source-anchored kinds share the corrections tab; old vocabulary cards stay absent.
const combined = [
  {paragraph:1,start:0,end:5,quote:'First',kind:'good-point',level:'phrase',comment:'原文亮点',id:'P1.1'},
  {paragraph:1,start:6,end:15,quote:'paragraph',kind:'suggestion',level:'phrase',comment:'可选优化',id:'P1.2'},
  annotation,
];
render({...preview, annotations:combined, language_learning:[{paragraph:1,text:'**词块学习：First**\n中文含义：第一个\n适用场景：顺序\n局部例句：First, read.\n来源：原文已有'}]});
assert.equal(document.querySelectorAll('#panel-corrections .annotation-card').length, 3);
assert.equal(document.querySelectorAll('#panel-corrections .good-point').length, 1);
assert.equal(document.querySelectorAll('#panel-corrections .error').length, 1);
assert.equal(document.querySelectorAll('#panel-corrections .suggestion').length, 1);
assert.equal(document.querySelector('#correction-count').textContent, '3');
assert.equal(document.querySelector('#tab-vocabulary'), null);
assert.equal(document.querySelector('#panel-vocabulary'), null);
assert.equal(document.querySelectorAll('.learning-card').length, 0);
assert.equal(document.getElementById('mark-P1.1').getAttribute('href'), '#note-P1.1');
// Chinese task lines move out of the source while original anchor offsets survive.
const mixed = '🙂中文要求：写一封信。\nHe go.\n补充要求：不要署名。\nEnglish body.';
const mixedStart = Array.from(mixed.slice(0,mixed.indexOf('He go.'))).length;
const taskPreview = {prompt:'题目：介绍你的学校。', original:['题目：介绍你的学校。', mixed],
  annotations:[{...annotation,paragraph:2,start:mixedStart,end:mixedStart+6,id:'mixed-note'},
    {paragraph:1,start:0,end:2,quote:'题目',kind:'suggestion',comment:'不应批改题目',id:'task-note'}],
  review:{paragraphs:[{paragraph:1,feedback:[{title:'格式说明',text:'题目原样保留'}]},
    {paragraph:2,feedback:[{title:'段落点评',text:'正文反馈'}]}],overall:''}};
const originalSnapshot = JSON.stringify(taskPreview);
render(taskPreview);
assert.doesNotMatch(document.querySelector('#source').textContent, /\p{Script=Han}/u);
assert.match(document.querySelector('#source').textContent, /He go\./);
assert.match(document.querySelector('#source').textContent, /English body\./);
assert.equal((document.querySelector('#essay-prompt').textContent.match(/题目：介绍你的学校。/g) || []).length, 1);
assert.match(document.querySelector('#essay-prompt').textContent, /中文要求：写一封信。/);
assert.match(document.querySelector('#essay-prompt').textContent, /补充要求：不要署名。/);
assert.equal(document.getElementById('mark-mixed-note').textContent, 'He go.');
assert.equal(document.getElementById('mark-task-note'), null);
assert.equal(document.querySelector('#correction-count').textContent, '1');
assert.equal(document.querySelector('#paragraph-count').textContent, '1');
assert.equal(document.querySelector('#word-count').textContent, '4 个单词');
assert.equal(document.getElementById('source-paragraph-1'), null);
assert.equal(document.getElementById('source-paragraph-2').querySelector('p').textContent, 'He go.\nEnglish body.');
assert.equal(JSON.stringify(taskPreview), originalSnapshot);
console.log('Annotation independence and comprehensive evaluation DOM checks passed.');

// Use production Markdown rendering to verify component and total-only colors.
const appSource = fs.readFileSync(path.join(root, 'frontend/app.js'), 'utf8');
context.esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
vm.runInContext(appSource.slice(appSource.indexOf('function inline('),appSource.indexOf('function reviewReport(')),context);
const table = '| 档次 | 内容 | 语言 | 组织结构 |\n|---|---|---|---|\n| A | 9–10 | 9–10 | [[red]]4–5[[/red]] |\n| B | [[red]]7–8[[/red]] | [[red]]7–8[[/red]] | 3 |\n| C | 5–6 | 5–6 | 2 |\n| D | 3–4 | 3–4 | 1 |\n| E | 0–2 | 0–2 | 0 |';
const rubricRender = (reference,score) => context.review.render({original:[],review:{paragraphs:[],overall:`总评\n本篇文章打分估计为：${score}分\n${reference}`}},context.markdown);
rubricRender(table,'18–19');
assert.deepEqual(Array.from(document.querySelectorAll('.rubric-reference .red'),node => node.textContent),['4–5','7–8','7–8']);
assert.equal(document.querySelector('.rubric-reference th .red'),null);
const historical = table.replace(/\[\[\/?red\]\]/g,'');
rubricRender(historical,'18–19');
assert.deepEqual(Array.from(document.querySelectorAll('.rubric-reference .red'),node => node.textContent),['B']);
assert.match(document.querySelector('.rubric-reference').textContent,/未标记各分项档位/);
rubricRender(historical,'20–21');
assert.equal(document.querySelectorAll('.rubric-reference .red').length,0);
console.log('Rubric component colors and historical total-band checks passed.');

const titles = ['综合评价','Task Response｜任务回应','Coherence and Cohesion｜连贯与衔接','Lexical Resource｜词汇','Grammatical Range and Accuracy｜语法'];
const blocks = titles.map(title => ({title,analysis:`${title}：第2段的具体证据。`,suggestions:'调整对应表达，并检查原意是否保留。'}));
context.review.render({...preview,review:{paragraphs:[],context:'已融入任务回应的审题信息',overall:'本篇文章打分估计为：18–19分',evaluation:{version:3,blocks}}},context.markdown);
assert.deepEqual(Array.from(document.querySelectorAll('.analysis-section > h4'),node=>node.textContent),['Comprehensive Evaluation','Task Response｜任务回应','Coherence and Cohesion｜连贯与衔接','Lexical Resource｜词汇','Grammatical Range and Accuracy｜语法']);
assert.equal(document.querySelectorAll('.evaluation-analysis').length,5);
assert.equal(document.querySelectorAll('.evaluation-suggestions').length,5);
assert.equal(document.querySelector('.review-context'),null);
assert.equal(document.querySelectorAll('#panel-corrections .annotation-card').length,1);
assert.equal(document.querySelectorAll('.review-score').length,1);
console.log('Five evaluation blocks with independent analysis/suggestion fields passed.');

const lexicalTitles = ['词汇范围','精确度','学术风格','改进方向','举个例子'];
blocks[3].lexical_sections = lexicalTitles.map(title=>({title,text:`${title}：依据原文的具体说明。`}));
context.review.render({...preview,review:{paragraphs:[],overall:'本篇文章打分估计为：18–19分',evaluation:{version:3,blocks}}},context.markdown);
assert.deepEqual(Array.from(document.querySelectorAll('.lexical-detail h5'),node=>node.textContent),['Vocabulary Range','Precision','Academic Style','Improvement Directions','Practical Example']);
assert.equal(document.querySelectorAll('.analysis-section').length,5);
const lexicalBlock=document.querySelectorAll('.analysis-section')[3];
assert.equal(lexicalBlock.querySelectorAll('.evaluation-analysis').length,3);
assert.equal(lexicalBlock.querySelectorAll('.evaluation-suggestions').length,2);
assert.doesNotMatch(lexicalBlock.textContent,/分析点评|修改建议/);
assert.equal(document.querySelectorAll('#panel-corrections .annotation-card').length,1);
console.log('Lexical five-part display and legacy two-field compatibility passed.');

const grammarTitles = ['Sentence Variety','Advanced Structures','Error Patterns','Specific Corrections','Progressive Improvement'];
blocks[4].grammar_sections = grammarTitles.map(title=>({title,text:'依据原文说明句式或改进方法。'}));
context.review.render({...preview,review:{paragraphs:[],overall:'本篇文章打分估计为：18–19分',evaluation:{version:3,blocks}}},context.markdown);
assert.deepEqual(Array.from(document.querySelectorAll('.grammar-detail h5'),node=>node.textContent),grammarTitles);
assert.equal(document.querySelectorAll('.analysis-section').length,5);
const grammarBlock=document.querySelectorAll('.analysis-section')[4];
assert.equal(grammarBlock.querySelectorAll('.evaluation-analysis').length,3);
assert.equal(grammarBlock.querySelectorAll('.evaluation-suggestions').length,2);
assert.doesNotMatch(grammarBlock.textContent,/分析点评|修改建议/);
assert.equal(document.querySelectorAll('.lexical-detail').length,5);
assert.equal(document.querySelectorAll('#panel-corrections .annotation-card').length,1);
console.log('Grammar five-part display and lexical coexistence passed.');

const cohesionTitles = ['Paragraph Structure','Linking Devices','Logical Flow','Specific Improvements','Practical Examples'];
blocks[2].cohesion_sections = cohesionTitles.map(title=>({title,text:'依据原文说明段落、衔接和逻辑。'}));
context.review.render({...preview,review:{paragraphs:[],overall:'本篇文章打分估计为：18–19分',evaluation:{version:3,blocks}}},context.markdown);
assert.deepEqual(Array.from(document.querySelectorAll('.cohesion-detail h5'),node=>node.textContent),cohesionTitles);
assert.equal(document.querySelectorAll('.analysis-section').length,5);
const cohesionBlock=document.querySelectorAll('.analysis-section')[2];
assert.equal(cohesionBlock.querySelectorAll('.evaluation-analysis').length,3);
assert.equal(cohesionBlock.querySelectorAll('.evaluation-suggestions').length,2);
assert.doesNotMatch(cohesionBlock.textContent,/分析点评|修改建议/);
assert.equal(document.querySelectorAll('.lexical-detail').length,5);
assert.equal(document.querySelectorAll('.grammar-detail').length,5);
assert.equal(document.querySelectorAll('#panel-corrections .annotation-card').length,1);
console.log('Cohesion five-part display and all three detailed dimensions passed.');

const taskTitles = ['Position and Argument Analysis','Evidence and Examples Assessment','Content and Structure Optimization Suggestions','Improvement Suggestions'];
blocks[1].task_sections = taskTitles.map(title=>({title,text:'依据真实题目和原文说明任务完成与改进。'}));
context.review.render({...preview,review:{paragraphs:[],overall:'本篇文章打分估计为：18–19分',evaluation:{version:3,blocks}}},context.markdown);
assert.deepEqual(Array.from(document.querySelectorAll('.task-detail h5'),node=>node.textContent),taskTitles);
assert.equal(document.querySelectorAll('.analysis-section').length,5);
const taskBlock=document.querySelectorAll('.analysis-section')[1];
assert.equal(taskBlock.querySelectorAll('.evaluation-analysis').length,2);
assert.equal(taskBlock.querySelectorAll('.evaluation-suggestions').length,2);
assert.doesNotMatch(taskBlock.textContent,/分析点评|修改建议/);
for (const type of ['cohesion','lexical','grammar']) assert.equal(document.querySelectorAll(`.${type}-detail`).length,5);
assert.equal(document.querySelectorAll('#panel-corrections .annotation-card').length,1);
console.log('Task Response four-part display and all detailed dimensions passed.');

const comprehensiveTitles = ['Strengths','Improvement Suggestions','Enhancement Path','Action Plan'];
blocks[0].comprehensive_sections = comprehensiveTitles.map(title=>({title,text:'依据原文说明优势、优先修改和行动步骤。'}));
context.review.render({...preview,review:{paragraphs:[],overall:'本篇文章打分估计为：18–19分',evaluation:{version:3,blocks}}},context.markdown);
assert.deepEqual(Array.from(document.querySelectorAll('.comprehensive-detail h5'),node=>node.textContent),comprehensiveTitles);
assert.equal(document.querySelectorAll('.analysis-section').length,5);
const comprehensiveBlock=document.querySelectorAll('.analysis-section')[0];
assert.equal(comprehensiveBlock.querySelectorAll('.evaluation-analysis').length,1);
assert.equal(comprehensiveBlock.querySelectorAll('.evaluation-suggestions').length,3);
assert.doesNotMatch(comprehensiveBlock.textContent,/分析点评|修改建议/);
assert.equal(document.querySelectorAll('.task-detail').length,4);
for (const type of ['cohesion','lexical','grammar']) assert.equal(document.querySelectorAll(`.${type}-detail`).length,5);
assert.equal(document.querySelectorAll('#panel-corrections .annotation-card').length,1);
console.log('Comprehensive Evaluation four-part display and all five blocks passed.');

const englishReview={...preview,annotations:[{...annotation,comment:'Use the base form with a plural subject.'}],review:{paragraphs:[],overall:'',evaluation:{version:3,blocks}}};
context.review.render(englishReview,context.markdown);
assert.equal(document.querySelector('.kind-tag').textContent,'Error');
assert.equal(document.querySelector('.comprehensive-detail h5').textContent,'Strengths');
assert.equal(document.querySelector('#download').textContent,'↓ 下载完整 Word 报告');
assert.match(document.querySelector('#word-count').textContent,/个单词/);
assert.equal(document.querySelector('#review-language-toggle'),null);
assert.equal(document.querySelectorAll('.annotation-card [data-translate-scope="annotation"]').length,1);
assert.equal(document.querySelectorAll('.analysis-section [data-translate-scope="evaluation"]').length,5);
assert.equal(document.querySelectorAll('[data-translate-scope]').length,6);
assert.equal(document.querySelector('.feedback-translate').textContent,'点击翻译');
assert.equal(document.querySelector('#panel-corrections .error .correction'),null);
console.log('Chinese interface, English feedback and independent card/evaluation translation buttons passed.');
