"use strict";
const ReviewLanguage = (() => {
  let jobId=null, base=null, renderer=null, request=null, revision=0, epoch=0;
  const choices=new Map();
  const clone=value=>JSON.parse(JSON.stringify(value));
  const status=()=>document.getElementById('review-language-status');
  function fragment(preview,scope,key) {
    if(scope==='annotation') return preview.annotations?.find(a=>a.id===key);
    if(scope==='paragraph') return preview.review?.paragraphs?.find(p=>String(p.paragraph)===key);
    if(scope==='evaluation') return key==='legacy' ? {overall:preview.review?.overall,evaluation:preview.review?.evaluation} : preview.review?.evaluation?.blocks?.find(b=>b.title===key);
  }
  function texts(preview) {
    const review=preview.review || {}, evaluation=review.evaluation || {};
    const values=(preview.annotations || []).map(a=>a.comment);
    values.push(review.context || '',...(review.paragraphs || []).flatMap(p=>(p.feedback || []).map(f=>f.text)));
    if(evaluation.version===3) for(const b of evaluation.blocks) {
      const details=['comprehensive','task','cohesion','lexical','grammar'].map(t=>b[`${t}_sections`]).find(Boolean);
      values.push(...(details?details.map(d=>d.text):[b.analysis,b.suggestions]));
    } else if(evaluation.version===2) values.push(evaluation.intro || '',...evaluation.overview.map(d=>d.text));
    else values.push(review.overall || '');
    return values.filter(Boolean);
  }
  function needsTranslation(preview,target) {
    return texts(preview).some(t=>target==='en'?/[\u3400-\u9fff]/.test(t):!/[\u3400-\u9fff]/.test(t));
  }
  function fetchTranslation(preview,language,scope='all',key='') {
    const localized=clone(preview), translations=preview.translations?.[language] || {};
    const slots=[];
    const add=(item,field)=>{if(item)slots.push([item,field]);};
    function blockSlots(block) {
      if(!block)return;
      const details=['comprehensive','task','cohesion','lexical','grammar'].map(t=>block[`${t}_sections`]).find(d=>d?.length);
      if(details)details.forEach(d=>add(d,'text'));
      else {add(block,'analysis');add(block,'suggestions');}
    }
    function reviewSlots(review) {
      if(!review)return;
      add(review,'context');
      (review.paragraphs || []).forEach(p=>(p.feedback || []).forEach(f=>add(f,'text')));
      const evaluation=review.evaluation || {};
      if(evaluation.version===3) {add(evaluation,'intro');(evaluation.blocks || []).forEach(blockSlots);}
      else if(evaluation.version===2) {add(evaluation,'intro');(evaluation.overview || []).forEach(d=>add(d,'text'));}
      else add(review,'overall');
    }
    const target=fragment(localized,scope,key);
    if(scope==='all') {(localized.annotations || []).forEach(a=>add(a,'comment'));reviewSlots(localized.review);}
    else if(scope==='annotation')add(target,'comment');
    else if(scope==='paragraph')(target?.feedback || []).forEach(f=>add(f,'text'));
    else if(scope==='evaluation') {if(key==='legacy')reviewSlots(target);else blockSlots(target);}
    for(const [item,field] of slots) {
      const text=item[field];if(typeof text!=='string' || !text.trim())continue;
      const required=language==='en'?/[\u3400-\u9fff]/.test(text):!/[\u3400-\u9fff]/.test(text);
      if(required && !translations[text])throw Error('Translation not prepared');
      if(translations[text])item[field]=translations[text];
    }
    return localized;
  }
  function draw() {
    if(!base) return;
    const preview=clone(base);
    for(const [id,state] of choices) {
      const current=fragment(base,state.scope,state.key);
      if(!current || JSON.stringify(current)!==state.signature) {choices.delete(id);continue;}
      if(!state.chinese) continue;
      const target=fragment(preview,state.scope,state.key);
      if(state.scope==='annotation') target.comment=state.translated.comment;
      else if(state.scope==='paragraph') target.feedback=clone(state.translated.feedback);
      else if(state.key==='legacy') {preview.review.overall=state.translated.overall;preview.review.evaluation=clone(state.translated.evaluation);}
      else Object.assign(target,clone(state.translated));
    }
    renderer(preview);
    for(const button of document.querySelectorAll('[data-translate-scope]')) {
      const id=JSON.stringify([button.dataset.translateScope,button.dataset.translateKey]), state=choices.get(id);
      let ready=true;
      try {fetchTranslation(base,'zh',button.dataset.translateScope,button.dataset.translateKey);} catch(error) {ready=false;}
      if(ready && state)state.error=false;
      button.textContent=state?.chinese?'查看英文':ready?'点击翻译':'译文准备中';
      button.disabled=!state?.chinese && !ready;
      button.setAttribute('aria-pressed',String(Boolean(state?.chinese)));
      if(!ready && !state?.chinese) {
        const note=document.createElement('span');note.className='feedback-translate-error';note.setAttribute('role','status');note.textContent='该点评译文尚未准备完成，保留英文。';button.after(note);
      }
    }
  }
  function toggle(scope,key) {
    const current=base && fragment(base,scope,key);if(!current)return;
    const id=JSON.stringify([scope,key]), signature=JSON.stringify(current), old=choices.get(id);
    if(old?.pending)return;
    if(old?.chinese) {old.chinese=false;draw();return;}
    if(old?.translated && old.signature===signature) {old.chinese=true;old.error=false;draw();return;}
    const state={scope,key,signature,pending:false,chinese:false,error:false}, currentEpoch=epoch;
    choices.set(id,state);
    try {
      const localized=fetchTranslation(base,'zh',scope,key);
      if(currentEpoch!==epoch || JSON.stringify(fragment(base,scope,key))!==signature)return;
      state.translated=fragment(localized,scope,key);state.chinese=true;
    } catch(error) {if(currentEpoch===epoch)state.error=true;}
    finally {state.pending=false;if(currentEpoch===epoch)draw();}
  }
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-translate-scope]');
    if(button)toggle(button.dataset.translateScope,button.dataset.translateKey);
  });
  function pendingPreview(preview) {
    const copy=clone(preview), message='正在准备英文点评…';
    (copy.annotations || []).forEach(a=>a.comment=message);
    const review=copy.review || {};review.context='';
    (review.paragraphs || []).forEach(p=>(p.feedback || []).forEach(f=>f.text=message));
    const evaluation=review.evaluation || {};
    (evaluation.blocks || []).forEach(b=>{b.analysis=b.suggestions=message;for(const t of ['comprehensive','task','cohesion','lexical','grammar'])(b[`${t}_sections`] || []).forEach(d=>d.text=message);});
    (evaluation.overview || []).forEach(d=>d.text=message);evaluation.intro='';
    if(![2,3].includes(evaluation.version))review.overall=message;
    return copy;
  }
  async function show(id,preview,renderPreview,api) {
    const token=++revision;
    if(jobId!==id) {epoch++;choices.clear();base=null;}
    jobId=id;renderer=renderPreview;request=api;status().textContent='';
    if(!needsTranslation(preview,'en')) {base=preview;draw();return;}
    if(!base) {renderer(pendingPreview(preview));for(const b of document.querySelectorAll('[data-translate-scope]'))b.disabled=true;}
    status().textContent='正在准备英文点评…';
    try {
      const english=fetchTranslation(preview,'en');
      if(token!==revision)return;
      base=english;draw();status().textContent='';
    } catch(error) {
      if(token!==revision)return;
      // Translation is an enhancement; keep the verified grading visible if it is unavailable.
      base=preview;
      renderer(preview);
      status().textContent='英文点评暂不可用，';
      const retry=document.createElement('button');retry.type='button';retry.className='text-button';retry.textContent='点击重试';retry.addEventListener('click',()=>show(id,preview,renderPreview,api));status().appendChild(retry);
    }
  }
  return {show,toggle,needsTranslation};
})();
