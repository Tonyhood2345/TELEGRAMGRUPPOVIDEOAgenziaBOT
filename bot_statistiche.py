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
YT_API_KEY = os.environ.get("YT_API_KEY")
YT2_CLIENT_ID = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN = os.environ.get("YT2_REFRESH_TOKEN")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"
YT_CHANNEL_ID = "UC7jCI1x_cwh_sOrNPJpaKyQ"

def download_video_fb(url):
    """Scarica il video da Facebook usando yt-dlp"""
    output_filename = "video_scaricato.mp4"
    print(f"📥 Tentativo di download video da: {url}")
    try:
        # Comando per scaricare il video alla massima qualità mp4
        comando = [
            'yt-dlp', 
            '-f', 'b[ext=mp4]', 
            url, 
            '-o', output_filename,
            '--force-overwrites'
        ]
        subprocess.run(comando, check=True)
        if os.path.exists(output_filename):
            print("✅ Video scaricato con successo.")
            return output_filename
    except Exception as e:
        print(f"❌ Errore durante il download del video: {e}")
    return None

def analizza_testo_annuncio(testo):
    if not testo: return "Altro", "Non specificata", "📢 Altro"
    t = testo.lower()
    firme = ["corso vittorio veneto", "giancani", "immobiliare"]
    t_clean = t
    for f in firme: t_clean = t_clean.replace(f, "")
    
    tipologie = {"villa": "Villa", "appartamento": "Appartamento", "casa singola": "Casa Singola", "terreno": "Terreno"}
    tipo_imm = next((v for k, v in tipologie.items() if k in t_clean), "Altro")
    
    mappa_citta = {"favara": "Favara", "priolo": "Favara", "agrigento": "Agrigento", "zingarello": "Agrigento", "licata": "Licata", "aragona": "Aragona", "caldare": "Aragona"}
    citta = "Non specificata"
    for k, v in mappa_citta.items():
        if re.search(r'\b' + re.escape(k) + r'\b', t_clean):
            citta = v
            break
            
    cat = "📢 Altro"
    if any(x in t for x in ["ribasso", "occasione", "affare"]): cat = "💰 Ribasso"
    elif any(x in t for x in ["vendita", "vendesi"]): cat = "🏠 Vendita"
    
    return tipo_imm, citta, cat

def get_google_services():
    creds_dict = json.loads(GOOGLE_SECRETS)
    creds_g = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    creds_yt = OauthCredentials(token=None, refresh_token=YT2_REFRESH_TOKEN, client_id=YT2_CLIENT_ID, client_secret=YT2_CLIENT_SECRET, token_uri="https://oauth2.googleapis.com/token")
    return gspread.authorize(creds_g), build('youtube', 'v3', credentials=creds_yt)

def posta_su_youtube(youtube, file_path, titolo, desc):
    try:
        body = {'snippet': {'title': titolo, 'description': desc}, 'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}}
        res = youtube.videos().insert(part='snippet,status', body=body, media_body=MediaFileUpload(file_path, resumable=True)).execute()
        return f"https://www.youtube.com/watch?v={res['id']}"
    except Exception as e:
        print(f"❌ Errore YT: {e}")
        return None

def posta_su_telegram(testo, video_path):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    with open(video_path, "rb") as f:
        requests.post(url, data={"chat_id": CHAT_ID, "caption": testo[:1024], "parse_mode": "HTML"}, files={"video": f})

def main():
    gc, youtube = get_google_services()
    sheet = gc.open_by_key(SHEET_ID).sheet1
    
    raw = sheet.get_all_values()
    headers = raw[0]
    col = {n: headers.index(n) for n in headers if n.strip()}
    records = [dict(zip(headers, r + [""]*(len(headers)-len(r)))) for r in raw[1:]]

    # 1. DISCOVERY NUOVI POST SU FACEBOOK
    print("🕵️ Controllo nuovi post su Facebook...")
    link_esistenti = [str(r.get("Link_Facebook", "")) for r in records]
    url_fb = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/published_posts?fields=message,created_time,permalink_url&limit=5&access_token={FB_PAGE_TOKEN}"
    fb_data = requests.get(url_fb).json().get('data', [])
    
    for p in reversed(fb_data):
        url = p.get('permalink_url', '')
        if url and ("/videos/" in url or "/reel/" in url) and url not in link_esistenti:
            msg = p.get('message', '')
            tipo_i, citta, cat = analizza_testo_annuncio(msg)
            
            # --- AZIONE: SCARICA E RIPUBBLICA ---
            video_file = download_video_fb(url)
            
            if video_file:
                print(f"🎬 Video scaricato! Inizio la ripubblicazione per: {citta}")
                
                # Carica su YouTube
                titolo_yt = f"Immobiliare Giancani - {tipo_i} a {citta}"
                yt_link = posta_su_youtube(youtube, video_file, titolo_yt, msg)
                
                # Invia su Telegram
                testo_tg = f"🏠 <b>{tipo_i} a {citta}</b>\n\n{msg}"
                posta_su_telegram(testo_tg, video_file)
                
                # Salva riga su Excel
                data_p = p.get('created_time').split('T')[0]
                riga = [""] * len(headers)
                if "Tipo" in col: riga[col["Tipo"]] = "POST"
                if "Data" in col: riga[col["Data"]] = data_p
                if "Tipologia" in col: riga[col["Tipologia"]] = cat
                if "Descrizione" in col: riga[col["Descrizione"]] = msg
                if "Tipologia_Immobile" in col: riga[col["Tipologia_Immobile"]] = tipo_i
                if "Citta" in col: riga[col["Citta"]] = citta
                if "Link_Facebook" in col: riga[col["Link_Facebook"]] = url
                if "Link_YouTube" in col: riga[col["Link_YouTube"]] = yt_link if yt_link else ""
                if "Pubblicato" in col: riga[col["Pubblicato"]] = "SI"
                
                sheet.append_row(riga)
                print(f"✅ Riga aggiunta e segnata SI nella colonna Z.")
                
                os.remove(video_file) # Pulizia
                break # Uno alla volta per sicurezza

    print("🎉 Bot finito.")

if __name__ == "__main__":
    main()
