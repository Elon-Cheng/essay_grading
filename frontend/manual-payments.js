"use strict";
window.ManualPayments = {
  price(value) {
    const text=String(value).trim();
    if(!text)return null;
    if(!/^\d+(\.\d{1,2})?$/.test(text))throw new Error('请输入有效金额，最多两位小数');
    const [yuan,fen='']=text.split('.');
    const result=Number(yuan)*100+Number(fen.padEnd(2,'0'));
    if(!Number.isSafeInteger(result)||result<1||result>1000000)throw new Error('金额需在 ¥0.01–¥10000 之间');
    return result;
  },
  async settingsHtml() {
    const d=await api('/api/admin/payments/manual');
    const teacherPrice=d.prices?.teacher;
    const teacherHtml='<label>Teacher 每月售价（元）<input name="teacher_price" inputmode="decimal" value="'+(teacherPrice==null?'':(teacherPrice/100).toFixed(2))+'"></label><label class="check-label"><input name="teacher_enabled" type="checkbox" '+(d.teacher_enabled?'checked':'')+'>开放 Teacher 购买</label><p class="muted">Teacher 当前只有作文批改及每月 100 次额度，教师端、班级和批量功能尚未上线。</p>';
    return '<section class="card"><h2>个人收款设置</h2><p>用户扫码转账并提交凭证。请在微信或支付宝核实实际到账后，再审核开通会员。</p>'+(!d.active?'<p class="notice">当前仍使用商户支付模式，个人收款设置不会用于新订单。</p>':'')+'<form id="collection-settings"><label>Pro 每月售价（元；留空暂停购买）<input name="price" inputmode="decimal" value="'+(d.price_fen==null?'':(d.price_fen/100).toFixed(2))+'"></label>'+teacherHtml+[['wechat','微信'],['alipay','支付宝']].map(([c,label])=>'<label>'+label+'收款人显示名称<input name="'+c+'_receiver" maxlength="80" value="'+escapeText(d.receivers[c])+'"></label>').join('')+'<button class="button primary" type="submit">保存收款设置</button></form></section><div class="plans">'+[['wechat','微信'],['alipay','支付宝']].map(([c,label])=>'<section class="card"><h2>'+label+'个人收款码</h2>'+(d.qr_uploaded[c]?'<img class="collection-preview" alt="'+label+'收款码预览" src="/api/admin/payments/manual/'+c+'/qr?v='+Date.now()+'">':'<p class="muted">尚未上传</p>')+'<form data-collection-upload="'+c+'"><label>上传收款码图片（最多 2 MB）<input name="file" type="file" accept="image/png,image/jpeg,image/webp" required></label><button class="button secondary" type="submit">上传'+label+'收款码</button></form></section>').join('')+'</div>';
  },
  async checkout(order) {
    const manual=order.payment_mode==='manual';
    const canSubmit=manual&&['pending','rejected'].includes(order.status);
    $('#payment-proof').hidden=!canSubmit;
    if(canSubmit)$('#payment-proof').reset();
    $('#check-payment').textContent=manual?'查看审核结果':'我已支付，查询结果';
    $('#checkout-help').textContent=manual?'收款人：'+order.payment_receiver+'。请核对收款人，按订单金额转账，并在可填写备注时填写订单号 '+order.id+'。付款后提交成功截图和交易单号，管理员核实到账后开通；不要重复付款。':'支付成功后自动开通；关闭窗口不影响权益发放。';
    if(manual&&canSubmit&&order.expires<Date.now()/1000)$('#checkout-help').textContent='扫码支付窗口已结束。未付款请重新下单；若此前已付款，请提交成功截图和交易单号，等待管理员核实，请勿重复付款。';
    if(manual&&['review_pending','rejected','paid','refunded'].includes(order.status)) {
      try {const proof=await api('/api/orders/'+order.id+'/proof');if(proof.review_note)$('#pay-state').textContent=status(order.status)+' · '+proof.review_note;}catch{}
    }
  },
  async review(ident) {
    const order=(await api('/api/admin/records/orders')).find(o=>o.id===ident);
    if(!order)throw new Error('订单不在当前列表，请刷新');
    const proof=await api('/api/orders/'+ident+'/proof');
    let dialog=$('#manual-review');
    if(!dialog){dialog=document.createElement('dialog');dialog.id='manual-review';document.body.appendChild(dialog);}
    dialog.innerHTML='<button type="button" class="close" data-review-close aria-label="关闭">×</button><h2>核对实际到账</h2><p>'+escapeText(order.channel==='wechat'?'微信':'支付宝')+' · '+money(order.amount_fen)+' · 收款人 '+escapeText(order.payment_receiver)+'</p><p class="muted wrap">订单 '+escapeText(ident)+'<br>付款人 '+escapeText(proof.payer)+'<br>用户提交单号 '+escapeText(proof.reference)+'</p><a href="'+proof.image_url+'" target="_blank" rel="noopener">查看原尺寸凭证</a><img class="proof-preview" src="'+proof.image_url+'" alt="用户付款凭证"><form id="review-payment" data-order="'+ident+'"><label>实际到账交易号<input name="transaction_id" minlength="6" maxlength="128"></label><label>实际到账金额（元）<input name="amount" inputmode="decimal"></label><label>审核说明（至少5字）<textarea name="reason" minlength="5" maxlength="500" required></textarea></label><label class="check-label"><input name="confirmed" type="checkbox">我已在收款账户核实实际到账</label><div class="table-actions"><button type="submit" name="decision" value="approve" class="button primary">确认到账并开通 Pro</button><button type="submit" name="decision" value="reject" class="button secondary">驳回凭证</button></div></form><p id="review-message" role="status"></p>';
    dialog.querySelector('[value=approve]').textContent='确认到账并开通 '+(order.plan==='teacher'?'Teacher':'Pro');
    dialog.querySelector('[data-review-close]').onclick=()=>dialog.close();dialog.showModal();
  }
};
document.addEventListener('submit',async event=>{
  const form=event.target;
  if(!['collection-settings','payment-proof','review-payment'].includes(form.id)&&!form.dataset.collectionUpload)return;
  event.preventDefault();
  const button=event.submitter; if(button)button.disabled=true;
  try {
    if(form.id==='collection-settings') {
      await api('/api/admin/payments/manual',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({price_fen:ManualPayments.price(form.elements.price.value),teacher_price_fen:ManualPayments.price(form.elements.teacher_price.value),teacher_enabled:form.elements.teacher_enabled.checked,wechat_receiver:form.elements.wechat_receiver.value,alipay_receiver:form.elements.alipay_receiver.value})});
      notice('收款设置已保存');await renderAdmin();
    } else if(form.dataset.collectionUpload) {
      await api('/api/admin/payments/manual/'+form.dataset.collectionUpload+'/qr',{method:'POST',body:new FormData(form)});
      notice('收款码已上传，请核对预览及收款人');await renderAdmin();
    } else if(form.id==='payment-proof') {
      const order=await api('/api/orders/'+selectedOrder+'/proof',{method:'POST',body:new FormData(form)});
      updateCheckout(order);await ManualPayments.checkout(order);notice('付款凭证已提交，正在等待管理员核实到账');
    } else {
      const decision=button.value;
      const data={decision,reason:form.elements.reason.value,transaction_id:form.elements.transaction_id.value,amount_fen:decision==='approve'?ManualPayments.price(form.elements.amount.value):null,confirmed_received:form.elements.confirmed.checked};
      if(decision==='approve'&&(!data.confirmed_received||!data.amount_fen||data.transaction_id.trim().length<6))throw new Error('请先核实实际到账，填写金额和实际交易单号');
      await api('/api/admin/orders/'+form.dataset.order+'/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
      $('#manual-review').close();notice(decision==='approve'?'已确认到账并开通对应套餐':'已驳回凭证，用户可补充材料');await renderAdmin();
    }
  }catch(e){if(form.id==='review-payment')$('#review-message').textContent=e.message;else if(form.id==='payment-proof')$('#pay-state').textContent=e.message;else notice(e.message,true);}finally{if(button)button.disabled=false;}
});
