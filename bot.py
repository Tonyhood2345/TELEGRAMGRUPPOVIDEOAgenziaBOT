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

# --- CONFIGURAZIONE SEGRETI (GITHUB ACTIONS) ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")

YT2_CLIENT_ID = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN = os.environ.get("YT2_REFRESH_TOKEN")

# DATI WORDPRESS
WP_USER = "Antonio Giancani" 
WP_PASSWORD = os.environ.get("WP_PASSWORD") 
WP_API_URL = "https://www.immobiliaregiancani.it/wp-json/wp/v2/posts"

# ID GOOGLE SHEET E CARTELLA DRIVE
SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"
FOLDER_ID = "1MXYsQjbyswrcYxxTYxE3jrO0RznJRHKD"

def get_credentials():
    if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        print("❌ ERRORE: GOOGLE_APPLICATION_CREDENTIALS mancante.")
        return None
    info = json.loads(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    return Credentials.from_service_account_info(info, scopes=scopes)

def get_youtube_service():
    if not all([YT2_CLIENT_ID, YT2_CLIENT_SECRET, YT2_REFRESH_TOKEN]):
        return None
    creds = OauthCredentials(None, client_id=YT2_CLIENT_ID, client_secret=YT2_CLIENT_SECRET,
                             refresh_token=YT2_REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token")
    return build('youtube', 'v3', credentials=creds)

def scarica_video_da_drive(drive_service, nome_file):
    print(f"🔍 Cerco '{nome_file}' su Drive...")
    query = f"'{FOLDER_ID}' in parents and name = '{nome_file}' and trashed = false"
    risultati = drive_service.files().list(q=query).execute().get('files', [])
    if not risultati:
        print(f"❌ File {nome_file} non trovato.")
        return None
    video = risultati[0]
    request = drive_service.files().get_media(fileId=video['id'])
    file_path = "video_temp.mp4"
    with open(file_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: status, done = downloader.next_chunk()
    print("✅ Video scaricato.")
    return file_path

def posta_su_youtube(youtube_service, video_path, titolo, descrizione):
    print("🚀 Caricamento su YouTube...")
    body = {'snippet': {'title': titolo, 'description': descrizione, 'categoryId': '22'}, 'status': {'privacyStatus': 'public'}}
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype='video/mp4')
    request = youtube_service.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
    response = None
    while response is None: status, response = request.next_chunk()
    print(f"✅ YouTube OK! ID: {response['id']}")
    return response['id']

def posta_su_wordpress(titolo, testo, yt_url):
    if not WP_PASSWORD:
        print("⚠️ WP_PASSWORD non configurata.")
        return None
    try:
        print("🚀 Pubblicazione su WordPress...")
        video_id = yt_url.split("/")[-1]
        video_embed = f'\n\n<figure class="wp-block-embed is-type-video is-provider-youtube"><div class="wp-block-embed__wrapper">https://www.youtube.com/watch?v={video_id}</div></figure>'
        
        auth_ptr = f"{WP_USER}:{WP_PASSWORD}"
        auth_base64 = base64.b64encode(auth_ptr.encode()).decode()
        headers = {'Authorization': f'Basic {auth_base64}', 'Content-Type': 'application/json'}
        
        payload = {'title': titolo, 'content': testo + video_embed, 'status': 'publish'}
        r = requests.post(WP_API_URL, headers=headers, json=payload, timeout=30)
        
        if r.status_code == 201:
            link = r.json().get('link')
            print(f"✅ WordPress OK: {link}")
            return link
        else:
            print(f"❌ Errore WordPress: {r.status_code}")
            return None
    except Exception as e:
        print(f"❌ Errore WP: {e}")
        return None

def posta_su_telegram(testo, video_path):
    print("🚀 Invio a Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    with open(video_path, 'rb') as v:
        caption = testo[:1020] if len(testo) > 1024 else testo
        data = {'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}
        r = requests.post(url, files={'video': v}, data=data)
    return r.status_code == 200

def posta_su_facebook(testo, video_path):
    print("🚀 Invio a Facebook...")
    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/videos"
    with open(video_path, 'rb') as v:
        data = {'description': testo, 'access_token': FB_PAGE_TOKEN}
        r = requests.post(url, files={'source': v}, data=data)
    return r.status_code == 200

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
        if str(row.get('Pubblicato', '')).strip().upper() != 'SI' and row.get('Data') and row.get('Nome_File_Video'):
            post_non_pubblicati.append((i + 2, row))
            
    if not post_non_pubblicati:
        print("✅ Nulla da pubblicare.")
        return

    post_non_pubblicati.sort(key=lambda x: datetime.strptime(str(x[1]['Data']), "%Y-%m-%d"))
    idx, post = post_non_pubblicati[0]
    desc_base = str(post.get('Descrizione', '')).strip()
    nome_video = str(post.get('Nome_File_Video', '')).strip()
    
    video_path = scarica_video_da_drive(drive_service, nome_video)
    if not video_path: return

    # 1. Caricamento YouTube
    yt_link = ""
    if youtube_service:
        v_id = posta_su_youtube(youtube_service, video_path, f"Immobile Giancani - {post['Data']}", desc_base)
        yt_link = f"https://youtu.be/{v_id}"

    # 2. Pubblicazione WordPress
    wp_link = posta_su_wordpress(f"Nuova Proposta Immobiliare: {post['Data']}", desc_base, yt_link)

    # 3. Costruzione Testo Social (CON TUTTI I LINK)
    testo_finale = desc_base
    if yt_link:
        testo_finale += f"\n\n📺 <b>Video HD su YouTube:</b>\n{yt_link}"
    if wp_link:
        testo_finale += f"\n\n🌐 <b>Dettagli sul sito:</b>\n{wp_link}"
    else:
        testo_finale += f"\n\n🌐 <b>Visita il sito:</b>\nhttps://www.immobiliaregiancani.it"

    # 4. Invio ai Social
    posta_su_telegram(testo_finale, video_path)
    posta_su_facebook(testo_finale, video_path)

    # 5. Aggiornamento Foglio
    headers = sheet.row_values(1)
    if "Pubblicato" in headers:
        sheet.update_cell(idx, headers.index("Pubblicato") + 1, "SI")
        print(f"📝 Riga {idx} segnata come SI.")

    if os.path.exists(video_path): os.remove(video_path)

if __name__ == "__main__":
    main()
