"use strict";
const $ = s => document.querySelector(s);
$('#download').addEventListener('click', async event => {
  event.preventDefault();
  const link = event.currentTarget;
  if (link.dataset.downloading === 'true') return;
  link.dataset.downloading = 'true';
  const label = link.textContent;
  link.textContent = '正在下载完整报告…';
  try {
    const response = await fetch(link.href);
    if (!response.ok) {
      let message = '下载失败，请稍后重试';
      try { message = (await response.json()).detail || message; } catch {}
      throw new Error(message);
    }
    if (!(response.headers.get('Content-Type') || '').includes('application/vnd.openxmlformats-officedocument.wordprocessingml.document')) {
      throw new Error('未收到有效的 Word 报告，请刷新页面后重试');
    }
    const blob = await response.blob();
    const length = response.headers.get('Content-Length');
    if (!blob.size || (length && blob.size !== Number(length))) throw new Error('报告下载不完整，请重试');
    const disposition = response.headers.get('Content-Disposition') || '';
    const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const plain = disposition.match(/filename="([^"]+)"/i);
    const filename = encoded ? decodeURIComponent(encoded[1]) : plain ? plain[1] : '完整批改报告.docx';
    const url = URL.createObjectURL(blob);
    const save = document.createElement('a');
    save.href = url;
    save.download = filename;
    document.body.appendChild(save);
    save.click();
    save.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (error) {
    notice(error.message, true);
    $('#status').scrollIntoView({behavior:'smooth', block:'center'});
  } finally {
    delete link.dataset.downloading;
    link.textContent = label;
  }
});
let chosenFile=null,records=[],busy=false,submissionKey=crypto.randomUUID();
const labels={queued:'等待处理',running:'批改中',succeeded:'已完成',failed:'未完成'};
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
$('#search').setAttribute('aria-label','搜索作文名称');$('#status').setAttribute('role','status');$('#status').setAttribute('aria-live','polite');
async function api(url,options){const r=await fetch(url,options);if(r.status===401){location.replace('/login');throw new Error('Session expired');}if(!r.ok){let message='请求失败，请稍后重试';try{const d=await r.json();if(typeof d.detail==='string')message=d.detail;}catch{}throw new Error(message);}return r.json();}
function notice(message,error=false){if(document.body.dataset.view!=='workspace')location.hash='workspace';$('#status').hidden=false;$('#status').textContent=message;$('#status').classList.toggle('error',error);}
function setBusy(value){busy=value;if(!value&&typeof refreshUsage==='function')refreshUsage();$('#submit').disabled=value;$('#submit').textContent=value?'正在批改…':'开始批改　→';renderHistory();}
function selectFile(file){if(!file)return;if(!file.name.toLowerCase().endsWith('.docx')||file.size>10*1024*1024||!file.size){notice('请选择有效的 .docx 文件，大小不超过 10 MB。',true);return;}chosenFile=file;submissionKey=crypto.randomUUID();$('#file-name').textContent=file.name;$('#file-hint').textContent=`${(file.size/1024).toFixed(1)} KB · 已选择，点击可更换文件`;$('#status').hidden=true;}
$('#file').addEventListener('change',e=>selectFile(e.target.files[0]));
for(const event of ['dragenter','dragover'])$('#dropzone').addEventListener(event,e=>{e.preventDefault();$('#dropzone').classList.add('dragover');});
for(const event of ['dragleave','drop'])$('#dropzone').addEventListener(event,e=>{e.preventDefault();$('#dropzone').classList.remove('dragover');if(event==='drop')selectFile(e.dataTransfer.files[0]);});
// Document content is escaped before interpreting supported formatting marks.
function inline(text){return esc(text).replace(/\{\+\+([\s\S]*?)\+\+\}/g,'<ins>$1</ins>').replace(/~~([\s\S]*?)~~/g,'<del>$1</del>').replace(/\[\[red\]\]([\s\S]*?)\[\[\/red\]\]/g,'<span class="red">$1</span>').replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>').replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g,'<em>$1</em>');}
function markdown(text){const lines=text.split('\n');let out='',paragraph=[];const flush=()=>{if(paragraph.length){out+='<p>'+inline(paragraph.join('\n'))+'</p>';paragraph=[];}};for(let i=0;i<lines.length;i++){const line=lines[i],trimmed=line.trim();if(trimmed.startsWith('|')){flush();let rows=[];while(i<lines.length&&lines[i].trim().startsWith('|')){const cells=lines[i].trim().replace(/^\||\|$/g,'').split('|');if(!cells.every(c=>/^\s*:?-{3,}:?\s*$/.test(c)))rows.push(cells);i++;}i--;out+='<div class="table-scroll"><table>'+rows.map((row,n)=>'<tr>'+row.map(c=>`<${n?'td':'th'}>${inline(c.trim())}</${n?'td':'th'}>`).join('')+'</tr>').join('')+'</table></div>';}else if(/^#{1,6}\s/.test(line)){flush();out+='<h3>'+inline(line.replace(/^#+\s+/,''))+'</h3>';}else if(/^[-*]\s+/.test(trimmed)){flush();let items=[];while(i<lines.length&&/^[-*]\s+/.test(lines[i].trim())){items.push('<li>'+inline(lines[i].trim().replace(/^[-*]\s+/,''))+'</li>');i++;}i--;out+='<ul>'+items.join('')+'</ul>';}else if(!trimmed)flush();else paragraph.push(line);}flush();return out;}
function reviewReport(text) {
  const parts = text.split(/^####[ \t]+(.+?)[ \t]*\r?$/m);
  if (parts.length === 1) return markdown(text);
  let output = parts[0].trim() ? `<div class="review-intro">${markdown(parts[0])}</div>` : '';
  let current = null, count = 0;
  const finish = () => {
    if (!current) return;
    output += `<section class="paragraph-review"><header class="paragraph-heading"><span class="paragraph-number">${String(++count).padStart(2,'0')}</span><h3>原文与逐段反馈</h3></header><div class="essay-text">${markdown(current.original)}</div><div class="teacher-feedback">${current.feedback}</div></section>`;
    current = null;
  };
  for (let i = 1; i < parts.length; i += 2) {
    const name = parts[i].trim(), body = parts[i + 1] || '';
    if (name === '原文及红色修改') {
      finish();
      current = {original: body, feedback: ''};
    } else if (name === '全文综合评价和提升建议') {
      finish();
      const score = body.match(/^本篇文章打分估计为[：:]\s*(.+?)分[。.]?\s*$/m);
      const content = score ? body.replace(score[0], '') : body;
      output += `<section class="review-summary"><header><div><span class="summary-eyebrow">OVERALL FEEDBACK</span><h3>全文综合评价与提升建议</h3></div>${score ? `<div class="review-score"><strong>${esc(score[1])}</strong><span>/ 25 分</span></div>` : ''}</header>${markdown(content)}</section>`;
    } else if (current) {
      current.feedback += `<section class="feedback-section"><h4>${esc(name)}</h4>${markdown(body)}</section>`;
    } else {
      output += `<section class="review-intro"><h3>${esc(name)}</h3>${markdown(body)}</section>`;
    }
  }
  finish();
  return output;
}
const retryButton=document.createElement('button');
retryButton.type='button';retryButton.className='button primary';
retryButton.textContent='重试未完成的批改';retryButton.hidden=true;
$('#download').parentElement.appendChild(retryButton);
retryButton.addEventListener('click',async()=>{
  if(busy)return;
  const id=retryButton.dataset.job;
  setBusy(true);retryButton.hidden=true;
  try{await api(`/api/essays/${id}/retry`,{method:'POST'});await watch(id);}
  catch(error){notice(error.message,true);setBusy(false);retryButton.hidden=false;}
});
async function openResult(job, preview = null, reveal = true){
  preview = preview || await api(`/api/essays/${job.id}/preview`);
  ReviewLanguage.show(job.id,preview,p=>EssayReview.render(p,markdown),api);
  document.body.classList.add('has-result');
  $('#result-name').textContent=job.filename;
  const ready=job.status==='succeeded';
  retryButton.hidden=!job.retryable;
  retryButton.dataset.job=job.id;
  $('#download').hidden=!ready;
  if(ready) $('#download').href=`/api/essays/${job.id}/download`;
  else $('#download').removeAttribute('href');
  $('#result').hidden=false;
  if(reveal){location.hash='workspace';$('#result').scrollIntoView({behavior:'smooth',block:'start'});}
  if(ready && typeof loadActivity==='function')loadActivity();
}

function renderHistory(){const query=$('#search').value.trim().toLowerCase();const list=records.filter(r=>r.filename.toLowerCase().includes(query));$('#total').textContent=records.length;$('#nav-count').textContent=records.length;$('#completed').textContent=records.filter(r=>r.status==='succeeded').length;$('#processing').textContent=records.filter(r=>['queued','running'].includes(r.status)).length;$('#history-body').innerHTML=list.map(r=>`<tr><td><div class="doc-name"><span class="doc-icon">W</span><span class="filename">${esc(r.filename)}</span></div></td><td><span class="badge ${['queued','running','succeeded','failed'].includes(r.status)?r.status:''}">${labels[r.status]||'未知状态'}</span></td><td><button class="text-button" data-job="${esc(r.id)}" ${busy?'disabled':''}>${r.status==='succeeded'?'查看反馈 ↗':r.status==='failed'?'查看详情':'查看进度'}</button></td></tr>`).join('');$('#history-empty').hidden=!!list.length;$('#history-empty').textContent=query?'没有找到匹配的作文。':'还没有作文记录。上传第一篇作文，开始积累反馈。';}
async function loadHistory(){try{records=await api('/api/essays');renderHistory();$('#history-error').hidden=true;}catch(e){$('#history-error').hidden=false;$('#history-error').textContent='暂时无法读取作文记录。'+e.message;}}
$('#search').addEventListener('input',renderHistory);
$('#history-body').addEventListener('click',async e=>{const button=e.target.closest('[data-job]');if(!button)return;const job=records.find(r=>r.id===button.dataset.job);if(!job)return;try{if(job.status==='succeeded')await openResult(job);else if(job.status==='failed'){await openResult(job);notice('这篇作文未完成批改：'+(job.error||'请重新上传后再试。'),true);$('#status').scrollIntoView({behavior:'smooth',block:'center'});}else{setBusy(true);await watch(job.id);}}catch(err){notice(err.message,true);setBusy(false);}});
function progress(job){const phase={queued:-1,extracting:0,grading:1,rendering:2,done:3}[job.stage]??-1;$('#steps').hidden=false;$('#steps').querySelectorAll('li').forEach((el,i)=>{el.classList.toggle('done',i<phase);el.classList.toggle('current',i===phase);});notice(({queued:'作文已提交，正在等待处理。',extracting:'正在读取文档，提取作文正文…',grading:'正在分别生成词句批改与段落报告，已完成的反馈会先显示…',rendering:'正在整理批注并生成 Word 文档…',done:'批改已完成，可以查看反馈或下载文档。'})[job.stage]||'正在处理…');}
async function watch(id){
  let revision='', revealed=false;
  try{while(true){
    const job=await api(`/api/essays/${id}`);progress(job);
    const index=records.findIndex(r=>r.id===id);if(index<0)records.unshift(job);else records[index]=job;renderHistory();
    // Preview is readable while running: each completed channel arrives independently.
    if(job.stage!=='queued' && job.stage!=='extracting'){
      const preview=await api(`/api/essays/${id}/preview`);
      const next=JSON.stringify([preview.channels,preview.annotations,preview.review,job.status]);
      if(preview.original.length && next!==revision){
        await openResult(job,preview,!revealed);revision=next;revealed=true;
      }
    }
    if(job.status==='failed')throw new Error(job.error||'批改未完成，请重新上传。');
    if(job.status==='succeeded')break;
    await new Promise(r=>setTimeout(r,1400));
  }}catch(e){notice(e.message,true);}finally{setBusy(false);await loadHistory();}
}

$('#form').addEventListener('submit',async e=>{e.preventDefault();if(busy)return;if(!chosenFile){notice('请先选择一篇 DOCX 作文。',true);$('#file').focus();return;}setBusy(true);$('#result').hidden=true;$('#steps').hidden=true;notice('正在上传作文…');try{const body=new FormData();body.append('file',chosenFile);const start=$('#start').value.trim();if(start)body.append('start',start);const job=await api('/api/essays',{method:'POST',headers:{'Idempotency-Key':submissionKey},body});await watch(job.id);}catch(err){notice(err.message,true);setBusy(false);}});

$('#start').addEventListener('input',()=>{submissionKey=crypto.randomUUID();});
