const EssayLearning = (() => {
  const panel = document.getElementById('panel-learning');
  let preview = {}, language = 'en', sourceKey = '';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const text = (en, zh) => language === 'zh' ? zh : en;
  const pair = (en, zh) => `<p class="learning-english">${escape(en)}</p>${language === 'zh' && zh ? `<p class="learning-chinese">${escape(zh)}</p>` : ''}`;
  const block = (label, html) => `<div class="learning-block"><h5>${escape(label)}</h5>${html}</div>`;
  const list = (words, meanings = []) => `<ul class="learning-phrases">${words.map((word, index) => `<li>${pair(word, meanings[index])}</li>`).join('')}</ul>`;
  function markedSentence(item) {
    const sentence = item.source_sentence || '', word = item.original || '';
    if (!word) return escape(sentence);
    const pattern = new RegExp('(?<!\\w)' + word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?!\\w)', 'g');
    const match = Array.from(sentence.matchAll(pattern))[(item.word_occurrence || 1) - 1];
    if (!match) return escape(sentence);
    const start = match.index, from = start + word.length;
    return escape(sentence.slice(0, start)) + `<mark>${escape(word)}</mark>` + escape(sentence.slice(from));
  }
  function draw() {
    if (!panel) return;
    const upgrades = preview.high_score_vocabulary || [], synonyms = preview.synonym_expansions || [];
    const topic = preview.topic_collocations, phrases = topic?.items || [];
    const count = upgrades.length + synonyms.length + phrases.length;
    document.getElementById('learning-count').textContent = count;
    const state = preview.channels?.learning;
    const empty = text(state === 'running' ? 'Vocabulary learning is being prepared.' : state === 'failed' ? 'Vocabulary learning is temporarily unavailable.' : 'No vocabulary learning content is available for this essay.', state === 'running' ? '词汇积累正在生成。' : state === 'failed' ? '词汇积累暂时不可用。' : '本篇作文暂无词汇积累内容。');
    const section = (title, subtitle, cards) => `<section class="learning-section"><header><h3>${title}</h3><p>${subtitle}</p></header>${cards || `<p class="learning-empty">${text('No suitable expressions identified.', '暂无适合积累的表达。')}</p>`}</section>`;
    panel.innerHTML = `<div class="learning-toolbar"><h2>${text('Vocabulary Learning', '词汇积累')}</h2><div class="learning-languages" role="group" aria-label="词汇显示语言"><button type="button" data-learning-language="en" aria-pressed="${language === 'en'}">English</button><button type="button" data-learning-language="zh" aria-pressed="${language === 'zh'}">中文</button></div></div>${count ? '' : `<p class="learning-empty" role="status">${empty}</p>`}`
      + section(text('High-score Vocabulary', '高分词'), text('Choose more precise expressions and learn why they work.', '找到更精准的表达，理解为什么更合适。'), upgrades.map(item => `<article class="learning-card"><h4><del>${escape(item.original)}</del><span aria-hidden="true"> → </span><strong>${escape(item.replacement)}</strong></h4>${language === 'zh' ? `<p class="learning-chinese">${escape(item.original_zh)} → ${escape(item.replacement_zh)}</p>` : ''}${block(text('Original sentence', '原文句子'), `<p class="learning-english">${markedSentence(item)}</p>${language === 'zh' && item.source_sentence_zh ? `<p class="learning-chinese">${escape(item.source_sentence_zh)}</p>` : ''}`)}${block(text('Replace this expression', '仅替换目标词'), pair(item.minimal_sentence, item.minimal_sentence_zh))}${block(text('New example', '新词例句'), pair(item.example_sentence, item.example_sentence_zh))}${block(text('Why it fits', '替换原因'), `<p>${escape(language === 'zh' && item.reason_zh ? item.reason_zh : item.reason)}</p>`)}${block(text('Useful collocations', '常用搭配'), list(item.collocations || [], item.collocations_zh))}</article>`).join(''))
      + section(text('Synonym Expansion', '近义词'), text('Build several natural ways to express the same idea.', '一个原文表达，积累多种自然表达方式。'), synonyms.map(item => `<article class="learning-card"><h4>${escape(item.original)}</h4><p class="learning-meaning"><span>${escape(item.part_of_speech)}</span> ${escape(language === 'zh' ? item.meaning_zh : item.meaning_en || item.original)}</p>${block(text('Alternative expressions', '近义表达'), list(item.synonyms || [], item.synonyms_zh))}</article>`).join(''))
      + section(text('Topic Collocations', '话题词伙'), topic ? escape(text(topic.topic, topic.topic_zh || topic.topic)) : text('Reusable phrases for this writing topic.', '积累同类作文中可以复用的完整表达。'), phrases.map(item => `<article class="learning-card"><h4>${escape(item.phrase)}</h4>${language === 'zh' && item.phrase_zh ? `<p class="learning-chinese">${escape(item.phrase_zh)}</p>` : ''}${block(text('Example sentence', '示例句'), pair(item.example_sentence, item.example_sentence_zh))}</article>`).join(''));
  }
  panel?.addEventListener('click', event => {
    const button = event.target.closest('[data-learning-language]');
    if (!button) return;
    language = button.dataset.learningLanguage;
    draw();
    panel.querySelector(`[data-learning-language="${language}"]`)?.focus();
  });
  return {render(value) {
    const key = JSON.stringify(value.original || []);
    if (key !== sourceKey) language = 'en';
    sourceKey = key;
    preview = value;
    draw();
  }};
})();
