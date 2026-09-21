import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from io import StringIO
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_alert(message: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets missing!")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=20)
    except Exception as e:
        print(f"Failed to send alert: {e}")

def run_pipeline():
    target_url = "https://www.dsebd.org/latest_share_price_scroll_l.php"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(target_url, headers=headers, verify=False, timeout=25)
        response.raise_for_status()
        
        tables = pd.read_html(StringIO(response.text))
        if not tables:
            send_telegram_alert("⚠️ DSE ডেটা পেজ পাওয়া যায়নি।")
            return
            
        # সঠিক ডেটা টেবিল নির্বাচন (যেটিতে শেয়ারের তালিকা থাকে)
        df = None
        for t in tables:
            if t.shape[1] >= 8 and len(t) > 10:
                df = t
                break
                
        if df is None:
            send_telegram_alert("⚠️ DSE শেয়ার টেবিল শনাক্ত করা যায়নি।")
            return

        # কলাম বিন্যাস
        if df.shape[1] >= 10:
            df = df.iloc[:, 1:10]
        elif df.shape[1] == 9:
            df = df.iloc[:, 0:9]
            
        df.columns = ['Ticker', 'LTP', 'High', 'Low', 'Close', 'YCP', 'Change', 'Trade', 'Value_mn']

        # অপ্রয়োজনীয় হেডার লাইন বাদ দেওয়া
        df = df[df['Ticker'].astype(str).str.upper() != 'TRADING CODE']

        # সংখ্যা রূপান্তর
        for c in ['High', 'Low', 'Close', 'LTP', 'Value_mn']:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', '').str.strip(), errors='coerce')
        
        df['Close'] = df['Close'].fillna(df['LTP'])
        df['Close'] = np.where(df['Close'] <= 0, df['LTP'], df['Close'])
        
        df = df.dropna(subset=['Close', 'High', 'Low', 'Value_mn'])
        df = df[(df['High'] > 0) & (df['Low'] > 0)]
        
        # কোয়ান্ট হিসাব
        hl_diff = df['High'] - df['Low']
        df['CLV'] = np.where(hl_diff > 0, ((df['Close'] - df['Low']) - (df['High'] - df['Close'])) / hl_diff, 0.0)
        df['Turnover_Cr'] = df['Value_mn'] / 10.0
        df['Spread_%'] = np.where(df['Low'] > 0, (hl_diff / df['Low']) * 100, 0.0)
        
        total_scraped = len(df)
        max_to = df['Turnover_Cr'].max() if not df.empty else 0.0
        
        # ফিল্টারিং
        e1 = df[(df['Turnover_Cr'] >= 0.5) & (df['CLV'] >= 0.50)].sort_values(by='Turnover_Cr', ascending=False).head(5)
        e2 = df[(df['Turnover_Cr'] >= 0.2) & (df['CLV'] >= 0.20) & (df['Spread_%'] <= 8.0)].sort_values(by='Turnover_Cr', ascending=False).head(5)
        traps = df[(df['Turnover_Cr'] >= 1.0) & (df['CLV'] < 0.20)].sort_values(by='Turnover_Cr', ascending=False).head(5)
        
        # বাংলাদেশ সময় নির্ধারণ (UTC+6)
        bd_now = datetime.now(timezone.utc) + timedelta(hours=6)
        now_bd = bd_now.strftime('%d-%b-%Y %I:%M %p')
        
        msg = f"📊 *DSE QUANT ALERT* ({now_bd})\n"
        msg += f"🔍 মোট স্ক্যান করা স্টক: {total_scraped} টি\n"
        msg += f"💰 আজকের সর্বোচ্চ লেনদেন: {max_to:.2f} Cr\n\n"
        
        msg += "🚀 *MOMENTUM CANDIDATES*\n"
        if not e1.empty:
            for _, r in e1.iterrows():
                msg += f"• *{r['Ticker']}* | Cls: {r['Close']} | TO: {r['Turnover_Cr']:.1f}Cr | CLV: {r['CLV']:.2f}\n"
        else:
            msg += "কোনো মোমেন্টাম স্টক মেলেনি।\n"
            
        msg += "\n🎯 *ACCUMULATION WATCHLIST*\n"
        if not e2.empty:
            for _, r in e2.iterrows():
                msg += f"• *{r['Ticker']}* | Cls: {r['Close']} | Sprd: {r['Spread_%']:.1f}% | CLV: {r['CLV']:.2f}\n"
        else:
            msg += "কোনো কম্প্রেশন স্টক মেলেনি।\n"
            
        msg += "\n⚠️ *OPERATOR TRAP / DUMP*\n"
        if not traps.empty:
            for _, r in traps.iterrows():
                msg += f"• *{r['Ticker']}* | Cls: {r['Close']} | TO: {r['Turnover_Cr']:.1f}Cr | CLV: {r['CLV']:.2f} (Weak Close)\n"
                
        send_telegram_alert(msg)
        print("Alert sent successfully!")
        
    except Exception as e:
        error_msg = f"⚠️ ইঞ্জিন রান করতে সমস্যা হয়েছে:\n{str(e)}"
        send_telegram_alert(error_msg)
        print(error_msg)

if __name__ == "__main__":
    run_pipeline()
        
