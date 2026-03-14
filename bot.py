import os
import json
import requests
import gspread
from requests.auth import HTTPBasicAuth
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as OauthCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from datetime import datetime

# --- CONFIGURAZIONE ---
WP_USER = "Antonio Giancani"
WP_PASSWORD = os.environ.get("WP_PASSWORD")
WP_API_URL = "https://www.immobiliaregiancani.it/wp-json/wp/v2/property"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
YT2_CLIENT_ID = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN = os.environ.get("YT2_REFRESH_TOKEN")

WAHA_URL = os.environ.get("WAHA_URL", "http://100.121.235.36:3000").strip("/")
WAHA_API_KEY = "immobiliare2024"
WHATSAPP_CHANNEL_ID = "120363191994943047@newsletter"
SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"

# ---------------------------------------------------------------------------
# FUNZIONI DI PUBBLICAZIONE
# ---------------------------------------------------------------------------

def posta_su_facebook(testo, video_path):
    print("🔵 Pubblicazione su Facebook...")
    try:
        url = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/videos"
        with open(video_path, 'rb') as f:
            r = requests.post(url, data={'access_token': FB_PAGE_TOKEN, 'description': testo}, files={'source': f})
        return f"https://www.facebook.com/{FB_PAGE_ID}/videos/{r.json().get('id')}" if r.status_code == 200 else None
    except: return None

def posta_su_youtube(youtube, file_path, titolo, descrizione):
    print("🔴 Pubblicazione su YouTube...")
    try:
        body = {'snippet': {'title': titolo, 'description': descrizione}, 'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}}
        res = youtube.videos().insert(part='snippet,status', body=body, media_body=MediaFileUpload(file_path, resumable=True)).execute()
        return f"https://www.youtube.com/watch?v={res['id']}"
    except: return None

def posta_su_wordpress(titolo, descrizione, yt_url, fb_url):
    print("🌐 Pubblicazione su WordPress (con link social)...")
    try:
        contenuto = f"{descrizione}\n\n"
        if yt_url: contenuto += f"📺 Guarda il video su YouTube: {yt_url}\n"
        if fb_url: contenuto += f"🔵 Segui la nostra pagina Facebook: {fb_url}"
        
        payload = {"title": titolo, "content": contenuto, "status": "publish"}
        r = requests.post(WP_API_URL, json=payload, auth=HTTPBasicAuth(WP_USER, WP_PASSWORD), timeout=20)
        return r.json().get("link") if r.status_code in [200, 201] else "https://www.immobiliaregiancani.it"
    except: return "https://www.immobiliaregiancani.it"

def invia_telegram(testo, yt, fb, wp):
    print("✈️ Invio a Telegram...")
    msg = (f"📢 *NUOVO IMMOBILE PUBBLICATO*\n\n{testo[:200]}...\n\n"
           f"🌐 [Sito Internet]({wp})\n🎥 [YouTube]({yt})\n🔵 [Facebook]({fb})")
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: print("⚠️ Telegram Fail")

def invia_whatsapp(tipo, desc, yt, fb, wp):
    print("🟢 Invio a WhatsApp...")
    try:
        testo = (f"🎬 *{tipo.upper()}*\n\n{desc[:300]}...\n\n"
                 f"🌐 *Sito:* {wp}\n📺 *YouTube:* {yt}\n🔵 *Facebook:* {fb}\n\n🏠 *Agenzia Giancani*")
        requests.post(f"{WAHA_URL}/api/sendText", 
                      headers={"X-Api-Key": WAHA_API_KEY}, 
                      json={"session": "default", "chatId": WHATSAPP_CHANNEL_ID, "text": testo}, timeout=20)
    except: print("⚠️ WhatsApp Fail")

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("🤖 Avvio Bot Giancani...")
    try:
        # Setup Servizi Google
        creds_dict = json.loads(GOOGLE_SECRETS)
        creds_gs = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        creds_yt = OauthCredentials(token=None, refresh_token=YT2_REFRESH_TOKEN, client_id=YT2_CLIENT_ID, client_secret=YT2_CLIENT_SECRET, token_uri="https://oauth2.googleapis.com/token")
        
        gc = gspread.authorize(creds_gs)
        drive_service = build('drive', 'v3', credentials=creds_gs)
        youtube_service = build('youtube', 'v3', credentials=creds_yt)
        
        # Apertura Foglio
        sheet = gc.open_by_key(SHEET_ID).sheet1
        records = sheet.get_all_records() # <--- ORA RECORDS È DEFINITO!
        
        headers = sheet.row_values(1)
        col_pub_idx = headers.index("Pubblicato") + 1

        for i, post in enumerate(records, start=2):
            if str(post.get("Pubblicato")).upper() == "SI": continue
            
            nome_file = str(post.get("Nome_File_Video")).strip()
            if not nome_file: continue

            print(f"🚀 In lavorazione: {nome_file}")
            
            # Download Video
            res = drive_service.files().list(q=f"name = '{nome_file}'").execute()
            files = res.get('files', [])
            if not files:
                print(f"⚠️ File {nome_file} non trovato.")
                continue

            video_local = "video_temp.mp4"
            with open(video_local, "wb") as f:
                f.write(drive_service.files().get_media(fileId=files[0]['id']).execute())

            # SEQUENZA PUBBLICAZIONE
            desc = str(post.get("Descrizione", ""))
            tipo = str(post.get("Tipologia", "Immobile"))
            titolo_pieno = f"Agenzia Giancani - {tipo}"

            # 1. YouTube & Facebook (per i link)
            yt_url = posta_su_youtube(youtube_service, video_local, titolo_pieno, desc)
            fb_url = posta_su_facebook(desc, video_local)
            
            # 2. WordPress (che ora riceve i link sopra)
            wp_url = posta_su_wordpress(titolo_pieno, desc, yt_url, fb_url)
            
            # 3. Messaggistica Finale
            invia_telegram(desc, yt_url, fb_url, wp_url)
            invia_whatsapp(tipo, desc, yt_url, fb_url, wp_url)

            # Aggiorna Sheet
            sheet.update_cell(i, col_pub_idx, "SI")
            if os.path.exists(video_local): os.remove(video_local)
            print(f"✅ Tutto postato per la riga {i}!")
            break # Ne pubblica uno alla volta ad ogni avvio

        print("🏁 Fine procedura.")

    except Exception as e:
        print(f"❌ Errore critico nel Main: {e}")

if __name__ == "__main__":
    main()
