import os
import json
import requests
import gspread
import base64
import re
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as OauthCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from datetime import datetime

# --- CONFIGURAZIONE ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
YT2_CLIENT_ID = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN = os.environ.get("YT2_REFRESH_TOKEN")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
WAHA_URL = os.environ.get("WAHA_URL", "http://100.121.235.36:3000")
WAHA_API_KEY = "immobiliare2024"
WHATSAPP_CHANNEL_ID = "120363191994943047@newsletter"
SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"

# --- FUNZIONI DI SUPPORTO (Devono stare PRIMA del main) ---
def validate_secrets():
    """Controlla che i segreti vitali siano presenti."""
    required = ["GOOGLE_APPLICATION_CREDENTIALS", "YT2_REFRESH_TOKEN", "TELEGRAM_TOKEN"]
    for r in required:
        if not os.environ.get(r):
            raise ValueError(f"❌ Manca il segreto: {r}")
    print("✅ Segreti verificati.")

def get_google_services():
    creds_dict = json.loads(GOOGLE_SECRETS)
    creds_gs = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    creds_yt = OauthCredentials(token=None, refresh_token=YT2_REFRESH_TOKEN, client_id=YT2_CLIENT_ID, client_secret=YT2_CLIENT_SECRET, token_uri="https://oauth2.googleapis.com/token")
    return gspread.authorize(creds_gs), build('drive', 'v3', credentials=creds_gs), build('youtube', 'v3', credentials=creds_yt)

def send_whatsapp_strategic(tipologia, descrizione, yt_link, fb_link):
    """Invia il messaggio con i link a WhatsApp."""
    try:
        url = f"{WAHA_URL}/api/sendText"
        headers = {"X-Api-Key": WAHA_API_KEY, "Content-Type": "application/json"}
        testo = (f"🎬 *NUOVO VIDEO: {tipologia.upper()}*\n\n"
                 f"{descrizione[:300]}...\n\n"
                 f"📺 *Guarda qui:*\n🔹 YouTube: {yt_link}\n🔹 Facebook: {fb_link}\n\n"
                 f"🏠 *Agenzia Giancani*")
        requests.post(url, headers=headers, json={"session": "default", "chatId": WHATSAPP_CHANNEL_ID, "text": testo}, timeout=15)
        print("✅ WhatsApp OK")
    except Exception as e:
        print(f"⚠️ WhatsApp bypassato: {e}")

# --- MAIN ---
def main():
    print("🤖 Avvio Bot Giancani...")
    try:
        validate_secrets() # Ora la funzione è definita sopra!
        gc, drive_service, youtube_service = get_google_services()
        # ... resto del tuo codice per scaricare e pubblicare ...
        print("🏁 Fine procedura.")
    except Exception as e:
        print(f"❌ Errore critico: {e}")

if __name__ == "__main__":
    main()
