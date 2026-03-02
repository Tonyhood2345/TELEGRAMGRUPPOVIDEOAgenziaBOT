import os
import json
import requests
import gspread
import base64
import time
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
WP_PASSWORD = os.environ.get("WP_PASSWORD") 

# DATI GOOGLE (Assicurati di caricare il file secrets.json su GitHub)
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")

# CONFIGURAZIONE WORDPRESS
WP_USER = "Antonio Giancani" 
WP_API_URL = "https://www.immobiliaregiancani.it/wp-json/wp/v2/property"

SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"
FOLDER_ID = "1MXYsQjbyswrcYxxTYxE3jrO0RznJRHKD"

# --- FUNZIONI DI SUPPORTO ---

def get_gspread_client():
    creds_dict = json.loads(GOOGLE_SECRETS)
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ])
    return gspread.authorize(creds), creds

def posta_su_wordpress_ere(titolo, testo, yt_url):
    if not WP_PASSWORD: return None
    try:
        print(f"🚀 Pubblicazione su WordPress: {titolo}")
        video_id = yt_url.split("v=")[-1] if "v=" in yt_url else yt_url.split("/")[-1]
        video_html = f'\n\n<iframe width="560" height="315" src="https://www.youtube.com/embed/{video_id}" frameborder="0" allowfullscreen></iframe>\n\n'
        
        auth_ptr = f"{WP_USER}:{WP_PASSWORD}"
        auth_base64 = base64.b64encode(auth_ptr.encode()).decode()
        headers = {'Authorization': f'Basic {auth_base64}', 'Content-Type': 'application/json'}
        
        payload = {
            'title': titolo,
            'content': testo + video_html,
            'status': 'publish'
        }
        r = requests.post(WP_API_URL, headers=headers, json=payload, timeout=30)
        return r.json().get('link') if r.status_code == 201 else None
    except Exception as e:
        print(f"❌ Errore WP: {e}")
        return None

def scarica_video_da_drive(drive_service, file_id, output_name):
    try:
        request = drive_service.files().get_media(fileId=file_id)
        with open(output_name, "wb") as f:
            f.write(request.execute())
        return output_name
    except Exception as e:
        print(f"❌ Errore download Drive: {e}")
        return None

def posta_su_telegram(testo, video_path):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    with open(video_path, "rb") as video:
        requests.post(url, data={"chat_id": CHAT_ID, "caption": testo, "parse_mode": "HTML"}, files={"video": video})

# --- CORE DEL BOT ---

def main():
    client, creds = get_gspread_client()
    drive_service = build('drive', 'v3', credentials=creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    records = sheet.get_all_records()

    print(f"🧐 Controllo {len(records)} righe su Google Sheets...")

    # IL CICLO CHE MANCAVA (Riga 71 risolta)
    for i, post in enumerate(records, start=2): # Partiamo da riga 2 (sotto intestazione)
        # Controlla se è già stato pubblicato
        if str(post.get("Pubblicato", "")).upper() == "SI":
            continue

        print(f"🆕 Elaborazione riga {i}: {post.get('Titolo', 'Senza Titolo')}")

        # Estrai dati dal foglio
        video_id_drive = post.get("ID_Video_Drive")
        desc_base = post.get("Descrizione", "Nuova Proposta Immobiliare")
        data_sheet = post.get("Data", datetime.now().strftime("%d/%m/%Y"))
        video_local = f"video_{i}.mp4"

        # 1. Scarica Video
        if video_id_drive:
            video_path = scarica_video_da_drive(drive_service, video_id_drive, video_local)
        else:
            continue

        if not video_path: continue

        # 2. (SIMULAZIONE) Link YouTube 
        # Qui andrebbe la tua funzione posta_su_youtube(video_path)
        yt_link = "https://www.youtube.com/watch?v=esempio" 

        # 3. PUBBLICAZIONE WORDPRESS (Risolto NameError post['Data'])
        titolo_wp = f"Proposta Immobiliare del {data_sheet}"
        wp_link = posta_su_wordpress_ere(titolo_wp, desc_base, yt_link)

        # 4. COSTRUZIONE TESTO SOCIAL
        testo_social = f"🏠 <b>{titolo_wp}</b>\n\n{desc_base}"
        if yt_link: testo_social += f"\n\n📺 Video HD: {yt_link}"
        if wp_link: testo_social += f"\n\n🌐 Dettagli: {wp_link}"

        # 5. INVIO SOCIAL
        posta_su_telegram(testo_social, video_path)
        # posta_su_facebook(testo_social, video_path) # Attiva se configurato

        # 6. AGGIORNAMENTO FOGLIO (Autonomia)
        # Supponendo che "Pubblicato" sia nella Colonna E (indice 5)
        # sheet.update_cell(i, 5, "SI") 
        print(f"✅ Riga {i} completata!")

        # Pulizia file temporaneo
        if os.path.exists(video_local):
            os.remove(video_local)

if __name__ == "__main__":
    main()
