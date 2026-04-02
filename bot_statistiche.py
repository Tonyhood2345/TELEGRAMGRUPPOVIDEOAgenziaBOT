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

def estrai_ticket(testo):
    """Cerca nel testo un codice ID tipo VEND-001 o Az2-002"""
    match = re.search(r'\b([A-Z0-9]+-[0-9]+)\b', testo, re.IGNORECASE)
    return match.group(1).upper() if match else ""

def download_video_fb(url):
    output_filename = "video_scaricato.mp4"
    print(f"📥 Tentativo di download video da: {url}")
    try:
        comando = ['yt-dlp', '-f', 'b[ext=mp4]', url, '-o', output_filename, '--force-overwrites']
        subprocess.run(comando, check=True)
        return output_filename if os.path.exists(output_filename) else None
    except Exception as e:
        print(f"❌ Errore download video: {e}")
        return None

def analizza_testo_annuncio(testo):
    if not testo: return "Altro", "Non specificata", "📢 Altro"
    t = testo.lower()
    t_clean = t.replace("corso vittorio veneto", "").replace("giancani", "").replace("immobiliare", "")
    tipologie = {"villa": "Villa", "appartamento": "Appartamento", "casa singola": "Casa Singola", "terreno": "Terreno"}
    tipo_imm = next((v for k, v in tipologie.items() if k in t_clean), "Altro")
    mappa_citta = {"favara": "Favara", "agrigento": "Agrigento", "licata": "Licata", "aragona": "Aragona"}
    citta = next((v for k, v in mappa_citta.items() if re.search(r'\b' + re.escape(k) + r'\b', t_clean)), "Non specificata")
    cat = "💰 Ribasso" if any(x in t for x in ["ribasso", "occasione", "affare"]) else "🏠 Vendita" if any(x in t for x in ["vendita", "vendesi"]) else "📢 Altro"
    return tipo_imm, citta, cat

def get_google_services():
    creds_dict = json.loads(GOOGLE_SECRETS)
    creds_g = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    creds_yt = OauthCredentials(token=None, refresh_token=YT2_REFRESH_TOKEN, client_id=YT2_CLIENT_ID, client_secret=YT2_CLIENT_SECRET, token_uri="https://oauth2.googleapis.com/token")
    return gspread.authorize(creds_g), build('youtube', 'v3', credentials=creds_yt)

def main():
    gc, youtube = get_google_services()
    sheet = gc.open_by_key(SHEET_ID).sheet1
    raw = sheet.get_all_values()
    headers = raw[0]
    col = {n: headers.index(n) for n in headers if n.strip()}
    records = [dict(zip(headers, r + [""]*(len(headers)-len(r)))) for r in raw[1:]]

    # 1. SCOPERTA NUOVI POST (Limite alzato a 50)
    print("🕵️ Controllo nuovi post su Facebook...")
    link_esistenti = [str(r.get("Link_Facebook", "")) for r in records]
    url_fb = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/published_posts?fields=message,created_time,permalink_url&limit=50&access_token={FB_PAGE_TOKEN}"
    fb_data = requests.get(url_fb).json().get('data', [])
    
    for p in reversed(fb_data):
        url = p.get('permalink_url', '')
        if url and ("/videos/" in url or "/reel/" in url) and url not in link_esistenti:
            msg = p.get('message', '')
            tipo_i, citta, cat = analizza_testo_annuncio(msg)
            ticket = estrai_ticket(msg)
            
            video_file = download_video_fb(url)
            yt_link = ""
            if video_file:
                print(f"🎬 Pubblicazione su YouTube: {citta}")
                try:
                    body = {'snippet': {'title': f"Immobile a {citta}", 'description': msg}, 'status': {'privacyStatus': 'public'}}
                    res = youtube.videos().insert(part='snippet,status', body=body, media_body=MediaFileUpload(video_file, resumable=True)).execute()
                    yt_link = f"https://www.youtube.com/watch?v={res['id']}"
                    
                    # Telegram
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo", data={"chat_id": CHAT_ID, "caption": msg[:1024]}, files={"video": open(video_file, "rb")})
                except Exception as e: print(f"Errore YT/TG: {e}")
                finally: os.remove(video_file)

            # Salva riga
            riga = [""] * len(headers)
            if "Tipo" in col: riga[col["Tipo"]] = "POST"
            if "Data" in col: riga[col["Data"]] = p.get('created_time').split('T')[0]
            if "Descrizione" in col: riga[col["Descrizione"]] = msg
            if "Tipologia_Immobile" in col: riga[col["Tipologia_Immobile"]] = tipo_i
            if "Citta" in col: riga[col["Citta"]] = citta
            if "Link_Facebook" in col: riga[col["Link_Facebook"]] = url
            if "Link_YouTube" in col: riga[col["Link_YouTube"]] = yt_link
            if "Ticket" in col: riga[col["Ticket"]] = ticket
            
            sheet.append_row(riga)
            print(f"✅ Riga aggiunta per {ticket}")

    # 2. AGGIORNAMENTO STATISTICHE (Visite totali in colonna Visualizzazioni)
    print("📊 Aggiornamento statistiche in corso...")
    records = [dict(zip(headers, r + [""]*(len(headers)-len(r)))) for r in sheet.get_all_values()[1:]]
    aggiornamenti = []
    
    for i, r in enumerate(records, start=2):
        visite_tot = 0
        
        # Visite FB
        fbid = re.search(r"(?:videos/|reel/)(\d+)", r.get("Link_Facebook", ""))
        if fbid:
            try:
                res = requests.get(f"https://graph.facebook.com/v18.0/{fbid.group(1)}?fields=views&access_token={FB_PAGE_TOKEN}").json()
                visite_tot += int(res.get('views', 0))
            except: pass

        # Visite YT
        ytid = re.search(r"(?:v=|youtu\.be/)([^&]+)", r.get("Link_YouTube", ""))
        if ytid:
            try:
                res = youtube.videos().list(part="statistics", id=ytid.group(1)).execute()
                if res.get('items'):
                    visite_tot += int(res['items'][0]['statistics'].get('viewCount', 0))
            except: pass

        # Scrive la somma in Visualizzazioni (Colonna T o dovunque si trovi)
        if "Visualizzazioni" in col: 
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, col["Visualizzazioni"]+1), 'values': [[visite_tot]]})

    if aggiornamenti:
        sheet.batch_update(aggiornamenti)
    print("🎉 Bot finito! Statistiche aggiornate.")

if __name__ == "__main__":
    main()
