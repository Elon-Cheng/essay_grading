"""Patch an isolated PayPro source copy for one-order Alipay OpenAPI settlement."""
from pathlib import Path


def prepare(root):
    java = root / 'src/main/java/com/wendao'
    response = java / 'model/resp/OpenApiOrderResp.java'
    text = response.read_text(encoding='utf-8')
    if 'private String qrCode;' in text:
        raise ValueError('Alipay patch already applied')
    response.write_text(text.replace('    private String qrCodeUrl;', '    private String qrCode;\n\n    private String qrCodeUrl;'),encoding='utf-8')
    service = java / 'service/impl/OrderServiceImpl.java'
    text = service.read_text(encoding='utf-8')
    boundary = text.index('    public OpenApiOrderResp createOpenApiOrder(')
    before, channel = text[:boundary], text[boundary:]
    channel = channel.replace('        Order existingOrder =', '''        if (payProConfig.getPayMethods() == null || payProConfig.getPayMethods().stream()
                .noneMatch(method -> method.getId().equals(req.getPayType()) && method.isStatus())) {
            throw new IllegalArgumentException("Payment channel is disabled");
        }
        Order existingOrder =''',1)
    marker='        String tokenAdmin = UUID.randomUUID().toString();'
    assert marker in channel
    channel = channel.replace(marker,'''        String nativeQrCode = null;
        if ("alipay_dmf".equals(req.getPayType())) {
            com.alipay.api.AlipayClient client = new com.alipay.api.DefaultAlipayClient(
                    "https://openapi.alipay.com/gateway.do", payProConfig.getAlipayDmfAppId(),
                    payProConfig.getAlipayDmfAppPrivateKey(), "json", "GBK",
                    payProConfig.getAlipayDmfPublicKey(), "RSA2");
            com.alipay.api.request.AlipayTradePrecreateRequest request =
                    new com.alipay.api.request.AlipayTradePrecreateRequest();
            com.alibaba.fastjson2.JSONObject business = new com.alibaba.fastjson2.JSONObject();
            business.put("out_trade_no", order.getId());
            business.put("total_amount", req.getAmount().toPlainString());
            business.put("subject", payProConfig.getAlipayDmfSubject());
            business.put("timeout_express", "15m");
            request.setBizContent(business.toJSONString());
            request.setNotifyUrl(payProConfig.getSite() + "/alipay/notify");
            try {
                com.alipay.api.response.AlipayTradePrecreateResponse result = client.execute(request);
                if (!result.isSuccess() || !order.getId().equals(result.getOutTradeNo())
                        || result.getQrCode() == null || !result.getQrCode().startsWith("https://qr.alipay.com/")) {
                    throw new IllegalStateException("Alipay precreate failed");
                }
                nativeQrCode = result.getQrCode();
                returnUrl = returnUrl.replace("&qrCode=undefined", "&qrCode="
                        + java.net.URLEncoder.encode(nativeQrCode, "UTF-8"));
            } catch (Exception error) {
                throw new IllegalStateException("Alipay precreate failed", error);
            }
        }

'''+marker,1)
    channel = channel.replace('                .qrCodeUrl(qrUrl)', '                .qrCode(nativeQrCode)\n                .qrCodeUrl(qrUrl)',1)
    channel = channel.replace('        HttpUtil.post(notifyUrl, com.alibaba.fastjson2.JSONObject.toJSONString(params));', '''        String acknowledgement = HttpUtil.post(notifyUrl, com.alibaba.fastjson2.JSONObject.toJSONString(params));
        if (!"success".equals(acknowledgement.trim())) {
            throw new IllegalStateException("SaaS receipt was not acknowledged");
        }''',1)
    before = before.replace('throw new RuntimeException("订单已完成，无需重复通过");', 'return 1;',1)
    before = before.replace('            callbackFaka(pay.getNotifyUrl(),pay.getId(),pay.getMoney(),pay.getPayNum());', '''            callbackFaka(pay.getNotifyUrl(),pay.getId(),pay.getMoney(),pay.getPayNum());
            pay.setState(OrderStatesEnum.SUCCESS_PAY.getState());
            orderMapper.updateById(pay);''',1)
    service.write_text(before+channel,encoding='utf-8')
    controller = java / 'controller/AlipayController.java'
    text = controller.read_text(encoding='utf-8')
    text = text.replace('        orderService.addOrder(pay);', '''        // OpenAPI orders are created by the signed endpoint; never recreate them here.
        if (pay.getId() != null && orderService.getOrderById(pay.getId()) != null) {
            return ResponseVO.errorResponse("Order already exists; use its original QR code");
        }
        orderService.addOrder(pay);''',1)
    old='''        if(response != null&&response.isSuccess()&&"TRADE_SUCCESS".equals(response.getTradeStatus())){
            orderService.pass(out_trade_no);'''
    assert old in text
    text = text.replace(old,'''        Order stored = orderService.getOrderById(out_trade_no);
        if (response != null && response.isSuccess() && stored != null
                && out_trade_no.equals(response.getOutTradeNo())
                && ("TRADE_SUCCESS".equals(response.getTradeStatus()) || "TRADE_FINISHED".equals(response.getTradeStatus()))
                && response.getTotalAmount() != null
                && new java.math.BigDecimal(response.getTotalAmount()).compareTo(stored.getMoney()) == 0) {
            orderService.pass(out_trade_no);''',1)
    text = text.replace('            queryOrderState(id);\n            return "success";', '''            ResponseVO<Object> result = queryOrderState(id);
            return result.isOk() && Integer.valueOf(1).equals(result.getData()) ? "success" : "failure";''',1)
    controller.write_text(text,encoding='utf-8')
    # Automatic Alipay checkout does not depend on optional email alerts.
    email = java / 'common/utils/EmailUtils.java'
    text = email.read_text(encoding='utf-8')
    text = text.replace('        log.info("开始给{}发送邮件，标题：{}", sendto, title);', '''        if (sender == null || sender.trim().isEmpty() || sendto == null || sendto.trim().isEmpty()) return;
        log.info("开始给{}发送邮件，标题：{}", sendto, title);''',1)
    email.write_text(text,encoding='utf-8')
    (java/'controller/OpenApiCreditController.java').write_text('''package com.wendao.controller;
import com.wendao.model.ResponseVO;
import com.wendao.model.req.OpenApiOrderReq;
import com.wendao.service.OrderService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping("/api/openapi")
public class OpenApiCreditController {
    @Autowired private OrderService service;
    @Value("${paypro.saas-notify-url:}") private String notifyUrl;
    @PostMapping("/add")
    public ResponseVO<?> create(@Validated @RequestBody OpenApiOrderReq request) {
        if (request.getTimestamp() == null || notifyUrl.isEmpty() || !notifyUrl.equals(request.getNotifyUrl())) {
            return ResponseVO.errorResponse(400, "Invalid timestamp or callback address");
        }
        return ResponseVO.successResponse(service.createOpenApiOrder(request));
    }
}
''',encoding='utf-8')
    # Preserve the pending provider order until a verified SaaS acknowledgment.
    # Polling retries failed delivery after process restarts, within the payment window.
    (java/'common/task/OpenApiAlipayReceipts.java').write_text('''package com.wendao.common.task;
import com.wendao.config.PayProConfig;
import com.wendao.controller.AlipayController;
import com.wendao.entity.Order;
import com.wendao.enums.OrderStatesEnum;
import com.wendao.mapper.OrderMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import java.util.Date;
@Component
public class OpenApiAlipayReceipts {
    @Autowired private OrderMapper mapper;
    @Autowired private AlipayController alipay;
    @Autowired private PayProConfig config;
    @Scheduled(fixedDelay=30000, initialDelay=30000)
    public void retry() {
        if (config.getAlipayDmfAppId() == null || config.getAlipayDmfAppId().trim().isEmpty()) return;
        for (Order order : mapper.selectList(new LambdaQueryWrapper<Order>()
                .eq(Order::getOrderSource, "OPENAPI").eq(Order::getPayType, "alipay_dmf")
                .eq(Order::getState, OrderStatesEnum.WAIT_PAY.getState())
                .gt(Order::getExpireTime, new Date()).last("LIMIT 10"))) {
            try { alipay.queryOrderState(order.getId()); }
            catch (Exception ignored) { /* Keep persistent order pending for the next attempt. */ }
        }
    }
}
''',encoding='utf-8')
    jobs = java/'common/task/Jobs.java'
    text = jobs.read_text(encoding='utf-8').replace('        for(Order p : list1){','        for(Order p : list1){\n            if ("OPENAPI".equals(p.getOrderSource())) continue;',1)
    jobs.write_text(text,encoding='utf-8')


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    prepare(parser.parse_args().source)
