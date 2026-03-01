import os
import json
import requests
import gspread
import io
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as OauthCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from datetime import datetime

# --- CONFIGURAZIONE SEGRETI (GITHUB ACTIONS) ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")

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
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    return Credentials.from_service_account_info(info, scopes=scopes)

def get_youtube_service():
    if not all([YT2_CLIENT_ID, YT2_CLIENT_SECRET, YT2_REFRESH_TOKEN]):
        print("⚠️ Credenziali YouTube 2 mancanti. Salto YouTube.")
        return None
    creds = OauthCredentials(
        None, client_id=YT2_CLIENT_ID, client_secret=YT2_CLIENT_SECRET,
        refresh_token=YT2_REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token"
    )
    return build('youtube', 'v3', credentials=creds)

def scarica_video_da_drive(drive_service, nome_file):
    print(f"🔍 Cerco '{nome_file}' nella cartella {FOLDER_ID}...")
    query = f"'{FOLDER_ID}' in parents and name = '{nome_file}' and trashed = false"
    risultati = drive_service.files().list(q=query).execute().get('files', [])
    if not risultati:
        print(f"❌ ERRORE: File '{nome_file}' non trovato.")
        return None
    video = risultati[0]
    request = drive_service.files().get_media(fileId=video['id'])
    file_path = "video_temp.mp4"
    with open(file_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
    print("✅ Video scaricato da Drive.")
    return file_path

def posta_su_youtube(youtube_service, video_path, titolo, descrizione):
    print("🚀 Caricamento sul SECONDO canale YouTube...")
    body = {
        'snippet': {'title': titolo, 'description': descrizione, 'categoryId': '22'},
        'status': {'privacyStatus': 'public'}
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype='video/mp4')
    request = youtube_service.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
    print(f"✅ YouTube OK! ID: {response['id']}")
    return response['id']

def posta_su_telegram(testo, video_path):
    print("🚀 Invio a Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    with open(video_path, 'rb') as video_file:
        files = {'video': video_file}
        caption_tg = testo[:1020] + "..." if len(testo) > 1024 else testo
        data = {'chat_id': CHAT_ID, 'caption': caption_tg, 'parse_mode': 'HTML'}
        r = requests.post(url, files=files, data=data)
    return r.status_code == 200, r.text

def posta_su_facebook(testo, video_path):
    print("🚀 Invio a Facebook e Instagram...")
    # --- LOG DI CONTROLLO ---
    print(f"📝 TESTO INVIATO A FB:\n{testo}") 
    # ------------------------
    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/videos"
    with open(video_path, 'rb') as video_file:
        files = {'source': video_file}
        data = {'description': testo, 'access_token': FB_PAGE_TOKEN}
        r = requests.post(url, files=files, data=data)
    return r.status_code == 200, r.text

def main():
    creds = get_credentials()
    if not creds: return
    client_sheets = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    youtube_service = get_youtube_service()
    
    sheet = client_sheets.open_by_key(SHEET_ID).sheet1
    records = sheet.get_all_records()
    
    post_non_pubblicati = []
    for i, row in enumerate(records):
        pubblicato = str(row.get('Pubblicato', '')).strip().upper()
        data_p = str(row.get('Data', '')).strip()
        nome_v = str(row.get('Nome_File_Video', '')).strip()
        if pubblicato != 'SI' and data_p and nome_v:
            post_non_pubblicati.append((i + 2, row))
            
    if not post_non_pubblicati:
        print("✅ Nulla da pubblicare.")
        return

    post_non_pubblicati.sort(key=lambda x: datetime.strptime(x[1]['Data'], "%Y-%m-%d"))
    indice_riga, post = post_non_pubblicati[0]
    
    # Assicuriamoci che desc_base sia una stringa pulita
    desc_base = str(post.get('Descrizione', '')).strip()
    nome_video = str(post.get('Nome_File_Video', '')).strip()
    
    video_path = scarica_video_da_drive(drive_service, nome_video)
    if not video_path: return

    # --- CARICAMENTO YOUTUBE ---
    yt_link = ""
    if youtube_service:
        titolo_yt = f"Novità Immobiliare - {post['Data']}" 
        v_id = posta_su_youtube(youtube_service, video_path, titolo_yt, desc_base)
        if v_id: 
            yt_link = f"https://youtu.be/{v_id}"
            print(f"✅ Link generato: {yt_link}")

    # --- COSTRUZIONE TESTO CON LINK ---
    cta_yt = f"\n\n📺 Guarda il video su YouTube 👇\n🔗 {yt_link}" if yt_link else ""
    
    # Testo Telegram
    testo_tg = desc_base
    if yt_link:
        max_tg = 1020 - len(cta_yt)
        testo_tg = (desc_base[:max_tg] + "...") if len(desc_base) > max_tg else desc_base
        testo_tg += cta_yt

    # Testo Facebook (Descrizione completa + Link)
    testo_fb = desc_base + cta_yt

    # --- PUBBLICAZIONE ---
    tg_ok, _ = posta_su_telegram(testo_tg, video_path)
    
    fb_ok = False
    if FB_PAGE_TOKEN and FB_PAGE_ID:
        fb_ok, fb_resp = posta_su_facebook(testo_fb, video_path)
        if fb_ok:
            print("✅ Facebook OK!")
        else:
            print(f"❌ Errore Facebook: {fb_resp}")
        
    # --- AGGIORNAMENTO FOGLIO ---
    if tg_ok or fb_ok or (yt_link != ""):
        headers = sheet.row_values(1)
        if "Pubblicato" in headers:
            col = headers.index("Pubblicato") + 1
            sheet.update_cell(indice_riga, col, "SI")
            print(f"📝 Riga {indice_riga} segnata come SI.")
            
    if os.path.exists(video_path): os.remove(video_path)

if __name__ == "__main__":
    main()
