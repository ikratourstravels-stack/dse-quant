  import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime
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
            
        df = tables[0]
        
        # DSE স্ক্রল পেজের স্ট্যান্ডার্ড ১০টি কলাম পার্সিং
        if df.shape[1] >= 10:
            df = df.iloc[:, 1:10]
            df.columns = ['Ticker', 'LTP', 'High', 'Low', 'Close', 'YCP', 'Change', 'Trade', 'Value_mn']
        elif df.shape[1] >= 9:
            df = df.iloc[:, 0:9]
            df.columns = ['Ticker', 'LTP', 'High', 'Low', 'Close', 'YCP', 'Change', 'Trade', 'Value_mn']
        else:
            send_telegram_alert("⚠️ DSE টেবিল ফরম্যাট পরিবর্তন হয়েছে।")
            return

        # নিউমেরিক কনভার্সন
        for c in ['High', 'Low', 'Close', 'LTP', 'Value_mn']:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', '').str.strip(), errors='coerce')
        
        # Close ফাঁকা থাকলে LTP বসানোর ব্যাকআপ লজিক
        df['Close'] = df['Close'].fillna(df['LTP'])
        df['Close'] = np.where(df['Close'] <= 0, df['LTP'], df['Close'])
        
        # মিসিং বা ইনভ্যালিড রো বাদ দেওয়া
        df = df.dropna(subset=['Close', 'High', 'Low', 'Value_mn'])
        df = df[(df['High'] > 0) & (df['Low'] > 0) & (df['Close'] > 0)]
        
        # কোয়ান্ট মেট্রিক হিসাব
        hl_diff = df['High'] - df['Low']
        df['CLV'] = np.where(hl_diff > 0, ((df['Close'] - df['Low']) - (df['High'] - df['Close'])) / hl_diff, 0.0)
        df['Turnover_Cr'] = df['Value_mn'] / 10.0
        df['Spread_%'] = np.where(df['Low'] > 0, (hl_diff / df['Low']) * 100, 0.0)
        
        # --- অপ্টিমাইজড DSE কোয়ান্ট ফিল্টার (V2.2) ---
        # ইঞ্জিন ১: মোমেন্টাম ব্রেকআউট (TO >= 1.0 Cr, CLV >= +0.60)
        e1 = df[(df['Turnover_Cr'] >= 1.0) & (df['CLV'] >= 0.60)].sort_values(by='Turnover_Cr', ascending=False).head(5)
        
        # ইঞ্জিন ২: বটম অ্যাকুমুলেশন (TO >= 0.4 Cr, CLV >= +0.25, Spread <= 7.5%)
        e2 = df[(df['Turnover_Cr'] >= 0.4) & (df['CLV'] >= 0.25) & (df['Spread_%'] <= 7.5)].sort_values(by='Turnover_Cr', ascending=False).head(5)
        
        # ট্র্যাপ ফিল্টার: টার্নওভার বড় কিন্তু উইক ক্লোজিং (TO >= 2.0 Cr, CLV < 0.25)
        traps = df[(df['Turnover_Cr'] >= 2.0) & (df['CLV'] < 0.25)].sort_values(by='Turnover_Cr', ascending=False).head(5)
        
        msg = f"📊 *DSE QUANT ALERT* ({datetime.now().strftime('%d-%b-%Y')})\n\n"
        
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
        
