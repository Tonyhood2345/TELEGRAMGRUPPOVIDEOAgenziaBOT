import os
import json
import requests
import gspread
import io
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as OauthCredentials # <-- Aggiunto per YouTube
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload # <-- Aggiunto per YouTube
from datetime import datetime

# --- VARIABILI SEGRETE PRESE DA GITHUB SECRETS ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")

# --- NUOVE VARIABILI PER IL SECONDO CANALE YOUTUBE ---
YT2_CLIENT_ID = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN = os.environ.get("YT2_REFRESH_TOKEN")

SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"
FOLDER_ID = "1MXYsQjbyswrcYxxTYxE3jrO0RznJRHKD"

def get_credentials():
    if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        print("❌ ERRORE: Variabile GOOGLE_APPLICATION_CREDENTIALS mancante.")
        return None
        
    info = json.loads(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    return Credentials.from_service_account_info(info, scopes=scopes)

def get_youtube_service():
    if not all([YT2_CLIENT_ID, YT2_CLIENT_SECRET, YT2_REFRESH_TOKEN]):
        print("⚠️ Credenziali YouTube 2 mancanti. Salto la pubblicazione su YouTube.")
        return None

    creds = OauthCredentials(
        None,
        client_id=YT2_CLIENT_ID,
        client_secret=YT2_CLIENT_SECRET,
        refresh_token=YT2_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token"
    )
    return build('youtube', 'v3', credentials=creds)

def scarica_video_da_drive(drive_service, nome_file):
    print(f"🔍 Cerco il file '{nome_file}' nella cartella specifica (ID: {FOLDER_ID})...")
    
    query = f"'{FOLDER_ID}' in parents and name = '{nome_file}' and trashed = false"
    risultati = drive_service.files().list(q=query).execute().get('files', [])
    
    if not risultati:
        print(f"❌ ERRORE: File '{nome_file}' non trovato nella cartella specificata.")
        return None
        
    video = risultati[0]
    print(f"📥 Scaricamento del video '{video['name']}' in corso...")
    
    request = drive_service.files().get_media(fileId=video['id'])
    file_path = "video_temp.mp4"
    
    with open(file_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            
    print("✅ Video scaricato con successo!")
    return file_path

def posta_su_youtube(youtube_service, video_path, titolo, descrizione):
    print("🚀 Inizio caricamento sul SECONDO canale YouTube...")
    body = {
        'snippet': {
            'title': titolo,
            'description': descrizione,
            'tags': ['bot', 'video'], # Puoi personalizzarli
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'public' # Impostato su pubblico
        }
    }
    
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype='video/mp4')
    request = youtube_service.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Caricamento YouTube al {int(status.progress() * 100)}%")
            
    print(f"✅ Video caricato su YouTube! ID: {response['id']}")
    return response['id']

def posta_su_telegram(testo, video_path):
    print("🚀 Inviando a Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    
    with open(video_path, 'rb') as video_file:
        files = {'video': video_file}
        # Gestione sicura dei 1024 caratteri
        caption_tg = testo[:1024] if len(testo) > 1024 else testo
        data = {'chat_id': CHAT_ID, 'caption': caption_tg, 'parse_mode': 'HTML'}
        r = requests.post(url, files=files, data=data)
        
    return r.status_code == 200, r.text

def posta_su_facebook(testo, video_path):
    print("🚀 Inviando a Facebook...")
    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/videos"
    
    with open(video_path, 'rb') as video_file:
        files = {'source': video_file}
        data = {
            'description': testo,
            'access_token': FB_PAGE_TOKEN
        }
        r = requests.post(url, files=files, data=data)
        
    return r.status_code == 200, r.text

def main():
    creds = get_credentials()
    if not creds: return
    
    client_sheets = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    youtube_service = get_youtube_service()
    
    print("🔍 Connessione a Google Sheets...")
    sheet = client_sheets.open_by_key(SHEET_ID).sheet1
    records = sheet.get_all_records()
    
    post_non_pubblicati = []
    for i, row in enumerate(records):
        pubblicato = str(row.get('Pubblicato', '')).strip().upper()
        data_post = str(row.get('Data', '')).strip()
        nome_video_check = str(row.get('Nome_File_Video', '')).strip()
        
        if pubblicato != 'SI' and data_post and nome_video_check:
            post_non_pubblicati.append((i + 2, row))
            
    if not post_non_pubblicati:
        print("✅ Nessun nuovo post CON VIDEO da pubblicare.")
        return

    post_non_pubblicati.sort(key=lambda x: datetime.strptime(x[1]['Data'], "%Y-%m-%d"))
    indice_riga, post = post_non_pubblicati[0]
    
    descrizione_base = post.get('Descrizione', '')
    nome_video = str(post.get('Nome_File_Video', '')).strip()
    
    print(f"🚀 Preparo la pubblicazione (Riga {indice_riga}) con file {nome_video}")
    
    # 1. Scarica il video
    video_path = scarica_video_da_drive(drive_service, nome_video)
    if not video_path: return

    # 2. Carica su YouTube (se configurato)
    youtube_link = ""
    if youtube_service:
        # Crea un titolo per YouTube, es: "Video del 2026-03-01"
        titolo_yt = f"Video del {post['Data']}" 
        video_id = posta_su_youtube(youtube_service, video_path, titolo_yt, descrizione_base)
        if video_id:
            youtube_link = f"https://youtu.be/{video_id}"

    # 3. Componi il testo finale con il link YouTube
    testo_finale = descrizione_base
    if youtube_link:
        cta_yt = f"\n\n🔴 Guardalo anche su YouTube 👇\n🔗 {youtube_link}"
        # Tagliamo la descrizione base se è troppo lunga, lasciando spazio al link
        max_len = 1024 - len(cta_yt)
        if len(testo_finale) > max_len:
            testo_finale = testo_finale[:max_len-3] + "..."
        testo_finale += cta_yt

    # 4. Pubblica su Telegram
    tg_ok, tg_resp = posta_su_telegram(testo_finale, video_path)
    if tg_ok: print("✅ Pubblicato su Telegram!")
    else: print(f"❌ Errore Telegram: {tg_resp}")

    # 5. Pubblica su Facebook
    if FB_PAGE_TOKEN and FB_PAGE_ID:
        # A Facebook passiamo lo stesso testo finale (che ora include il link YouTube)
        fb_ok, fb_resp = posta_su_facebook(testo_finale, video_path)
        if fb_ok: print("✅ Pubblicato su Facebook!")
        else: print(f"❌ Errore Facebook: {fb_resp}")
    else:
        fb_ok = False
        
    # 6. Aggiorna il foglio Google
    if tg_ok or fb_ok or youtube_link:
        intestazioni = sheet.row_values(1)
        if "Pubblicato" in intestazioni:
            col_index = intestazioni.index("Pubblicato") + 1
            sheet.update_cell(indice_riga, col_index, "SI")
            print(f"📝 Foglio aggiornato: Riga {indice_riga} marcata come 'SI'.")
            
    # Pulizia
    if os.path.exists(video_path):
        os.remove(video_path)

if __name__ == "__main__":
    main()
