import os
import requests
import pandas as pd
from datetime import datetime
from io import StringIO

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
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"Failed to send alert: {e}")

def run_pipeline():
    today = datetime.now()
    day_of_week = today.weekday()  # 4 = Friday, 5 = Saturday

    # শুক্র ও শনিবার মার্কেট বন্ধ থাকলে আগেই নিরাপদ বার্তা পাঠাবে
    if day_of_week in [4, 5]:
        msg = f"ℹ️ *DSE মার্কেট আপডেট*\n\nআজ মার্কেট বন্ধ (সাপ্তাহিক ছুটি)।\nআগামী রবিবার সকাল ১০:০০ টা থেকে পাইপলাইন নিয়মিত ডেটা ট্র্যাক করবে।"
        print("Market closed for weekend.")
        send_telegram_alert(msg)
        return

    url = "https://www.dsebd.org/latest_share_price_scroll_l.php"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.dsebd.org/"
    }

    try:
        response = requests.get(url, headers=headers, timeout=25)
        response.raise_for_status()

        tables = pd.read_html(StringIO(response.text))
        if not tables:
            send_telegram_alert("⚠️ DSE পেজে কোনো ডেটা টেবিল পাওয়া যায়নি।")
            return

        df = tables[0]
        # কলামের সংখ্যা যাচাই ও রিনেম
        if df.shape[1] >= 9:
            df = df.iloc[:, :9]
            df.columns = ["TRADING_CODE", "LTP", "HIGH", "LOW", "CLOSEP", "YCP", "CHANGE", "TRADE", "VALUE"]

            # ডেটা ক্লিনিং
            df["LTP"] = pd.to_numeric(df["LTP"].astype(str).str.replace(',', ''), errors='coerce')
            df["CHANGE"] = pd.to_numeric(df["CHANGE"].astype(str).str.replace(',', ''), errors='coerce')
            df["VALUE"] = pd.to_numeric(df["VALUE"].astype(str).str.replace(',', ''), errors='coerce')

            top_gainers = df.sort_values(by="CHANGE", ascending=False).dropna(subset=["CHANGE"]).head(5)
            
            report = f"📊 *DSE Daily Market Summary*\nতারিখ: {today.strftime('%d-%m-%Y')}\n\n*Top 5 Gainers:*\n"
            for _, row in top_gainers.iterrows():
                report += f"• `{row['TRADING_CODE']}`: {row['LTP']} ({row['CHANGE']:+} TK)\n"

            send_telegram_alert(report)
            print("Summary sent successfully.")
        else:
            send_telegram_alert("⚠️ DSE ডেটা ফরম্যাটে পরিবর্তন এসেছে।")

    except Exception as e:
        err_msg = f"⚠️ *ইঞ্জিন রান করতে সমস্যা হয়েছে:*\n`{str(e)[:150]}`"
        send_telegram_alert(err_msg)
        print(f"Error: {e}")

if __name__ == "__main__":
    run_pipeline()
