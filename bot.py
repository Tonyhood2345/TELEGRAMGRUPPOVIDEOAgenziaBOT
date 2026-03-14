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

# ---------------------------------------------------------------------------
# FUNZIONI DI PUBBLICAZIONE
# ---------------------------------------------------------------------------

def posta_su_facebook(testo, video_path):
    print("🔵 Pubblicazione su Facebook...")
    try:
        url = f"https://graph.facebook.com/v18.0/{os.environ.get('FB_PAGE_ID')}/videos"
        with open(video_path, 'rb') as f:
            r = requests.post(url, data={'access_token': os.environ.get('FB_PAGE_TOKEN'), 'description': testo}, files={'source': f})
        if r.status_code == 200:
            return f"https://www.facebook.com/{os.environ.get('FB_PAGE_ID')}/videos/{r.json().get('id')}"
    except: return None

def posta_su_youtube(youtube, file_path, titolo, descrizione):
    print("🔴 Pubblicazione su YouTube...")
    try:
        body = {'snippet': {'title': titolo, 'description': descrizione}, 'status': {'privacyStatus': 'public'}}
        res = youtube.videos().insert(part='snippet,status', body=body, media_body=MediaFileUpload(file_path, resumable=True)).execute()
        return f"https://www.youtube.com/watch?v={res['id']}"
    except: return None

def posta_su_wordpress(titolo, descrizione, yt_url, fb_url):
    print("🌐 Pubblicazione su WordPress (con link social)...")
    try:
        # Arricchiamo la descrizione con i link dei video per WordPress
        contenuto_completo = f"{descrizione}\n\n"
        if yt_url: contenuto_completo += f"Guarda il video su YouTube: {yt_url}\n"
        if fb_url: contenuto_completo += f"Seguici su Facebook: {fb_url}"
        
        payload = {"title": titolo, "content": contenuto_completo, "status": "publish"}
        r = requests.post(WP_API_URL, json=payload, auth=HTTPBasicAuth(WP_USER, WP_PASSWORD))
        return r.json().get("link") if r.status_code in [200, 201] else "https://www.immobiliaregiancani.it"
    except: return "https://www.immobiliaregiancani.it"

# ... (Funzioni Telegram e WhatsApp restano identiche all'invio finale) ...

# ---------------------------------------------------------------------------
# MAIN (SEQUENZA CORRETTA)
# ---------------------------------------------------------------------------
def main():
    # Setup Google Services (Drive, YouTube, Sheets)
    # ... (Codice di connessione identico) ...
    
    # Ciclo sui record dello Sheet
    for i, post in enumerate(records, start=2):
        if str(post.get("Pubblicato")).upper() == "SI": continue
        
        # 1. DOWNLOAD VIDEO DA DRIVE
        # ... (Codice download identico) ...
        
        video_local = "temp.mp4"
        titolo = f"Agenzia Giancani - {post['Tipologia']}"
        desc = post.get("Descrizione", "")

        # --- ESECUZIONE SEQUENZA RICHIESTA ---
        
        # A. PRIMA: YouTube e Facebook (per avere i link)
        yt_url = posta_su_youtube(youtube_service, video_local, titolo, desc)
        fb_url = posta_su_facebook(desc, video_local)
        
        # B. PENULTIMA: WordPress (che ora può includere yt_url e fb_url)
        wp_url = posta_su_wordpress(titolo, desc, yt_url, fb_url)
        
        # C. INFINE: Telegram e WhatsApp (con il link del sito aggiornato)
        invia_telegram(desc, yt_url, fb_url, wp_url)
        invia_whatsapp(post['Tipologia'], desc, yt_url, fb_url, wp_url)

        # AGGIORNA SHEET
        sheet.update_cell(i, col_pub_idx, "SI")
        break

if __name__ == "__main__":
    main()
