"""Read-only release gate. Print missing settings without exposing secrets."""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
import payments


def checks():
    try:
        checkout = payments.checkout_options()
    except Exception:
        checkout = {'price_fen':None,'channels':{'wechat':False,'alipay':False}}
    price = checkout['price_fen']
    rates = [os.getenv(k, '') for k in ('AI_INPUT_PRICE_PER_MILLION','AI_CACHED_PRICE_PER_MILLION','AI_OUTPUT_PRICE_PER_MILLION')]
    try:
        rates_ok = all(value != '' and float(value) >= 0 for value in rates)
    except ValueError:
        rates_ok = False
    return {
        'production_mode': os.getenv('APP_ENV') == 'production',
        'postgresql_configured': os.getenv('DATABASE_URL','').startswith(('postgresql://','postgres://')),
        'dedicated_worker_mode': os.getenv('INLINE_WORKER') == '0',
        'ai_key_configured': bool(os.getenv('OPENAI_API_KEY')),
        'ai_price_configured': rates_ok,
        'ai_budget_configured': bool(os.getenv('AI_DAILY_BUDGET')),
        'https_public_url': os.getenv('PUBLIC_BASE_URL','').startswith('https://'),
        'pro_price_configured': price is not None and price > 0,
        'wechat_configured': checkout['channels']['wechat'],
        'alipay_configured': checkout['channels']['alipay'],
    }


if __name__ == '__main__':
    result = checks()
    print(json.dumps(result, indent=2))
    print('Also verify worker, backup restore and actual payment/receipt review before launch.')
    sys.exit(0 if all(result.values()) else 1)
