import os
import json
import time
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
def determina_tipologia(descrizione):
    desc = str(descrizione).lower()
    if 'villa' in desc or 'villino' in desc: return 'Villa'
    elif 'appartamento' in desc or 'attico' in desc: return 'Appartamento'
    elif 'casale' in desc or 'rustico' in desc: return 'Casale'
    elif 'casa singola' in desc or 'indipendente' in desc: return 'Casa Singola'
    elif 'terreno' in desc or 'lotto' in desc: return 'Terreno'
    elif 'locale' in desc or 'magazzino' in desc or 'negozio' in desc: return 'Commerciale'
    elif 'garage' in desc or 'box' in desc: return 'Garage'
    else: return 'Altro'

# ---------------------------------------------------------------------------
def posta_su_facebook(testo, video_path):
    print("🔵 Pubblicazione su Facebook...")
    try:
        url = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/videos"
        with open(video_path, 'rb') as f:
            r = requests.post(url, data={'access_token': FB_PAGE_TOKEN, 'description': testo}, files={'source': f})
        
        if r.status_code == 200:
            return f"https://www.facebook.com/{FB_PAGE_ID}/videos/{r.json().get('id')}"
        else:
            print(f"⚠️ Errore Facebook: {r.text}")
            return None
    except Exception as e:
        print(f"⚠️ Eccezione Facebook: {e}")
        return None

