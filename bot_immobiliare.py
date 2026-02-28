import os
import json
import requests
import gspread
import io
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from datetime import datetime

# --- VARIABILI SEGRETE PRESE DA GITHUB SECRETS ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")

SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"
FOLDER_ID = "1MXYsQjbyswrcYxxTYxE3jrO0RznJRHKD" # ID della tua cartella Drive

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

def scarica_video_da_drive(drive_service, nome_file):
    print(f"🔍 Cerco il file '{nome_file}' nella cartella Drive...")
    query = f"'{FOLDER_ID}' in parents and name = '{nome_file}' and trashed = false"
    risultati = drive_service.files().list(q=query).execute().get('files', [])
    
    if not risultati:
        print(f"❌ ERRORE: File '{nome_file}' non trovato in Drive.")
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

def posta_su_telegram(testo, video_path):
    print("🚀 Inviando a Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    
    with open(video_path, 'rb') as video_file:
        files = {'video': video_file}
        # Limite di Telegram per la caption è 1024 caratteri
        data = {'chat_id': CHAT_ID, 'caption': testo[:1000] + "..." if len(testo) > 1024 else testo}
        r = requests.post(url, files=files, data=data)
        
    return r.status_code == 200, r.text

def posta_su_facebook(testo, video_path):
    print("🚀 Inviando a Facebook...")
    # Per i video si usa l'endpoint /videos e il parametro 'description' invece di 'message'
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
    
    print("🔍 Connessione a Google Sheets...")
    sheet = client_sheets.open_by_key(SHEET_ID).sheet1
    records = sheet.get_all_records()
    
    # Trova post da pubblicare
    post_non_pubblicati = []
    for i, row in enumerate(records):
        pubblicato = str(row.get('Pubblicato', '')).strip().upper()
        if pubblicato != 'SI':
            post_non_pubblicati.append((i + 2, row)) # +2 per l'offset di riga in gspread
            
    if not post_non_pubblicati:
        print("✅ Nessun nuovo post da pubblicare. Tutti hanno 'SI'.")
        return

    # Ordina per data e prendi il più vecchio
    post_non_pubblicati.sort(key=lambda x: datetime.strptime(x[1]['Data'], "%Y-%m-%d"))
    indice_riga, post = post_non_pubblicati[0]
    
    descrizione = post.get('Descrizione', '')
    nome_video = post.get('Nome_File_Video', '').strip()
    
    if non nome_video:
        print("❌ ERRORE: La colonna 'Nome_File_Video' è vuota per questo post!")
        return
        
    print(f"🚀 Preparo la pubblicazione del post in data {post['Data']} (Riga {indice_riga})")
    
    # 1. Scarica il video
    video_path = scarica_video_da_drive(drive_service, nome_video)
    if not video_path:
        return # Si ferma se non trova il video

    # 2. Pubblica su Telegram
    tg_ok, tg_resp = posta_su_telegram(descrizione, video_path)
    if tg_ok:
        print("✅ Pubblicato su Telegram!")
    else:
        print(f"❌ Errore Telegram: {tg_resp}")

    # 3. Pubblica su Facebook
    fb_ok, fb_resp = posta_su_facebook(descrizione, video_path)
    if fb_ok:
        print("✅ Pubblicato su Facebook!")
    else:
        print(f"❌ Errore Facebook: {fb_resp}")
        
    # 4. Aggiorna il foglio Google
    if tg_ok or fb_ok:
        intestazioni = sheet.row_values(1)
        if "Pubblicato" in intestazioni:
            col_index = intestazioni.index("Pubblicato") + 1
            sheet.update_cell(indice_riga, col_index, "SI")
            print(f"📝 Foglio aggiornato: Riga {indice_riga} marcata come 'SI'.")
        else:
            print("⚠️ Colonna 'Pubblicato' non trovata! Assicurati che esista alla riga 1.")
            
    # Pulizia file temporaneo
    if os.path.exists(video_path):
        os.remove(video_path)

if __name__ == "__main__":
    main()
