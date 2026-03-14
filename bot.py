import os
import json
import requests
import gspread
import base64
import time
import re
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as OauthCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from datetime import datetime, timedelta

# --- CONFIGURAZIONE SEGRETI ---
TELEGRAM_TOKEN      = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID             = os.environ.get("CHAT_ID")
WP_PASSWORD         = os.environ.get("WP_PASSWORD")
GOOGLE_SECRETS      = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
YT2_CLIENT_ID       = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET   = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN   = os.environ.get("YT2_REFRESH_TOKEN")
FB_PAGE_TOKEN       = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID          = os.environ.get("FB_PAGE_ID")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY")

# --- WHATSAPP (WAHA) ---
WAHA_URL            = os.environ.get("WAHA_URL", "http://100.121.235.36:3000")
WAHA_API_KEY        = os.environ.get("WAHA_API_KEY", "immobiliare2024")
WHATSAPP_CHANNEL_ID = os.environ.get("WHATSAPP_CHANNEL_ID", "120363191994943047@newsletter")

WP_USER     = "Antonio Giancani"
WP_API_URL  = "https://www.immobiliaregiancani.it/wp-json/wp/v2/property"
SHEET_ID    = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"
DRIVE_FOLDER_NAME      = "Video_Da_Ripubblicare"
GIORNI_RIPUBBLICAZIONE = 30

# ---------------------------------------------------------------------------
# FUNZIONI DI SUPPORTO
# ---------------------------------------------------------------------------

def validate_secrets():
    required = {
        "GOOGLE_APPLICATION_CREDENTIALS": GOOGLE_SECRETS,
        "YT2_CLIENT_ID": YT2_CLIENT_ID,
        "YT2_REFRESH_TOKEN": YT2_REFRESH_TOKEN,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(f"❌ Variabili mancanti: {', '.join(missing)}")
    print("✅ Secrets validati.")

def pulisci_testo(testo):
    testo = re.sub(r'\*{2,}', '', testo)
    testo = re.sub(r'#{1,6}\s*', '', testo)
    testo = re.sub(r'^(Hook|Opzione \d+.*?|Post Facebook|Testo|Caption)\s*[:\-–]?\s*', '', testo, flags=re.MULTILINE | re.IGNORECASE)
    testo = re.sub(r'\n{3,}', '\n\n', testo)
    return testo.strip()

def get_google_services():
    creds_dict = json.loads(GOOGLE_SECRETS)
    creds_gspread = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"
    ])
    creds_yt = OauthCredentials(
        token=None, refresh_token=YT2_REFRESH_TOKEN,
        client_id=YT2_CLIENT_ID, client_secret=YT2_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token"
    )
    return gspread.authorize(creds_gspread), build('drive', 'v3', credentials=creds_gspread), build('youtube', 'v3', credentials=creds_yt)

# ---------------------------------------------------------------------------
# STRATEGIA WHATSAPP (SOLO TESTO + LINK)
# ---------------------------------------------------------------------------
def send_whatsapp_strategic(tipologia, descrizione, yt_link, fb_link):
    try:
        url = f"{WAHA_URL}/api/sendText"
        headers = {"X-Api-Key": WAHA_API_KEY, "Content-Type": "application/json"}
        
        # Tronca descrizione per WhatsApp
        desc_breve = descrizione[:350] + "..." if len(descrizione) > 350 else descrizione
        
        testo = (f"🎬 *NUOVO VIDEO: {tipologia.upper()}*\n\n"
                 f"{desc_breve}\n\n"
                 f"📺 *Guarda il video completo qui:*\n"
                 f"🔹 YouTube: {yt_link}\n"
                 f"🔹 Facebook: {fb_link}\n\n"
                 f"📍 Favara, Corso Vittorio Veneto 151\n"
                 f"🏠 *Agenzia Giancani*")

        payload = {"session": "default", "chatId": WHATSAPP_CHANNEL_ID, "text": testo}
        requests.post(url, headers=headers, json=payload, timeout=15)
        print("✅ WhatsApp OK")
    except Exception as e:
        print(f"⚠️ WhatsApp bypassato: {e}")

# ... (Qui vanno le funzioni sincronizza_video_da_facebook, posta_su_youtube, ecc. che avevi già) ...
# Assicurati di includerle se non sono qui sotto!

def posta_su_facebook(testo, video_path):
    try:
        url = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/videos"
        with open(video_path, 'rb') as f:
            r = requests.post(url, data={'access_token': FB_PAGE_TOKEN, 'description': testo}, files={'source': f}, timeout=300)
        if r.status_code == 200:
            return f"https://www.facebook.com/{FB_PAGE_ID}/videos/{r.json().get('id')}"
    except: return None

def posta_su_youtube(youtube, file_path, titolo, descrizione):
    try:
        body = {'snippet': {'title': titolo, 'description': descrizione}, 'status': {'privacyStatus': 'public'}}
        res = youtube.videos().insert(part='snippet,status', body=body, media_body=MediaFileUpload(file_path, resumable=True)).execute()
        return f"https://www.youtube.com/watch?v={res['id']}"
    except: return None

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    try:
        validate_secrets()
        gc, drive_service, youtube_service = get_google_services()
        sheet = gc.open_by_key(SHEET_ID).sheet1
        
        # Sincronizzazione (opzionale ogni volta)
        # sincronizza_video_da_facebook(sheet, drive_service)

        records = sheet.get_all_records()
        headers = sheet.row_values(1)
        col_pub_idx = headers.index("Pubblicato") + 1
        
        oggi = datetime.now().date()

        for i, post in enumerate(records, start=2):
            if str(post.get("Pubblicato")).upper() == "SI": continue
            
            nome_file = str(post.get("Nome_File_Video")).strip()
            if not nome_file: continue

            print(f"🚀 Elaborazione: {nome_file}")
            
            # Download da Drive (Semplificato per brevità)
            # ... (usa la tua funzione cerca_id_drive_per_nome) ...
            
            # Simuliamo i link per l'esempio, tu usa le funzioni reali
            # yt_link = posta_su_youtube(...)
            # fb_link = posta_su_facebook(...)
            
            # Esempio Chiamata WhatsApp Strategic
            # send_whatsapp_strategic(post['Tipologia'], post['Descrizione'], yt_link, fb_link)
            
            # Aggiorna Sheet
            # sheet.update_cell(i, col_pub_idx, "SI")
            break
            
    except Exception as e:
        print(f"❌ Errore nel Main: {e}")

if __name__ == "__main__":
    main()
