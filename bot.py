import os
import json
import requests
import gspread
import base64
import re
import time
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

# --- FUNZIONI DI SUPPORTO ---

def validate_secrets():
    required = ["GOOGLE_APPLICATION_CREDENTIALS", "YT2_REFRESH_TOKEN", "TELEGRAM_TOKEN", "FB_PAGE_TOKEN"]
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
    try:
        url = f"{WAHA_URL}/api/sendText"
        headers = {"X-Api-Key": WAHA_API_KEY, "Content-Type": "application/json"}
        testo = (f"🎬 *NUOVO VIDEO: {tipologia.upper()}*\n\n"
                 f"{descrizione[:300]}...\n\n"
                 f"📺 *Guarda qui:*\n🔹 YouTube: {yt_link if yt_link else 'Caricamento...'}\n"
                 f"🔹 Facebook: {fb_link if fb_link else 'Vedi sulla pagina'}\n\n"
                 f"🏠 *Agenzia Giancani - Favara*")
        requests.post(url, headers=headers, json={"session": "default", "chatId": WHATSAPP_CHANNEL_ID, "text": testo}, timeout=20)
        print("✅ WhatsApp OK")
    except Exception as e:
        print(f"⚠️ WhatsApp non raggiungibile: {e}")

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
        body = {'snippet': {'title': titolo, 'description': descrizione}, 'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}}
        res = youtube.videos().insert(part='snippet,status', body=body, media_body=MediaFileUpload(file_path, resumable=True)).execute()
        return f"https://www.youtube.com/watch?v={res['id']}"
    except: return None

# --- MAIN ---
def main():
    print("🤖 Avvio Bot Giancani...")
    try:
        validate_secrets()
        gc, drive_service, youtube_service = get_google_services()
        sheet = gc.open_by_key(SHEET_ID).sheet1
        records = sheet.get_all_records()
        
        headers = sheet.row_values(1)
        col_pub_idx = headers.index("Pubblicato") + 1
        
        for i, post in enumerate(records, start=2):
            if str(post.get("Pubblicato")).upper() == "SI":
                continue
            
            nome_file = str(post.get("Nome_File_Video")).strip()
            if not nome_file: continue

            print(f"🚀 In lavorazione: {nome_file}")
            
            # Cerca su Drive
            res = drive_service.files().list(q=f"name = '{nome_file}' and trashed = false").execute()
            files = res.get('files', [])
            if not files:
                print(f"⚠️ File {nome_file} non trovato su Drive.")
                continue
            
            # Download
            video_local = "video.mp4"
            with open(video_local, "wb") as f:
                f.write(drive_service.files().get_media(fileId=files[0]['id']).execute())
            
            # Pubblicazione
            titolo = f"Agenzia Giancani - {post['Tipologia']}"
            desc = str(post.get("Descrizione", ""))
            
            yt_url = posta_su_youtube(youtube_service, video_local, titolo, desc)
            fb_url = posta_su_facebook(desc, video_local)
            
            # WhatsApp Strategico
            send_whatsapp_strategic(post['Tipologia'], desc, yt_url, fb_url)
            
            # Aggiorna Excel
            sheet.update_cell(i, col_pub_idx, "SI")
            print(f"✅ Riga {i} completata!")
            
            if os.path.exists(video_local): os.remove(video_local)
            break # Ne pubblica uno alla volta ogni volta che parte
            
        print("🏁 Fine procedura.")
    except Exception as e:
        print(f"❌ Errore critico: {e}")

if __name__ == "__main__":
    main()
