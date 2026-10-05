"""Inspect direct-merchant payment settings locally; never call a payment API."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
FIELDS = {
    'wechat': ('WECHAT_APP_ID', 'WECHAT_MCH_ID', 'WECHAT_SERIAL',
               'WECHAT_API_V3_KEY', 'WECHAT_PUBLIC_KEY_ID',
               'WECHAT_PRIVATE_KEY_PATH', 'WECHAT_PUBLIC_KEY_PATH'),
    'alipay': ('ALIPAY_APP_ID', 'ALIPAY_SELLER_ID',
               'ALIPAY_PRIVATE_KEY_PATH', 'ALIPAY_PUBLIC_KEY_PATH'),
}


def valid_key(config, channel, private):
    setting = channel.upper() + ('_PRIVATE_KEY_PATH' if private else '_PUBLIC_KEY_PATH')
    value = config.get(setting)
    if not value:
        return False
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    try:
        data = path.read_bytes()
        key = (serialization.load_pem_private_key(data, password=None) if private
               else serialization.load_pem_public_key(data))
        expected = rsa.RSAPrivateKey if private else rsa.RSAPublicKey
        return isinstance(key, expected) and key.key_size >= 2048
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm):
        return False


def inspect(config, channels):
    base = urlsplit(config.get('PUBLIC_BASE_URL') or '')
    price = config.get('PRO_PRICE_FEN') or ''
    common = {
        'merchant_mode': config.get('PAYMENTS_MODE') == 'merchant',
        'https_base_url': bool(base.scheme == 'https' and base.hostname
                               and not base.username and not base.password
                               and not base.query and not base.fragment
                               and base.path in ('', '/')),
        'pro_price_positive': price.isascii() and price.isdigit() and int(price) > 0,
        'dedicated_worker_mode': config.get('INLINE_WORKER') == '0',
    }
    result = {}
    for channel in channels:
        checks = {name: bool(config.get(name)) for name in FIELDS[channel]}
        checks['rsa_private_key_readable'] = valid_key(config, channel, True)
        checks['rsa_platform_public_key_readable'] = valid_key(config, channel, False)
        if channel == 'wechat':
            checks['api_v3_key_32_bytes'] = len((config.get('WECHAT_API_V3_KEY') or '').encode()) == 32
        else:
            checks['supported_gateway'] = config.get('ALIPAY_GATEWAY', 'https://openapi.alipay.com/gateway.do') in (
                'https://openapi.alipay.com/gateway.do',
                'https://openapi-sandbox.dl.alipaydev.com/gateway.do',
            )
        result[channel] = {'checks': checks, 'local_config_ready': all(checks.values())}
    ready = all(common.values()) and all(value['local_config_ready'] for value in result.values())
    return {'common': common, 'channels': result, 'local_config_ready': ready,
            'live_payment_verified': False,
            'scope': 'Direct merchant adapter only; provider permissions and callback reachability are not verified.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--channel', choices=('wechat', 'alipay', 'both'), default='both')
    args = parser.parse_args()
    config = {**dotenv_values(args.env_file), **os.environ}
    channels = tuple(FIELDS) if args.channel == 'both' else (args.channel,)
    result = inspect(config, channels)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['local_config_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
