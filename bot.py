import os
import json
import requests
import gspread
import subprocess
import re
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as OauthCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from datetime import datetime

# --- CONFIGURAZIONE ---
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
YT2_CLIENT_ID = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN = os.environ.get("YT2_REFRESH_TOKEN")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"

def modifica_testo_annuncio(testo_originale):
    intro = "🌟 UN GRANDE CLASSICO SEMPRE ATTUALE 🌟\n\n"
    return f"{intro}{testo_originale}\n\n#repost #immobiliaregiancani #favara"

def download_video_fb(url):
    output_filename = "video_riciclo.mp4"
    print(f"📥 Scaricamento video da: {url}")
    try:
        comando = ['yt-dlp', '-f', 'b[ext=mp4]', url, '-o', output_filename, '--force-overwrites']
        subprocess.run(comando, check=True)
        return output_filename if os.path.exists(output_filename) else None
    except Exception as e:
        print(f"❌ Errore download: {e}")
        return None

def get_google_services():
    creds_dict = json.loads(GOOGLE_SECRETS)
    creds_g = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    creds_yt = OauthCredentials(token=None, refresh_token=YT2_REFRESH_TOKEN, client_id=YT2_CLIENT_ID, client_secret=YT2_CLIENT_SECRET, token_uri="https://oauth2.googleapis.com/token")
    return gspread.authorize(creds_g), build('youtube', 'v3', credentials=creds_yt)

def main():
    gc, youtube = get_google_services()
    sheet = gc.open_by_key(SHEET_ID).worksheet("DATABASE_IMMOBILI")
    
    raw = sheet.get_all_values()
    
    # Pulizia estrema degli header per evitare problemi con spazi o a capo invisibili
    headers = [str(h).strip().replace('\n', '').replace('\r', '') for h in raw[0]]
    col = {n: headers.index(n) for n in headers if n}
    
    # Creazione dei record allineati
    records = []
    for r in raw[1:]:
        # Riempiamo le celle vuote se la riga è più corta degli header
        r_completa = r + [""] * (len(headers) - len(r))
        records.append(dict(zip(headers, r_completa)))

    print(f"🕵️ DIAGNOSTICA: Trovate {len(records)} righe. Colonne riconosciute: {headers}")

    post_da_riciclare = None
    riga_foglio_originale = None 

    for index, r in enumerate(records):
        link_fb = str(r.get("Link_Facebook", "")).strip()
        pubblicato = str(r.get("Pubblicato", "")).strip().upper()
        
        # Stampa le prime 5 righe per capire cosa legge
        if index < 5:
            print(f"🔍 [Riga {index+2}] -> FB: '{link_fb[:30]}...' | Pubblicato: '{pubblicato}' | Città: '{r.get('Citta', '')}'")

        if link_fb and pubblicato == "SI":
            post_da_riciclare = r
            riga_foglio_originale = index + 2 
            print(f"🎯 TROVATO! Post da riciclare alla riga {riga_foglio_originale}")
            break 

    if post_da_riciclare:
        url_fb_vecchio = post_da_riciclare.get("Link_Facebook")
        testo_vecchio = post_da_riciclare.get("Descrizione", "")
        
        nuovo_testo = modifica_testo_annuncio(testo_vecchio)
        video_temp = download_video_fb(url_fb_vecchio)
        
        if video_temp:
            print(f"✅ Video pronto. Inizio ripubblicazione...")

            # --- FACEBOOK ---
            fb_url = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/videos"
            with open(video_temp, 'rb') as f:
                r_fb = requests.post(fb_url, data={'access_token': FB_PAGE_TOKEN, 'description': nuovo_testo}, files={'source': f})
            
            nuovo_link_fb = ""
            if r_fb.status_code == 200:
                nuovo_link_fb = f"https://www.facebook.com/{FB_PAGE_ID}/videos/{r_fb.json().get('id')}"
                print(f"✅ Facebook: {nuovo_link_fb}")

            # --- YOUTUBE ---
            titolo_yt = f"RIPROPOSTA: {post_da_riciclare.get('Tipologia_Immobile', 'Immobile')} a {post_da_riciclare.get('Citta', 'Favara')}"
            body_yt = {'snippet': {'title': titolo_yt, 'description': nuovo_testo}, 'status': {'privacyStatus': 'public'}}
            res_yt = youtube.videos().insert(part='snippet,status', body=body_yt, media_body=MediaFileUpload(video_temp, resumable=True)).execute()
            nuovo_link_yt = f"https://www.youtube.com/watch?v={res_yt['id']}"
            print(f"✅ YouTube: {nuovo_link_yt}")

            # --- TELEGRAM ---
            tg_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
            with open(video_temp, "rb") as f:
                requests.post(tg_url, data={"chat_id": CHAT_ID, "caption": nuovo_testo[:1024], "parse_mode": "HTML"}, files={"video": f})
            print(f"✅ Telegram inviato.")

            # --- AGGIORNAMENTO EXCEL ---
            col_pubblicato_idx = headers.index("Pubblicato") + 1
            sheet.update_cell(riga_foglio_originale, col_pubblicato_idx, "RICICLATO")
            print(f"🔄 Riga {riga_foglio_originale} impostata a 'RICICLATO'.")

            nuova_riga = [""] * len(headers)
            if "Tipo" in col: nuova_riga[col["Tipo"]] = "POST"
            if "Data" in col: nuova_riga[col["Data"]] = datetime.now().strftime("%Y-%m-%d")
            if "Tipologia" in col: nuova_riga[col["Tipologia"]] = post_da_riciclare.get("Tipologia", "")
            if "Descrizione" in col: nuova_riga[col["Descrizione"]] = nuovo_testo
            if "Tipologia_Immobile" in col: nuova_riga[col["Tipologia_Immobile"]] = post_da_riciclare.get("Tipologia_Immobile", "")
            if "Citta" in col: nuova_riga[col["Citta"]] = post_da_riciclare.get("Citta", "")
            if "Link_Facebook" in col: nuova_riga[col["Link_Facebook"]] = nuovo_link_fb
            if "Link_YouTube" in col: nuova_riga[col["Link_YouTube"]] = nuovo_link_yt
            if "Pubblicato" in col: nuova_riga[col["Pubblicato"]] = "SI" 
            
            sheet.append_row(nuova_riga)
            print(f"📝 Nuova riga aggiunta per il riciclo futuro.")
            
            os.remove(video_temp)
        else:
            print("❌ Errore critico: Impossibile scaricare il video.")
    else:
        print("ℹ️ Nessun vecchio post trovato da riciclare.")

if __name__ == "__main__":
    main()
