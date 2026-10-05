"""Apply required safety fixes to the local advanced source before deployment."""
from pathlib import Path
import re


def prepare(root):
    java = root / 'src/main/java/com/wendao'
    p = java / 'utils/OpenApiSignUtil.java'
    s = p.read_text(encoding='utf-8')
    s = re.sub(r'\s*log\.(?:info|warn)\([\s\S]*?\);', '', s)
    p.write_text(s, encoding='utf-8')
    p = java / 'controller/AlipayController.java'
    s = p.read_text(encoding='utf-8')
    start = s.index('    @RequestMapping(value = "/alipay/notify"')
    s = s[:start] + '''    @RequestMapping(value = "/alipay/notify", method = RequestMethod.POST)
    @ResponseBody
    public String notify(HttpServletRequest incoming) {
        try {
            Map<String, String> params = new HashMap<>();
            for (Map.Entry<String, String[]> entry : incoming.getParameterMap().entrySet()) {
                if (entry.getValue().length != 1) return "failure";
                params.put(entry.getKey(), entry.getValue()[0]);
            }
            if (!payProConfig.getAlipayDmfAppId().equals(params.get("app_id"))
                    || !"RSA2".equals(params.get("sign_type"))
                    || !com.alipay.api.internal.util.AlipaySignature.rsaCheckV1(
                        params, payProConfig.getAlipayDmfPublicKey(), "GBK", "RSA2")) return "failure";
            String id = params.get("out_trade_no");
            if (id == null || !("TRADE_SUCCESS".equals(params.get("trade_status"))
                    || "TRADE_FINISHED".equals(params.get("trade_status")))) return "failure";
            queryOrderState(id);
            return "success";
        } catch (Exception error) {
            return "failure";
        }
    }
}
'''
    p.write_text(s, encoding='utf-8')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    prepare(parser.parse_args().source)
