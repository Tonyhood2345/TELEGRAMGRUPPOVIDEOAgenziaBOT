import os
import json
import requests
import gspread
import base64
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as OauthCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from datetime import datetime

# --- CONFIGURAZIONE SEGRETI ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
YT2_CLIENT_ID = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN = os.environ.get("YT2_REFRESH_TOKEN")

# DATI WORDPRESS PER ESSENTIAL REAL ESTATE
WP_USER = "Antonio Giancani" 
WP_PASSWORD = os.environ.get("WP_PASSWORD") 
# Cambiamo l'indirizzo per puntare alle PROPRIETÀ di Essential Real Estate
WP_API_URL = "https://www.immobiliaregiancani.it/wp-json/wp/v2/property"

SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"
FOLDER_ID = "1MXYsQjbyswrcYxxTYxE3jrO0RznJRHKD"

def posta_su_wordpress_ere(titolo, testo, yt_url):
    if not WP_PASSWORD: return None
    try:
        print(f"🚀 Pubblicazione su Essential Real Estate: {titolo}")
        
        # Creiamo un codice HTML più robusto per forzare WordPress a mostrare il video
        video_id = yt_url.split("v=")[-1] if "v=" in yt_url else yt_url.split("/")[-1]
        video_html = f'\n\n<iframe width="560" height="315" src="https://www.youtube.com/embed/{video_id}" frameborder="0" allowfullscreen></iframe>\n\n'
        
        auth_ptr = f"{WP_USER}:{WP_PASSWORD}"
        auth_base64 = base64.b64encode(auth_ptr.encode()).decode()
        headers = {'Authorization': f'Basic {auth_base64}', 'Content-Type': 'application/json'}
        
        # Inviamo il post come "property" (il formato di Essential Real Estate)
        payload = {
            'title': titolo,
            'content': testo + video_html,
            'status': 'publish'
        }
        
        r = requests.post(WP_API_URL, headers=headers, json=payload, timeout=30)
        
        if r.status_code == 201:
            link = r.json().get('link')
            print(f"✅ Immobile creato su ERE: {link}")
            return link
        else:
            print(f"❌ Errore ERE ({r.status_code}): {r.text}")
            return None
    except Exception as e:
        print(f"❌ Errore connessione: {e}")
        return None

# ... (Le altre funzioni scarica_video, posta_su_youtube, posta_su_telegram, posta_su_facebook rimangono uguali) ...

def main():
    # ... (Parte iniziale uguale fino al caricamento YouTube) ...
    # Assumiamo di avere yt_link e video_path pronti
    
    # 1. Caricamento YouTube (già funzionante)
    # 2. Pubblicazione su ESSENTIAL REAL ESTATE
    wp_link = posta_su_wordpress_ere(f"Proposta Immobiliare: {post['Data']}", desc_base, yt_link)

    # 3. Costruzione Testo Social
    testo_finale = desc_base
    if yt_link:
        testo_finale += f"\n\n📺 Video HD su YouTube:\n{yt_link}"
    if wp_link:
        testo_finale += f"\n\n🌐 Scheda completa sul sito:\n{wp_link}"

    # 4. Invio ai Social
    posta_su_telegram(testo_finale, video_path)
    posta_su_facebook(testo_finale, video_path)

    # 5. Aggiornamento Foglio
    # ... (Aggiorna cella con "SI") ...

if __name__ == "__main__":
    main()
