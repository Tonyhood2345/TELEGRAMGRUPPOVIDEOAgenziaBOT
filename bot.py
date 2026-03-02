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
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")

WP_USER = "Antonio Giancani" 
WP_API_URL = "https://www.immobiliaregiancani.it/wp-json/wp/v2/property"
SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"

# --- FUNZIONI DI AUTENTICAZIONE ---

def get_google_services():
    creds_dict = json.loads(GOOGLE_SECRETS)
    creds_gspread = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ])
    
    # Credenziali OAuth2 per YouTube (richiedono refresh token)
    creds_yt = OauthCredentials(
        token=None,
        refresh_token=YT2_REFRESH_TOKEN,
        client_id=YT2_CLIENT_ID,
        client_secret=YT2_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token"
    )
    
    gc = gspread.authorize(creds_gspread)
    drive = build('drive', 'v3', credentials=creds_gspread)
    youtube = build('youtube', 'v3', credentials=creds_yt)
    
    return gc, drive, youtube

# --- FUNZIONI DI PUBBLICAZIONE ---

def posta_su_youtube(youtube, file_path, titolo, descrizione):
    try:
        print(f"🎬 Caricamento su YouTube: {titolo}")
        body = {
            'snippet': {'title': titolo, 'description': descrizione, 'tags': ['immobiliare', 'casa', 'vendita']},
            'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
        }
        insert_request = youtube.videos().insert(
            part='snippet,status',
            body=body,
            media_body=MediaFileUpload(file_path, chunksize=-1, resumable=True)
        )
        response = insert_request.execute()
        return f"https://www.youtube.com/watch?v={response['id']}"
    except Exception as e:
        print(f"❌ Errore YouTube: {e}")
        return None

def posta_su_wordpress_ere(titolo, testo, yt_url):
    if not WP_PASSWORD: return None
    try:
        video_id = yt_url.split("v=")[-1] if "v=" in yt_url else yt_url.split("/")[-1]
        video_html = f'\n\n<iframe width="560" height="315" src="https://www.youtube.com/embed/{video_id}" frameborder="0" allowfullscreen></iframe>\n\n'
        auth_ptr = f"{WP_USER}:{WP_PASSWORD}"
        auth_base64 = base64.b64encode(auth_ptr.encode()).decode()
        headers = {'Authorization': f'Basic {auth_base64}', 'Content-Type': 'application/json'}
        payload = {'title': titolo, 'content': testo + video_html, 'status': 'publish'}
        r = requests.post(WP_API_URL, headers=headers, json=payload, timeout=30)
        return r.json().get('link') if r.status_code == 201 else None
    except Exception as e:
        print(f"❌ Errore WP: {e}")
        return None

# --- CORE DEL BOT ---

def main():
    gc, drive_service, youtube_service = get_google_services()
    sheet = gc.open_by_key(SHEET_ID).sheet1
    records = sheet.get_all_records()

    # Trova l'indice della colonna "Pubblicato" (es. se è la 5ª colonna)
    # È meglio cercarla dinamicamente per evitare errori se sposti le colonne
    headers = sheet.row_values(1)
    try:
        col_pub_idx = headers.index("Pubblicato") + 1
    except ValueError:
        print("❌ Errore: Colonna 'Pubblicato' non trovata nel foglio!")
        return

    for i, post in enumerate(records, start=2):
        if str(post.get("Pubblicato", "")).upper() == "SI":
            continue

        print(f"🆕 Elaborazione riga {i}: {post.get('Titolo', 'Nuova Proposta')}")
        
        video_id_drive = post.get("ID_Video_Drive")
        desc_base = post.get("Descrizione", "")
        data_sheet = post.get("Data", datetime.now().strftime("%d/%m/%Y"))
        titolo_video = f"Casa a Favara - {data_sheet}"
        video_local = f"temp_video_{i}.mp4"

        # 1. Download da Drive
        try:
            request = drive_service.files().get_media(fileId=video_id_drive)
            with open(video_local, "wb") as f:
                f.write(request.execute())
        except Exception as e:
            print(f"❌ Errore download: {e}")
            continue

        # 2. YouTube Reale
        yt_link = posta_su_youtube(youtube_service, video_local, titolo_video, desc_base)
        if not yt_link: continue

        # 3. WordPress (ERE)
        wp_link = posta_su_wordpress_ere(f"Immobile del {data_sheet}", desc_base, yt_link)

        # 4. Social (Telegram esempio)
        testo_social = f"🏠 <b>Nuova Proposta {data_sheet}</b>\n\n{desc_base}\n\n📺 YouTube: {yt_link}"
        if wp_link: testo_social += f"\n🌐 Sito: {wp_link}"
        
        # Funzione invio telegram (assunta definita come nel tuo post)
        # posta_su_telegram(testo_social, video_local)

        # 5. AGGIORNAMENTO FOGLIO (Fondamentale per l'autonomia)
        sheet.update_cell(i, col_pub_idx, "SI")
        print(f"✅ Riga {i} completata e segnata come SI.")

        # Pulizia
        if os.path.exists(video_local): os.remove(video_local)
        time.sleep(5) # Piccola pausa per evitare limiti API

if __name__ == "__main__":
    main()
