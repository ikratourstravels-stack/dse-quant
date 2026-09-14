import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from io import StringIO
import urllib3

# SSL সতর্কবার্তা ও ভেরিফিকেশন এরর বন্ধ করার কনফিগ
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        # verify=False যুক্ত করে SSL সার্টিফিকেট জনিত এরর বাইপাস করা হয়েছে
        response = requests.get(target_url, headers=headers, verify=False, timeout=25)
        response.raise_for_status()
        
        tables = pd.read_html(StringIO(response.text))
        df = tables[0] if tables else None
        
        if df is None or df.empty:
            send_telegram_alert("⚠️ DSE ডেটা পাওয়া যায়নি বা মার্কেট বন্ধ রয়েছে।")
            return

        # কলামের নাম পরিষ্কার করা
        df.columns = [str(c).strip() for c in df.columns]
        
        # কলাম রিনেম ও টাইপ কাস্টিং
        col_map = {
            'TRADING CODE': 'Ticker',
            'LTP*': 'LTP',
            'HIGH': 'High',
            'LOW': 'Low',
            'CLOSEP*': 'Close',
            'YCP': 'YCP',
            'TRADE': 'Trade',
            'VALUE (mn)': 'Value_mn',
            'VOLUME': 'Volume'
        }
        df = df.rename(columns=col_map)
        
        for c in ['High', 'Low', 'Close', 'LTP', 'Value_mn', 'Volume', 'YCP']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', ''), errors='coerce')
        
        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume', 'Value_mn'])
        
        # কোয়ান্ট মেট্রিক হিসাব
        hl_diff = df['High'] - df['Low']
        df['CLV'] = np.where(hl_diff > 0, ((df['Close'] - df['Low']) - (df['High'] - df['Close'])) / hl_diff, 0.0)
        df['True_VWAP'] = np.where(df['Volume'] > 0, (df['Value_mn'] * 1e6) / df['Volume'], df['Close'])
        df['Turnover_Cr'] = df['Value_mn'] / 10.0
        df['Spread_%'] = np.where(df['Low'] > 0, (hl_diff / df['Low']) * 100, 0.0)
        
        # ১. ENGINE 1: মোমেন্টাম ফিল্টার (Turnover >= 3 Cr, CLV >= 0.80, Close > VWAP)
        e1 = df[(df['Turnover_Cr'] >= 3.0) & (df['CLV'] >= 0.80) & (df['Close'] > df['True_VWAP'])].head(5)
        
        # ২. ENGINE 2: অ্যাক্যুমুলেশন ফিল্টার (Turnover >= 1 Cr, Spread <= 6.5%, CLV >= 0.40, Close near VWAP)
        vwap_diff = ((df['Close'] - df['True_VWAP']).abs() / df['True_VWAP']) * 100
        e2 = df[(df['Turnover_Cr'] >= 1.0) & (vwap_diff <= 1.5) & (df['CLV'] >= 0.40) & (df['Spread_%'] <= 6.5)].head(5)
        
        # ৩. TRAP ফিল্টার (Turnover >= 3 Cr কিন্তু CLV < 0.40)
        traps = df[(df['Turnover_Cr'] >= 3.0) & (df['CLV'] < 0.40)].head(5)
        
        # রিপোর্ট তৈরি
        msg = f"📊 *DSE QUANT ALERT* ({datetime.now().strftime('%d-%b-%Y')})\n\n"
        
        msg += "🚀 *ENGINE 1: MOMENTUM SIGNALS*\n"
        if not e1.empty:
            for _, r in e1.iterrows():
                msg += f"• *{r['Ticker']}* | Cls: {r['Close']} | TO: {r['Turnover_Cr']:.1f}Cr | CLV: {r['CLV']:.2f} | VWAP: {r['True_VWAP']:.1f}\n"
        else:
            msg += "কোনো মোমেন্টাম ব্রেকআউট পাওয়া যায়নি।\n"
            
        msg += "\n🎯 *ENGINE 2: ACCUMULATION WATCHLIST*\n"
        if not e2.empty:
            for _, r in e2.iterrows():
                msg += f"• *{r['Ticker']}* | Cls: {r['Close']} | Sprd: {r['Spread_%']:.1f}% | CLV: {r['CLV']:.2f}\n"
        else:
            msg += "কোনো টাইট অ্যাক্যুমুলেশন বেস পাওয়া যায়নি।\n"
            
        msg += "\n⚠️ *OPERATOR TRAP / DISTRIBUTION*\n"
        if not traps.empty:
            for _, r in traps.iterrows():
                msg += f"• *{r['Ticker']}* | Cls: {r['Close']} | CLV: {r['CLV']:.2f} (Weak Close)\n"
                
        send_telegram_alert(msg)
        print("Alert sent successfully!")
        
    except Exception as e:
        error_msg = f"⚠️ ইঞ্জিন রান করতে সমস্যা হয়েছে:\n{str(e)}"
        send_telegram_alert(error_msg)
        print(error_msg)

if __name__ == "__main__":
    run_pipeline()
