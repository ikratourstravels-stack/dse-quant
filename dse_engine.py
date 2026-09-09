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
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"Failed to send alert: {e}")

def run_dse_engine():
    today = datetime.now().strftime("%Y-%m-%d")
    print("Fetching DSE Market Data...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = "https://www.dsebd.org/latest_share_price_scroll_l.php"

    try:
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code != 200:
            send_telegram_alert(f"⚠️ *DSE ডেটা ফেচ ব্যর্থ: Status {response.status_code}*")
            return

        tables = pd.read_html(StringIO(response.text))
        target_table = None
        for tbl in tables:
            tbl_str = str(tbl.columns)
            if "Trading Code" in tbl_str or "LTP" in tbl_str:
                target_table = tbl
                break

        if target_table is None:
            send_telegram_alert("⚠️ *DSE ডেটা টেবিল ফরম্যাট পরিবর্তন হয়েছে।*")
            return

        df = target_table.copy()
        df.columns = [str(c).strip() for c in df.columns]

        col_map = {}
        for c in df.columns:
            if "Trading Code" in c:
                col_map[c] = "CODE"
            elif "LTP" in c:
                col_map[c] = "LTP"
            elif "High" in c:
                col_map[c] = "HIGH"
            elif "Low" in c:
                col_map[c] = "LOW"
            elif "Close" in c or "YCP" in c:
                col_map[c] = "YCP"
            elif "Change" in c:
                col_map[c] = "CHANGE"
            elif "Value" in c:
                col_map[c] = "VALUE"
            elif "Volume" in c:
                col_map[c] = "VOLUME"

        df = df.rename(columns=col_map)
        
        for num_col in ["LTP", "CHANGE", "VALUE", "VOLUME"]:
            if num_col in df.columns:
                df[num_col] = pd.to_numeric(df[num_col].astype(str).str.replace(",", ""), errors="coerce")

        df = df.dropna(subset=["CODE", "LTP"])

        top_gainers = df.sort_values(by="CHANGE", ascending=False).head(5)
        top_losers = df.sort_values(by="CHANGE", ascending=True).head(5)
        top_value = df.sort_values(by="VALUE", ascending=False).head(5) if "VALUE" in df.columns else None

        msg = f"📊 *DSE Daily Market Summary*\n📅 তারিখ: `{today}`\n"
        msg += "━━━━━━━━━━━━━━━━━━\n"

        msg += "\n🔥 *Top Gainers:*\n"
        for _, r in top_gainers.iterrows():
            msg += f"• `{r['CODE']}`: {r['LTP']} ({r['CHANGE']:+})\n"

        msg += "\n📉 *Top Losers:*\n"
        for _, r in top_losers.iterrows():
            msg += f"• `{r['CODE']}`: {r['LTP']} ({r['CHANGE']:+})\n"

        if top_value is not None:
            msg += "\n💰 *Top Turnover (Value):*\n"
            for _, r in top_value.iterrows():
                msg += f"• `{r['CODE']}`: {r['VALUE']:.1f} mn\n"

        msg += "\n━━━━━━━━━━━━━━━━━━\n🤖 _Automated by DSE Quant Engine_"

        send_telegram_alert(msg)
        print("Market summary sent successfully!")

    except Exception as e:
        send_telegram_alert(f"⚠️ *ইঞ্জিন রান করতে সমস্যা হয়েছে:* `{str(e)[:100]}`")
        print(f"Error: {e}")

if __name__ == "__main__":
    run_dse_engine()
    
