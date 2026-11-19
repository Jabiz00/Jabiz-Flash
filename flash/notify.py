import os, requests
class TelegramNotifier:
    def __init__(self):
        self.token=os.getenv("TELEGRAM_BOT_TOKEN","")
        self.chat_id=os.getenv("TELEGRAM_CHAT_ID","")
        self.enabled=bool(self.token and self.chat_id)
    def send(self,message):
        if not self.enabled: return
        try:
            r=requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
              json={"chat_id":self.chat_id,"text":message,"disable_web_page_preview":True},timeout=10)
            r.raise_for_status()
        except requests.RequestException as exc:
            print(f"[telegram] {exc}")
