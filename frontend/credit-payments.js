'use strict';
const CreditPayments = (() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function request(url,options) {
    const response = await fetch(url,options);
    if (response.status === 401) {location.assign('/login');throw Error('请先登录');}
    const data = await response.json();
    if (!response.ok) throw Error(data.detail || '请求失败');
    return data;
  }
  async function catalog() {
    const data = await request('/api/payment/products');
    return '<section class="card"><h2>购买批改次数</h2><p>按次购买，次数不按月清零。批改成功扣除，失败返还。</p><div class="plans">'+data.products.map(p=>'<section class="card"><h3>'+escape(p.name)+'</h3><p>'+p.essay_credits+' 次 · ¥'+(p.price_fen/100).toFixed(2)+'</p>'+['wechat','alipay'].map(c=>'<button class="button primary" data-credit-product="'+p.id+'" data-credit-method="'+c+'" '+(data.channels[c]?'':'disabled')+'>'+(c==='wechat'?'微信支付':'支付宝')+'</button>').join('')+'</section>').join('')+'</div>'+(!Object.values(data.channels).some(Boolean)?'<p class="muted">收款渠道准备中，暂未开放购买。</p>':'')+'</section>';
  }
  async function history(admin=false) {
    const rows = await request(admin?'/api/admin/payments':'/api/payment/orders');
    return '<section class="card"><h2>批改次数订单</h2>'+(rows.length?'<div class="table-scroll"><table><thead><tr><th>订单</th><th>套餐</th><th>次数</th><th>金额</th><th>状态</th><th>操作</th></tr></thead><tbody>'+rows.map(r=>{const n=r.orderNo||r.order_no,s=r.status;return '<tr><td>'+escape(n)+'</td><td>'+escape(r.productName||r.product_name)+'</td><td>'+(r.essayCredits||r.essay_credits)+'</td><td>¥'+((r.amountFen||r.actual_amount)/100).toFixed(2)+'</td><td>'+escape({PENDING:'待支付',PAID:'已到账',EXPIRED:'已过期',FAILED:'失败'}[s]||s)+'</td><td>'+(!admin?'<a href="/payment/'+encodeURIComponent(n)+'">查看订单</a>':'')+'</td></tr>';}).join('')+'</tbody></table></div>':'<p>暂无次数订单。</p>')+'</section>';
  }
  document.addEventListener('click',async event=>{
    const button = event.target.closest('[data-credit-product]');
    if (!button) return;
    button.disabled = true;
    // Retain the key after a network error so retry cannot create a second charge.
    button.dataset.creditKey ||= crypto.randomUUID();
    try {
      const order = await request('/api/payment/create',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':button.dataset.creditKey},body:JSON.stringify({productId:Number(button.dataset.creditProduct),paymentMethod:button.dataset.creditMethod})});
      location.assign('/payment/'+encodeURIComponent(order.orderNo));
    } catch(error) {button.disabled=false;const message=document.querySelector('#message');if(message){message.hidden=false;message.textContent=error.message;}else alert(error.message);}
  });
  if (location.pathname.startsWith('/payment/')) {
    const orderNo = decodeURIComponent(location.pathname.split('/').pop());
    let timer;
    async function poll() {
      try {
        const order = await request('/api/payment/'+encodeURIComponent(orderNo)+'/status');
        document.querySelector('#credit-description').textContent=order.productName+' · '+order.essayCredits+' 次批改 · 应付 ¥'+order.amount.toFixed(2)+(order.status==='PENDING'&&order.paymentMethod==='wechat'&&order.payNum?' · 付款备注：'+order.payNum+'（请填写以匹配订单）':'');
        const pending=order.status==='PENDING' && order.expiresAt>Date.now()/1000;
        const qr=document.querySelector('#credit-qr'),link=document.querySelector('#credit-provider');
        qr.hidden=!pending || !order.qrCodeUrl;link.hidden=!pending || !order.paymentUrl;
        if(!qr.hidden)qr.src=order.qrCodeUrl;
        if(!link.hidden)link.href=order.paymentUrl;
        document.querySelector('#credit-state').textContent=order.status==='PAID'?'支付成功，已增加 '+order.essayCredits+' 次批改额度。':order.status==='EXPIRED'?'订单已过期，请勿继续付款。':order.error||'请扫码支付，等待到账确认…';
        document.querySelector('#credit-done').hidden=order.status!=='PAID';
        if(!pending)clearInterval(timer);
      } catch(error) {document.querySelector('#credit-state').textContent=error.message;}
    }
    timer=setInterval(poll,3000);poll();
    addEventListener('pagehide',()=>clearInterval(timer),{once:true});
  }
  return {catalog,history};
})();
