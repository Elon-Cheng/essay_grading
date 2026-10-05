"use strict";
const $ = selector => document.querySelector(selector);
const escapeText = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const when = stamp => stamp ? new Date(stamp * 1000).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false}) : '—';
const money = fen => fen == null ? '价格待公布' : '¥' + (fen / 100).toFixed(2);
const statusLabels = {creating:'下单待确认',pending:'待支付',paid:'已支付',closed:'已关闭',refund_pending:'退款处理中',refunded:'已退款',queued:'等待处理',running:'处理中',succeeded:'成功',failed:'失败',active:'生效',expired:'已到期',revoked:'已撤销',processing:'处理中',unknown:'用量待核查',format_error:'格式修复',http_error:'接口错误',started:'调用中',processed:'已处理',rejected:'已拒绝'};
const status = value => statusLabels[value] || value || '—';
Object.assign(statusLabels,{review_pending:'待人工核实',rejected:'凭证已驳回'});
let currentUser = null, selectedOrder = null, paymentTimer = null, adminTab = 'overview';
async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) { let detail = '请求失败，请稍后再试'; try { detail = (await response.json()).detail || detail; } catch {} if (response.status === 401 && location.pathname !== '/pricing') location.href='/login'; throw new Error(detail); }
  return response.json();
}
function notice(text, error = false) { $('#message').hidden=false; $('#message').textContent=text; $('#message').classList.toggle('error',error); }
function table(columns, rows) { return '<div class="table-scroll"><table><thead><tr>'+columns.map(c=>'<th>'+escapeText(c[0])+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+columns.map(c=>'<td class="'+(c[2] || '')+'">'+(c[1](row))+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>'; }
function metric(label, value) { return '<div class="card"><div class="metric-label">'+escapeText(label)+'</div><div class="metric-value">'+escapeText(value)+'</div></div>'; }
async function renderPricing() {
  const data=await api('/api/plans');
  $('#content').innerHTML='<div class="plans">'+data.plans.map(plan=>{
    const isPro=plan.id==='pro';
    const action=plan.id==='free'?'<a class="button secondary" href="/workspace">进入工作台</a>':plan.enabled?'<div class="pay-buttons">'+[['wechat','微信支付'],['alipay','支付宝']].map(([channel,label])=>'<button class="button primary" data-buy="'+channel+'" data-plan="'+plan.id+'" '+(!plan.purchasable || !data.channels[channel]?'disabled':'')+'>'+label+'</button>').join('')+'</div>':'<button class="button secondary" disabled>暂未开放购买</button>';
    return '<section class="card plan-card '+(isPro?'featured':'')+'"><span class="badge">'+(isPro?'适合持续练习':plan.id==='free'?'开始你的第一篇':'教师套餐')+'</span><h2 class="plan-name">'+escapeText(plan.name)+'</h2><div class="price">'+(plan.id==='free'?'免费':money(plan.price_fen)+'<span class="muted"> / 月</span>')+'</div>'+(plan.id==='teacher'&&!plan.enabled?'<p class="muted">教师功能准备中，暂未开放购买。</p>':'')+'<ul><li>'+plan.quota+' 次 / '+(plan.id==='free'?'自然月':'订阅月')+'</li><li>逐段点评与语言建议</li><li>完整 Word 批改报告</li><li>个人批改历史</li>'+(plan.id==='free'&&data.free_daily_quota?'<li>每天最多 '+data.free_daily_quota+' 次</li>':'')+'</ul>'+action+'</section>';
  }).join('')+'</div><p class="notice">免费额度按北京时间自然月重置。付费套餐按订阅月发放额度，续费顺延有效期；未使用额度不结转。批改失败返还次数。'+(data.plans.some(p=>p.purchasable)?(data.payment_mode==='manual'?'微信或支付宝个人收款码转账，提交付款凭证后由管理员核实到账并开通对应套餐。':'支持微信或支付宝扫码支付。'):data.plans.some(p=>p.price_fen!=null)?'套餐售价已公布，收款方式准备中，当前未开放购买。':'当前未开放购买，售价及收款方式准备中。')+'</p>';
}
async function renderAccount() {
  const data=await api('/api/subscription');
  if(data.unlimited){$('#content').innerHTML='<section class="card"><h2>???</h2><p>????????? ? ????</p><p>??? '+data.used_quota+' ? ? ??? '+data.reserved_quota+' ?</p></section>';return;}
  $('#content').innerHTML='<section class="card"><span class="badge">当前套餐</span><h2 class="subscription-name">'+escapeText({free:'免费版',pro:'Pro',teacher:'教师版'}[data.plan])+'</h2><p>有效期至：'+(data.expire_at?when(data.expire_at):'长期有效')+'</p><progress value="'+(data.used_quota+data.reserved_quota)+'" max="'+data.quota+'" aria-label="本周期额度使用进度"></progress><p>本周期 '+data.quota+' 次 · 已使用 '+data.used_quota+' 次 · 处理中 '+data.reserved_quota+' 次 · 剩余 '+data.remaining_quota+' 次</p><p class="muted">下次额度重置：'+when(data.period_end)+'</p><a class="button primary" href="/pricing">查看套餐</a></section><div class="summary-grid">'+metric('本周期总额度',data.quota)+metric('已使用',data.used_quota)+metric('处理中占用',data.reserved_quota)+metric('可用额度',data.remaining_quota)+'</div><p class="notice">提交时预占次数，报告完成后扣除；失败时返还。会员到期后，仍可查看和下载历史报告。</p>';
}
async function renderOrders() {
  const rows=await api('/api/orders');
  $('#content').innerHTML='<section class="card">'+(rows.length?table([['订单',r=>escapeText(r.id),'wrap'],['创建时间',r=>when(r.created)],['套餐',r=>escapeText(r.plan)],['金额',r=>money(r.amount_fen)],['渠道',r=>(r.channel==='wechat'?'微信':'支付宝')+(r.payment_mode==='manual'?'（人工核实）':'')],['状态',r=>escapeText(status(r.status))],['操作',r=>['pending','creating','review_pending','rejected'].includes(r.status)?'<button class="button secondary" data-pay="'+escapeText(r.id)+'">查看订单</button>':'—']],rows):'<div class="empty">还没有订单。<a href="/pricing">查看套餐 →</a></div>')+'</section>';
}
async function openCheckout(order) {
  selectedOrder=order.id;
  $('#checkout-description').textContent=(order.plan==='teacher'?'Teacher':'Pro')+' · '+(order.channel==='wechat'?'微信支付':'支付宝')+' · '+money(order.amount_fen);
  $('#pay-qr').hidden=!order.code_url || order.expires<Date.now()/1000 || !['pending','rejected'].includes(order.status);
  if(!$('#pay-qr').hidden) $('#pay-qr').src='/api/orders/'+order.id+'/qr';
  $('#pay-state').textContent=status(order.status)+(order.error?' · '+order.error:'');
  if(!$('#checkout').open)$('#checkout').showModal();
  await ManualPayments.checkout(order);
  document.getElementById('paypro-link')?.remove();
  if(order.payment_mode==='paypro' && order.code_url && order.status==='pending' && order.expires>Date.now()/1000){const link=document.createElement('a');link.id='paypro-link';link.className='button primary';link.href=order.code_url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='打开支付页面';document.getElementById('pay-state').after(link);}
  clearInterval(paymentTimer);
  paymentTimer=setInterval(async()=>{try{const fresh=await api('/api/orders/'+selectedOrder);updateCheckout(fresh);}catch{}},5000);
}
function updateCheckout(order){$('#pay-state').textContent=status(order.status)+(order.error?' · '+order.error:'');if(order.payment_mode==='manual')$('#payment-proof').hidden=!['pending','rejected'].includes(order.status);if(!['pending','rejected'].includes(order.status)||order.expires<Date.now()/1000)$('#pay-qr').hidden=true;if(order.status==='paid'){clearInterval(paymentTimer);$('#pay-qr').hidden=true;$('#pay-state').textContent='已确认到账，'+(order.plan==='teacher'?'Teacher':'Pro')+' 已开通';render().catch(e=>notice(e.message,true));}}
async function renderAdmin() {
  const tabs=[['overview','运营概览'],['collection','个人收款'],['accounts','用户与额度'],['jobs','批改任务'],['calls','AI 调用'],['orders','订单与审核'],['refunds','退款'],['payments','支付通知'],['audit','操作审计']];
  let html='<div class="tabs">'+tabs.map(([id,label])=>'<button class="button secondary '+(adminTab===id?'active':'')+'" data-tab="'+id+'">'+label+'</button>').join('')+'</div>';
  if(adminTab==='overview') {
    const d=await api('/api/admin/overview');
    const pct=v=>v==null?'暂无数据':(v*100).toFixed(1)+'%';
    html+='<div class="summary-grid">'+metric('用户总数',d.users)+metric('今日活跃用户',d.dau)+metric('今日注册',d.registrations_today)+metric('今日批改提交',d.jobs_today)+metric('真实报告成功',d.succeeded_today)+metric('真实报告失败',d.failed_today)+metric('任务失败率',pct(d.task_error_rate))+metric('等待 / 处理中',d.pending_jobs)+metric('今日 API 调用',d.api_calls_today)+metric('输入 token',d.input_tokens)+metric('输出 token',d.output_tokens)+metric('API 错误率',pct(d.api_error_rate))+metric('今日实付',money(d.paid_fen))+metric('今日退款',money(d.refunded_fen))+metric('30天免费转付费',pct(d.paid_conversion_30d))+metric('注册转化',pct(d.registration_conversion))+'</div>';
    html+='<section class="card"><h2>AI 成本估算</h2><p>'+Object.entries(d.estimated_cost_by_currency).map(([currency,cost])=>escapeText(currency)+' '+cost.toFixed(4)).join(' · ')+'</p><p>成功交付平均成本：'+Object.entries(d.average_delivery_cost_by_currency).map(([currency,cost])=>escapeText(currency)+' '+(cost==null?'暂无数据':cost.toFixed(4))).join(' · ')+'</p><p class="muted">未知用量 '+d.unknown_usage_calls+' 次；未配置单价或无法估价 '+d.unpriced_calls+' 次。估算费用需与供应商账单核对。</p></section>';
  } else if(adminTab==='collection') {
    html+=await ManualPayments.settingsHtml();
  } else if(adminTab==='accounts') {
    const rows=await api('/api/admin/accounts');
    html+='<section class="card">'+table([['用户',r=>escapeText(r.username)],['权限',r=>escapeText(r.role)],['套餐',r=>escapeText(r.plan)],['到期时间',r=>when(r.expire_at)],['额度',r=>r.unlimited?'????':r.remaining_quota+' / '+r.quota],['状态',r=>r.disabled?'已禁用':'正常'],['操作',r=>'<div class="table-actions"><button class="button secondary" data-grant="'+r.id+'">发放会员</button><button class="button secondary" data-quota="'+r.id+'">调整额度</button>'+(r.role!=='admin'?'<button class="button secondary" data-disable="'+r.id+'" data-disabled="'+r.disabled+'">'+(r.disabled?'启用':'禁用')+'</button>':'')+'</div>']],rows)+'</section>';
  } else {
    const rows=await api('/api/admin/records/'+adminTab);
    const columns={
      jobs:[['任务',r=>escapeText(r.filename),'wrap'],['用户',r=>r.user_id],['状态',r=>escapeText(status(r.status))],['阶段',r=>escapeText(r.stage)],['尝试',r=>r.attempts],['额度',r=>escapeText(r.quota_state)],['AI 成本',r=>Object.entries(r.ai_costs||{}).map(([c,v])=>escapeText(c)+' '+v.toFixed(4)).join(' · ')+(r.unknown_cost_calls?'（'+r.unknown_cost_calls+' 次费用未知）':'')],['错误',r=>escapeText(r.error),'wrap']],
      calls:[['时间',r=>when(r.started)],['任务',r=>escapeText(r.job_id),'wrap'],['模型',r=>escapeText(r.returned_model||r.model)],['输入 / 输出',r=>(r.input_tokens??'未知')+' / '+(r.output_tokens??'未知')],['缓存输入',r=>r.cached_tokens??'未知'],['费用估算',r=>r.estimated_cost==null?'未知':escapeText(r.currency)+' '+r.estimated_cost.toFixed(6)],['耗时',r=>(r.latency_ms??'—')+' ms'],['状态',r=>escapeText(status(r.status))],['核查',r=>r.status==='unknown'?'<button class="button secondary" data-resolve="'+escapeText(r.id)+'">核查用量</button>':'—']],
      orders:[['订单',r=>escapeText(r.id),'wrap'],['用户',r=>r.user_id],['渠道',r=>escapeText(r.channel)+(r.payment_mode==='manual'?'（人工）':'')],['金额',r=>money(r.amount_fen)],['状态',r=>escapeText(status(r.status))],['操作',r=>r.payment_mode==='manual'?(r.status==='review_pending'?'<button class="button primary" data-review="'+escapeText(r.id)+'">审核到账</button>':r.status==='paid'?'<button class="button secondary" data-manual-refund="'+escapeText(r.id)+'">登记实际退款</button>':'—'):r.status==='paid'?'<button class="button secondary" data-refund="'+escapeText(r.id)+'">全额退款</button>':'—']],
      refunds:[['订单',r=>escapeText(r.order_id),'wrap'],['金额',r=>money(r.amount_fen)],['状态',r=>escapeText(status(r.status))],['原因',r=>escapeText(r.reason),'wrap'],['更新时间',r=>when(r.updated)]],
      payments:[['渠道',r=>escapeText(r.channel)],['订单',r=>escapeText(r.order_id),'wrap'],['状态',r=>escapeText(status(r.status))],['错误',r=>escapeText(r.error),'wrap'],['时间',r=>when(r.created)]],
      audit:[['时间',r=>when(r.created)],['操作者',r=>r.actor_id??'系统'],['操作',r=>escapeText(r.action)],['对象',r=>escapeText(r.target),'wrap'],['原因',r=>escapeText(r.reason),'wrap']]
    };
    html+='<section class="card">'+(rows.length?table(columns[adminTab],rows):'<p class="empty">暂无记录</p>')+'</section>';
  }
  $('#content').innerHTML=html;
}
async function render() {
  const path=location.pathname;
  const info={'/pricing':['选择适合你的练习节奏','免费版每月 3 次，Pro 每订阅月 100 次。'], '/account':['我的账户','查看套餐、额度和有效期。'], '/orders':['订单记录','支付和会员开通进度一目了然。'], '/admin':['运营后台','查看使用量、支付和 AI 成本。']}[path]||['我的账户',''];
  $('#page-title').textContent=info[0];$('#page-subtitle').textContent=info[1];document.title='墨评 · '+info[0];
  if(path==='/pricing')await renderPricing();else if(path==='/orders')await renderOrders();else if(path==='/admin')await renderAdmin();else await renderAccount();
  if(path==='/pricing')$('#content').insertAdjacentHTML('afterbegin',await CreditPayments.catalog());
  if(path==='/account'){
    const credits=await api('/api/subscription');
    $('#content').insertAdjacentHTML('afterbegin','<section class="card"><h2>按次购买额度</h2><p>剩余 '+credits.essay_credits+' 次 · 处理中 '+credits.reserved_credits+' 次 · 可用 '+credits.available_credits+' 次</p><a class="button primary" href="/pricing">购买批改次数</a></section>');
  }
  if(path==='/orders')$('#content').insertAdjacentHTML('afterbegin',await CreditPayments.history());
  if(path==='/admin' && adminTab==='orders')$('#content').insertAdjacentHTML('beforeend',await CreditPayments.history(true));
}
$('#refresh').onclick=()=>render().catch(e=>notice(e.message,true));
$('#close-checkout').onclick=()=>$('#checkout').close();$('#checkout').addEventListener('close',()=>clearInterval(paymentTimer));
$('#check-payment').onclick=async()=>{try{const order=await api('/api/orders/'+selectedOrder+'/refresh',{method:'POST'});updateCheckout(order);}catch(e){$('#pay-state').textContent=e.message;}};
$('#content').addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  button.disabled=true;
  try {
    if(button.dataset.buy){if(!currentUser){location.href='/login';return;}const plan=button.dataset.plan||'pro';const keyName='essay-order-key-'+plan+'-'+button.dataset.buy;const key=sessionStorage.getItem(keyName)||crypto.randomUUID();sessionStorage.setItem(keyName,key);const order=await api('/api/orders',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify({plan,channel:button.dataset.buy})});sessionStorage.removeItem(keyName);await openCheckout(order);}
    else if(button.dataset.pay)await openCheckout(await api('/api/orders/'+button.dataset.pay));
    else if(button.dataset.review)await ManualPayments.review(button.dataset.review);
    else if(button.dataset.manualRefund){const transaction=prompt('请先在收款账户完成退款，再填写实际退款交易号');if(transaction===null)return;const amount=prompt('实际全额退款金额（元）');if(amount===null)return;const reason=prompt('退款原因（至少5字）。保存后撤销该订单会员权益');if(reason===null)return;await api('/api/admin/orders/'+button.dataset.manualRefund+'/manual-refund',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({transaction_id:transaction,amount_fen:ManualPayments.price(amount),confirmed_refunded:true,reason})});notice('实际退款已登记，会员权益已撤销');await renderAdmin();}
    else if(button.dataset.tab){adminTab=button.dataset.tab;await renderAdmin();}
    else if(button.dataset.grant){const months=prompt('发放 Pro 月数（1–12）','1');if(months===null)return;const reason=prompt('填写发放原因（至少5字）');if(reason===null)return;await api('/api/admin/users/'+button.dataset.grant+'/subscription',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan:'pro',months:Number(months),reason})});notice('会员已发放，并已记录操作审计');await renderAdmin();}
    else if(button.dataset.resolve){const input=prompt('已向供应商核查的输入 token 数');if(input===null)return;const output=prompt('已核查的输出 token 数');if(output===null)return;const cost=prompt('已核查费用（按本次记录币种）；留空使用原价格快照估算','');if(cost===null)return;const reason=prompt('填写核查依据（至少5字）');if(reason===null)return;await api('/api/admin/calls/'+button.dataset.resolve+'/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({input_tokens:Number(input),output_tokens:Number(output),verified_cost:cost===''?null:Number(cost),reason})});notice('用量已核查并保存审计记录');await renderAdmin();}
    else if(button.dataset.quota){const delta=prompt('本周期额度调整量，例如 3 或 -1','3');if(delta===null)return;const reason=prompt('填写额度调整原因（至少5字）');if(reason===null)return;await api('/api/admin/users/'+button.dataset.quota+'/quota',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delta:Number(delta),reason})});notice('本周期额度已调整');await renderAdmin();}
    else if(button.dataset.disable){const reason=prompt('填写账号状态调整原因（至少5字）');if(reason===null)return;await api('/api/admin/users/'+button.dataset.disable+'/state',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({disabled:button.dataset.disabled==='0',reason})});await renderAdmin();}
    else if(button.dataset.refund){const reason=prompt('全额退款后将撤销该订单会员权益。请填写退款原因（至少5字）');if(reason===null)return;const result=await api('/api/admin/orders/'+button.dataset.refund+'/refund',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})});notice('退款状态：'+status(result.status));await renderAdmin();}
  }catch(error){notice(error.message,true);}finally{button.disabled=false;}
});
(async()=>{try{const response=await fetch('/api/auth/me');if(response.ok){currentUser=await response.json();$('#session-link').textContent=currentUser.username;$('#session-link').href='/account';$('#admin-link').hidden=currentUser.role!=='admin';}document.querySelectorAll('.site-header nav a').forEach(a=>a.classList.toggle('active',a.pathname===location.pathname));await render();}catch(e){notice(e.message,true);}})();
