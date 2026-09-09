import os
import requests
import pandas as pd
from datetime import datetime
from io import StringIO

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_alert(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets missing!")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=20)
    except Exception as e:
        print(f"Failed to send alert: {e}")

def run_dse_engine():
    url = "https://www.amarstock.com/data/dse/eod"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            send_telegram_alert(f"⚠️ AmarStock EOD ফেচ ব্যর্থ: Status {response.status_code}")
            return
    except Exception as e:
        send_telegram_alert(f"⚠️ AmarStock ডেটা কানেকশনে ত্রুটি: {e}")
        return

    try:
        df = pd.read_csv(StringIO(response.text))
    except Exception as e:
        send_telegram_alert(f"⚠️ CSV পার্সিং ব্যর্থ: {e}")
        return

    df.columns = [c.strip().lower() for c in df.columns]

    numeric_cols = ['close', 'high', 'low', 'ltp', 'volume', 'value']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    df['price'] = df['ltp'] if 'ltp' in df.columns else df['close']
    
    if 'value' in df.columns:
        df['turnover_cr'] = df['value'] / 10000000.0
    else:
        df['turnover_cr'] = 0.0

    spread = df['high'] - df['low']
    df['clv'] = 0.0
    valid_spread = spread > 0
    df.loc[valid_spread, 'clv'] = ((df['price'] - df['low']) - (df['high'] - df['price'])) / spread

    # Engine 1: Momentum / Breakout
    e1_hits = df[(df['clv'] >= 0.65) & (df['turnover_cr'] >= 3.0)]

    # Engine 2: Accumulation Zone
    e2_hits = df[(df['clv'] >= 0.35) & (df['clv'] < 0.65) & (df['turnover_cr'] >= 1.5)]

    today_str = datetime.now().strftime("%Y-%m-%d")
    report = [f"📊 *DSE Quant Analysis - {today_str}*\n"]

    report.append("🚀 *[Engine 1: Momentum/Breakout]*")
    if not e1_hits.empty:
        for _, row in e1_hits.head(10).iterrows():
            sym = row.get('trading_code', row.get('symbol', 'UNKNOWN'))
            report.append(f"• `{sym}`: Price {row['price']:.1f} | CLV {row['clv']:.2f} | Turn {row['turnover_cr']:.2f} Cr")
    else:
        report.append("কোনো সিগন্যাল পাওয়া যায়নি।")

    report.append("\n📦 *[Engine 2: Accumulation Zone]*")
    if not e2_hits.empty:
        for _, row in e2_hits.head(10).iterrows():
            sym = row.get('trading_code', row.get('symbol', 'UNKNOWN'))
            report.append(f"• `{sym}`: Price {row['price']:.1f} | CLV {row['clv']:.2f} | Turn {row['turnover_cr']:.2f} Cr")
    else:
        report.append("কোনো সিগন্যাল পাওয়া যায়নি।")

    send_telegram_alert("\n".join(report))

if __name__ == "__main__":
    run_dse_engine()
  