def posta_su_youtube(youtube, file_path, titolo, descrizione):
    print("🔴 Pubblicazione su YouTube...")
    try:
        body = {'snippet': {'title': titolo, 'description': descrizione}, 'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}}
        res = youtube.videos().insert(part='snippet,status', body=body, media_body=MediaFileUpload(file_path, resumable=True)).execute()
        return f"https://www.youtube.com/watch?v={res['id']}"
    except Exception as e:
        print(f"⚠️ Eccezione YouTube: {e}")
        return None

def posta_su_wordpress(titolo, descrizione, yt_url, fb_url):
    print("🌐 Pubblicazione su WordPress...")
    try:
        contenuto = f"{descrizione}\n\n"
        if yt_url: contenuto += f"📺 Guarda il video su YouTube: {yt_url}\n"
        if fb_url: contenuto += f"🔵 Segui la nostra pagina Facebook: {fb_url}"
        
        payload = {"title": titolo, "content": contenuto, "status": "publish"}
        r = requests.post(WP_API_URL, json=payload, auth=HTTPBasicAuth(WP_USER, WP_PASSWORD), timeout=20)
        
        if r.status_code in [200, 201]:
            return r.json().get("link")
        else:
            print(f"⚠️ Errore WP: {r.text}")
            return "https://www.immobiliaregiancani.it"
    except Exception as e:
        print(f"⚠️ Eccezione WP: {e}")
        return "https://www.immobiliaregiancani.it"

def invia_telegram(testo, yt, fb, wp):
    print("✈️ Invio a Telegram...")
    msg = (f"📢 *NUOVO IMMOBILE PUBBLICATO*\n\n{testo[:200]}...\n\n"
           f"🌐 [Sito Internet]({wp or 'N/D'})\n🎥 [YouTube]({yt or 'N/D'})\n🔵 [Facebook]({fb or 'N/D'})")
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e: 
        print(f"⚠️ Telegram Fail: {e}")

def invia_whatsapp(tipo, desc, yt, fb, wp):
    print("🟢 Invio a WhatsApp...")
    try:
        testo = (f"🎬 *{tipo.upper()}*\n\n{desc[:300]}...\n\n"
                 f"🌐 *Sito:* {wp or 'N/D'}\n📺 *YouTube:* {yt or 'N/D'}\n🔵 *Facebook:* {fb or 'N/D'}\n\n🏠 *Agenzia Giancani*")
        requests.post(f"{WAHA_URL}/api/sendText", 
                      headers={"X-Api-Key": WAHA_API_KEY}, 
                      json={"session": "default", "chatId": WHATSAPP_CHANNEL_ID, "text": testo}, timeout=10)
    except Exception as e: 
        print(f"⚠️ WhatsApp Fail: {e}")

# ---------------------------------------------------------------------------
def get_or_create_col(sheet, headers, col_name):
    """Controlla se la colonna esiste, altrimenti la crea e restituisce l'indice (1-based)."""
    if col_name in headers:
        return headers.index(col_name) + 1
    else:
        new_idx = len(headers) + 1
        sheet.update_cell(1, new_idx, col_name)
        headers.append(col_name)
        return new_idx

def main():
    print("🤖 Avvio Bot Giancani Pubblicatore...")
    try:
        creds_dict = json.loads(GOOGLE_SECRETS)
        creds_gs = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        creds_yt = OauthCredentials(token=None, refresh_token=YT2_REFRESH_TOKEN, client_id=YT2_CLIENT_ID, client_secret=YT2_CLIENT_SECRET, token_uri="https://oauth2.googleapis.com/token")
        
        gc = gspread.authorize(creds_gs)
        drive_service = build('drive', 'v3', credentials=creds_gs)
        youtube_service = build('youtube', 'v3', credentials=creds_yt)
        
        sheet = gc.open_by_key(SHEET_ID).sheet1
        records = sheet.get_all_records()
        headers = sheet.row_values(1)
        
        # Recupera indici colonne in modo sicuro
        col_pub_idx = get_or_create_col(sheet, headers, "Pubblicato")
        col_tipo_idx = get_or_create_col(sheet, headers, "Tipologia_Immobile")
        idx_yt = get_or_create_col(sheet, headers, "Link_YouTube")
        idx_fb = get_or_create_col(sheet, headers, "Link_Facebook")
        idx_wp = get_or_create_col(sheet, headers, "Link_Sito")

        for i, post in enumerate(records, start=2):
            # FIX: strip() elimina gli spazi accidentali come "SI "
            stato_pubblicato = str(post.get("Pubblicato", "")).strip().upper()
            if stato_pubblicato == "SI": 
                continue
            
            nome_file = str(post.get("Nome_File_Video", "")).strip()
            if not nome_file: 
                continue

            print(f"\n🚀 In lavorazione: {nome_file} (Riga {i})")
            
            res = drive_service.files().list(q=f"name = '{nome_file}'").execute()
            files = res.get('files', [])
            if not files:
                print(f"⚠️ File '{nome_file}' non trovato su Drive.")
                continue

            video_local = "video_temp.mp4"
            print("📥 Scaricamento video da Google Drive in corso...")
            with open(video_local, "wb") as f:
                f.write(drive_service.files().get_media(fileId=files[0]['id']).execute())

            desc = str(post.get("Descrizione", ""))
            tipo_calcolato = determina_tipologia(desc)
            titolo_pieno = f"Agenzia Giancani - {tipo_calcolato}"

            # Pubblicazione su tutte le piattaforme
            yt_url = posta_su_youtube(youtube_service, video_local, titolo_pieno, desc)
            fb_url = posta_su_facebook(desc, video_local)
            wp_url = posta_su_wordpress(titolo_pieno, desc, yt_url, fb_url)
            
            invia_telegram(desc, yt_url, fb_url, wp_url)
            invia_whatsapp(tipo_calcolato, desc, yt_url, fb_url, wp_url)

            # AGGIORNAMENTO FOGLIO GOOGLE (con time.sleep per evitare blocchi API)
            print("📝 Aggiornamento del foglio Google con i link...")
            
            # 1. Segna subito come "SI" per evitare ripubblicazioni future in caso di crash
            sheet.update_cell(i, col_pub_idx, "SI")
            time.sleep(1) # Previene l'errore "Quota exceeded" di Google
            
            sheet.update_cell(i, col_tipo_idx, tipo_calcolato)
            
            if yt_url:
                time.sleep(1)
                sheet.update_cell(i, idx_yt, yt_url)
            if fb_url:
                time.sleep(1)
                sheet.update_cell(i, idx_fb, fb_url)
            if wp_url:
                time.sleep(1)
                sheet.update_cell(i, idx_wp, wp_url)
            
            if os.path.exists(video_local): 
                os.remove(video_local)
                
            print(f"✅ Tutto postato, classificato e link salvati per la riga {i}!")
            
            # Esce dal ciclo in modo da farne sempre e solo UNO ad ogni avvio (ideale per cron job)
            break 

        print("🏁 Fine procedura.")

    except Exception as e:
        print(f"❌ Errore critico nel Main: {e}")

if __name__ == "__main__":
    main()
