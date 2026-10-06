/* Render only escaped, source-anchored annotations; model HTML is never used. */
'use strict';
const EssayReview = (() => {
  const lexicalLabels = {'词汇范围':'Vocabulary Range','精确度':'Precision','学术风格':'Academic Style','改进方向':'Improvement Directions','举个例子':'Practical Example'};
  function translateButton(scope,key) {
    return `<button type="button" class="feedback-translate" data-translate-scope="${escape(scope)}" data-translate-key="${escape(key)}" aria-pressed="false">点击翻译</button>`;
  }
  const names = {'good-point':'Good Point', suggestion:'Suggestion', error:'Error'};
  const levels = {phrase:'短语层', sentence:'句子层'};
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function sourcePresentation(preview) {
    const prompt = preview.prompt || '';
    const taskLines = new Set(prompt.split(/\r?\n/).map(line => line.trim()).filter(Boolean));
    const moved = [], rows = new Map();
    (preview.original || []).forEach((text, i) => {
      const ranges = [], visible = [];
      let offset = 0;
      // Keep offsets in the unchanged source, including supplementary characters.
      for (const line of text.match(/[^\n]*\n|[^\n]+$/g) || []) {
        const end = offset + Array.from(line).length;
        const trimmed = line.trim();
        if (/\p{Script=Han}/u.test(line) || (trimmed && taskLines.has(trimmed))) {
          if (trimmed && !taskLines.has(trimmed)) {
            moved.push(trimmed);
            taskLines.add(trimmed);
          }
        } else {
          visible.push(line);
          const previous = ranges[ranges.length - 1];
          if (previous && previous.end === offset) previous.end = end;
          else ranges.push({start:offset, end});
        }
        offset = end;
      }
      if (visible.join('').trim()) rows.set(i + 1, {text, visible:visible.join(''), ranges});
    });
    return {rows, prompt:[prompt.trim(), moved.join('\n')].filter(Boolean).join('\n\n')};
  }
  function formatParagraphs(rows) {
    const excluded = new Set();
    const entries = Array.from(rows, ([number, row]) => [number, row.visible.trim()]);
    const salutation = /^(?:Dear\s+[^.!?\n]{1,100}|Hi(?:\s+[^.!?\n]{1,60})?|Hello(?:\s+[^.!?\n]{1,60})?)[,:!]?$/i;
    const signoff = /^(?:Yours(?:\s+(?:sincerely|faithfully|truly))?|Sincerely(?:\s+yours)?|Faithfully\s+yours|(?:Best|Kind|Warm)\s+regards|Regards|Best\s+wishes|With\s+best\s+wishes)[,.!]?$/i;
    const name = /^[A-Za-z][A-Za-z'’-]*(?:\s+[A-Za-z][A-Za-z'’-]*){0,3}[,.]?$/;
    if (entries.length && salutation.test(entries[0][1])) excluded.add(entries[0][0]);
    // Only standalone closing formulas and their following signature; never a word-count cutoff.
    let signature = false;
    for (let i = entries.length - 1; i >= 0; i--) {
      const [number, text] = entries[i], lines = text.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
      if (lines.length && signoff.test(lines[0]) && lines.slice(1).every(s => name.test(s))) {
        excluded.add(number);
        for (let j = i + 1; j < entries.length; j++) {
          if (name.test(entries[j][1])) excluded.add(entries[j][0]);
          else break;
        }
        signature = true;
        break;
      }
    }
    if (!signature && entries.length && /^Li\s+Hua[,.]?$/i.test(entries[entries.length - 1][1])) excluded.add(entries[entries.length - 1][0]);
    return excluded;
  }
  function evaluationBlock(block, markdown) {
    const type = block.title === '综合评价' ? 'comprehensive' : block.title === 'Task Response｜任务回应' ? 'task' : block.title === 'Coherence and Cohesion｜连贯与衔接' ? 'cohesion' : block.title === 'Lexical Resource｜词汇' ? 'lexical' : block.title === 'Grammatical Range and Accuracy｜语法' ? 'grammar' : '';
    const details = type ? block[`${type}_sections`] : null;
    const splitAt = type === 'comprehensive' ? 1 : type === 'task' ? 2 : 3;
    const content = details?.length === (['comprehensive','task'].includes(type) ? 4 : 5)
      ? details.map((item,i) => `<section class="${type}-detail ${i < splitAt ? 'evaluation-analysis' : 'evaluation-suggestions'}"><h5>${escape(lexicalLabels[item.title] || item.title)}</h5>${markdown(item.text)}</section>`).join('')
      : `<section class="evaluation-analysis"><h5>分析点评</h5>${markdown(block.analysis)}</section><section class="evaluation-suggestions"><h5>修改建议</h5>${markdown(block.suggestions)}</section>`;
    return `<section class="analysis-section"><h4>${escape(block.title === '综合评价' ? 'Comprehensive Evaluation' : block.title)}</h4>${translateButton('evaluation',block.title)}${content}</section>`;
  }
  function analysis(text, markdown, evaluation) {
    if (evaluation?.version === 3) {
      return `<section class="evaluation-group" aria-label="综合评价与四个写作维度">${evaluation.blocks.map(block => evaluationBlock(block,markdown)).join('')}</section>`;
    }
    if (evaluation?.version === 2) {
      const sections = entries => entries.map(entry => `<section class="analysis-section${['学习建议','提分路径'].includes(entry.title) ? ' training-priority' : ''}"><h4>${escape(entry.title)}</h4>${markdown(entry.text)}</section>`).join('');
      return `${evaluation.intro ? markdown(evaluation.intro) : ''}<section class="evaluation-group" aria-label="综合总评"><h3>综合总评</h3>${sections(evaluation.overview)}</section>`;
    }
    // Explicit model headings only: do not guess the meaning of older prose.
    const parts = text.split(/^\*\*(全文优势|关键问题|下篇优先训练|学习建议|提分路径|审题与内容|结构与逻辑|词汇表达|语法准确性|亮点表达)[：:]?\*\*[ \t]*\r?$/m);
    if (parts.length === 1) return `<section class="analysis-section"><h4>全文评价与提升建议</h4>${markdown(text)}</section>`;
    let output = parts[0].trim() ? markdown(parts[0]) : '';
    for (let i = 1; i < parts.length; i += 2) {
      if (['审题与内容','结构与逻辑','词汇表达','语法准确性','亮点表达'].includes(parts[i])) continue;
      output += `<section class="analysis-section${parts[i] === '下篇优先训练' ? ' training-priority' : ''}"><h4>${escape(parts[i])}</h4>${markdown(parts[i+1] || '')}</section>`;
    }
    return output;
  }
  function rubricReference(text, markdown, score) {
    const container = document.createElement('div');
    container.innerHTML = markdown(text);
    // Historical reports may have only a total score, without per-component bands.
    if (!text.includes('[[red]]') && score) {
      const match = score.match(/^(\d+(?:\.\d+)?)(?:\s*[–—－~～-]\s*(\d+(?:\.\d+)?))?\s*$/);
      if (match) {
        const low = Number(match[1]), high = Number(match[2] || match[1]);
        const bands = [['A',21,25],['B',16,20],['C',11,15],['D',6,10],['E',0,5]];
        const band = bands.find(([,min,max]) => low >= min && high <= max && low <= high);
        if (band) {
          for (const row of container.querySelectorAll('tr')) {
            const cell = row.querySelector('td');
            if (cell?.textContent.trim() === band[0]) {
              cell.innerHTML = `<span class="red" title="按本篇总分定位的参考档位">${band[0]}</span>`;
            }
          }
          const note = document.createElement('p');
          note.textContent = '红色档名按本篇总分定位；此报告未标记各分项档位。';
          container.appendChild(note);
        }
      }
    }
    return container.innerHTML;
  }
  function render(preview, markdown) {
    const activeTab = document.querySelector('[data-review-tab][aria-selected="true"]')?.dataset.reviewTab || 'corrections';
    const review = preview.review || {paragraphs:[], overall:''};
    const originals = preview.original || [];
    const presentation = sourcePresentation(preview);
    const items = (Array.isArray(preview.annotations) ? preview.annotations : []).filter(a => {
      const row = presentation.rows.get(a.paragraph);
      return row && names[a.kind] && Number.isInteger(a.start) && Number.isInteger(a.end) && a.start < a.end &&
        row.ranges.some(range => a.start >= range.start && a.end <= range.end) &&
        Array.from(row.text).slice(a.start,a.end).join('') === a.quote;
    });
    const states = preview.channels || {};
    const emptyMessage = (state, label) => state === 'failed' ? `${label}生成失败，其他已完成反馈仍可查看。` : ['pending','running'].includes(state) ? `正在生成${label}…` : state === 'unavailable' ? `此历史报告未保存独立${label}。` : `本篇没有需要单独标注的${label}。`;
    document.querySelector('#essay-prompt').textContent = presentation.prompt || '原文档未提供独立题目；内容评分以现有信息暂定。';
    document.querySelector('#source').innerHTML = Array.from(presentation.rows, ([number, row]) => {
      const chars = Array.from(row.text), annotations = items.filter(a => a.paragraph === number).sort((a,b) => a.start - b.start);
      const visibleSlice = (start, end) => row.ranges.map(range => {
        const from = Math.max(start,range.start), to = Math.min(end,range.end);
        return from < to ? chars.slice(from,to).join('') : '';
      }).join('');
      let output = '', cursor = 0;
      annotations.forEach(a => {
        if (!names[a.kind] || a.start < cursor || a.end > chars.length || chars.slice(a.start,a.end).join('') !== a.quote) return;
        output += escape(visibleSlice(cursor,a.start));
        output += `<a class="word-mark ${a.kind}${a.quote ? '' : ' insertion-marker'}" data-level="${escape(a.level || 'legacy')}" id="mark-${escape(a.id)}" href="#note-${escape(a.id)}" aria-label="${escape(names[a.kind] + '：' + (a.quote || '此处补充'))}" title="${escape((levels[a.level] || '原有批注') + ' · ' + names[a.kind] + '：' + a.comment)}">${escape(a.quote)}</a>`;
        cursor = a.end;
      });
      output += escape(visibleSlice(cursor,chars.length));
      return `<section class="original-paragraph" id="source-paragraph-${number}" tabindex="-1"><p>${output}</p></section>`;
    }).join('');
    const fullText = Array.from(presentation.rows.values(), row => row.visible).join('\n');
    document.querySelector('#word-count').textContent = `${(fullText.match(/[A-Za-z]+(?:['’-][A-Za-z]+)*/g) || []).length} 个单词`;
    document.querySelector('#sentence-count').textContent = `${(fullText.match(/[^.!?\n]+[.!?]+|[^.!?\n]+$/gm) || []).filter(s => /[A-Za-z]/.test(s)).length} 个句子`;
    const formatOnly = formatParagraphs(presentation.rows);
    const paragraphs = review.paragraphs.map((part,i) => ({...part, paragraph:part.paragraph || i+1}))
      .filter(part => (!originals.length || presentation.rows.has(part.paragraph)) && !formatOnly.has(part.paragraph))
      .filter(part => (part.feedback || []).some(f => ['段落点评','问题建议'].includes(f.title) && f.text.trim()));
    document.querySelector('#panel-paragraphs').innerHTML = paragraphs.map(part => {
      const number = part.paragraph;
      const feedback = (part.feedback || []).filter(f => ['段落点评','问题建议'].includes(f.title) && f.text.trim());
      return `<section class="paragraph-review" id="paragraph-${number}" tabindex="-1"><header class="paragraph-heading"><span class="paragraph-number">${String(number).padStart(2,'0')}</span><h3>第 ${number} 段</h3>${translateButton('paragraph',String(number))}</header><div class="teacher-feedback">${feedback.map(f => `<section class="feedback-section"><h4>${escape(f.title === '段落点评' ? '段落任务与内容逻辑' : f.title === '问题建议' ? '展开方法与训练建议' : f.title)}</h4>${markdown(f.text)}</section>`).join('')}</div></section>`;
    }).join('') || `<p>${emptyMessage(states.report, '段落点评')}</p>`;
    const corrections = document.querySelector('#panel-corrections');
    const card = a => `<section class="annotation-card ${a.kind}" data-level="${escape(a.level || 'legacy')}" id="note-${escape(a.id)}" tabindex="-1"><header><span class="kind-tag">${escape(names[a.kind])}</span><span class="level-tag">${escape(levels[a.level] || '原有批注')}</span><span class="level-tag">第 ${a.paragraph} 段</span>${translateButton('annotation',a.id)}<a href="#mark-${escape(a.id)}" class="quote-link">${escape(a.quote || '此处补充')} ↗</a></header><p>${escape(a.comment)}</p>${a.kind !== 'error' && a.correction ? `<div class="correction"><span>可改为</span> ${escape(a.correction)}</div>` : ''}</section>`;
    corrections.innerHTML = items.filter(a => names[a.kind]).map(card).join('');
    const correctionCount = corrections.children.length;
    document.querySelector('#correction-count').textContent = correctionCount;
    document.querySelector('#paragraph-count').textContent = paragraphs.length;
    if (!correctionCount) corrections.innerHTML = `<div class="tab-empty">${emptyMessage(states.annotations, '词句批改')}</div>`;
    if (typeof EssayLearning !== 'undefined') EssayLearning.render(preview);
    selectTab(activeTab === 'corrections' && !correctionCount && paragraphs.length ? 'paragraphs' : activeTab);
    let summary = review.overall || '';
    const score = summary.match(/^本篇文章打分估计为[：:]\s*(.+?)分[。.]?\s*$/m);
    if (score) summary = summary.replace(score[0], '');
    const reference = summary.match(/^\|[^\n]*档次[^\n]*\|[ \t]*\r?\n(?:[ \t]*\|[^\n]*\|[ \t]*(?:\r?\n|$))+/m);
    if (reference) summary = summary.replace(reference[0], '');
    document.querySelector('#evaluation').innerHTML = `<section class="review-summary">${score ? `<div class="review-score"><span class="score-label">本篇评分估计</span><strong>${escape(score[1])}</strong><span>/ 25 分</span></div>` : ''}${review.context && review.evaluation?.version !== 3 ? `<section class="review-context"><h4>审题情况</h4>${markdown(review.context)}</section>` : ''}${analysis(summary || emptyMessage(states.report, '综合评价'),markdown,review.evaluation)}${reference ? `<details class="rubric-reference"><summary>A–E 分档参考</summary>${rubricReference(reference[0],markdown,score?.[1])}</details>` : ''}</section>`;
    if (review.evaluation?.version !== 3 && summary.trim()) document.querySelector('#evaluation .review-summary').insertAdjacentHTML('afterbegin',translateButton('evaluation','legacy'));
  }
  function selectTab(name, focus = false) {
    document.querySelectorAll('[data-review-tab]').forEach(tab => {
      const active = tab.dataset.reviewTab === name;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      document.getElementById(tab.getAttribute('aria-controls')).hidden = !active;
      if (active && focus) tab.focus();
    });
  }
  document.querySelectorAll('[data-review-tab]').forEach((tab, index, tabs) => {
    tab.addEventListener('click', () => selectTab(tab.dataset.reviewTab));
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next === undefined) return;
      event.preventDefault();
      selectTab(tabs[next].dataset.reviewTab, true);
    });
  });
  for (const [buttonId, panelId] of [['connective-toggle', 'connective-help'], ['prompt-toggle', 'writing-prompt']]) {
    document.getElementById(buttonId).addEventListener('click', event => {
      const panel = document.getElementById(panelId);
      panel.hidden = !panel.hidden;
      event.currentTarget.setAttribute('aria-expanded', String(!panel.hidden));
    });
  }
  document.addEventListener('click', event => {
    const link = event.target.closest('.word-mark, .quote-link');
    if (!link) return;
    const target = document.getElementById(link.getAttribute('href').slice(1));
    if (!target) return;
    event.preventDefault();
    const panel = target.closest('[role="tabpanel"]');
    if (panel) selectTab(panel.id.replace('panel-', ''));
    document.querySelectorAll('.annotation-selected').forEach(el => el.classList.remove('annotation-selected'));
    target.classList.add('annotation-selected');
    target.scrollIntoView({behavior:'smooth',block:'center'});
    target.focus({preventScroll:true});
  });
  return {render};
})();
