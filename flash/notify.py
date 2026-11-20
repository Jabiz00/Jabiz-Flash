"""Telegram notifications for paper-only events."""
import os
import requests

class TelegramNotifier:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self.enabled = bool(self.token and self.chat_id)
        self.last_error = ""

    def send(self, message):
        if not self.enabled:
            self.last_error = "Telegram credentials not configured"
            print("[telegram] disabled: required secrets are missing")
            return False
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": message,
                      "disable_web_page_preview": True},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise ValueError("Telegram API did not confirm message delivery")
            self.last_error = ""
            return True
        except (requests.RequestException, ValueError) as exc:
            self.last_error = str(exc)[:240]
            print(f"[telegram] delivery failed: {self.last_error}")
            return False
