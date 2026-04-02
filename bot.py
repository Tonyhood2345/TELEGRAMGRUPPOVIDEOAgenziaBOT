import os
import json
import requests
import gspread
import base64
import time
import re
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as OauthCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from datetime import datetime

# --- CONFIGURAZIONE SEGRETI ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
WP_PASSWORD = os.environ.get("WP_PASSWORD")
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
YT2_CLIENT_ID = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN = os.environ.get("YT2_REFRESH_TOKEN")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")

WP_USER = "Antonio Giancani"
WP_API_URL = "https://www.immobiliaregiancani.it/wp-json/wp/v2/property"
SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"
YT_CHANNEL_ID = "UC7jCI1x_cwh_sOrNPJpaKyQ"

# --- UTILS ---
def extract_yt_id(url):
    match = re.search(r"(?:v=|youtu\.be/)([^&]+)", str(url))
    return match.group(1) if match else None

def extract_fb_id(url):
    match = re.search(r"(?:videos/|reel/|posts/)(\d+)", str(url))
    return match.group(1) if match else None

def estrai_data_ora(timestamp_str):
    if not timestamp_str: return datetime.now().strftime("%Y-%m-%d"), "00:00"
    parti = timestamp_str.split('T')
    return parti[0], (parti[1][:5] if len(parti) > 1 else "00:00")

def analizza_testo_annuncio(testo):
    if not testo: return "Altro", "Non specificata", "📢 Altro"
    t = testo.lower()
    # Pulizia firme per evitare falsi positivi sulla città
    firme = ["corso vittorio veneto", "giancani", "immobiliare"]
    t_clean = t
    for f in firme: t_clean = t_clean.replace(f, "")
    
    # Trova Tipologia Immobile
    tipologie = {"villa": "Villa", "appartamento": "Appartamento", "casa singola": "Casa Singola", "terreno": "Terreno"}
    tipo_imm = next((v for k, v in tipologie.items() if k in t_clean), "Altro")
    
    # Trova Città (Mappatura Contrade)
    mappa_citta = {"favara": "Favara", "priolo": "Favara", "agrigento": "Agrigento", "zingarello": "Agrigento", "licata": "Licata", "aragona": "Aragona", "caldare": "Aragona"}
    citta = "Non specificata"
    for k, v in mappa_citta.items():
        if re.search(r'\b' + re.escape(k) + r'\b', t_clean):
            citta = v
            break
            
    # Categoria Post
    cat = "📢 Altro"
    if any(x in t for x in ["ribasso", "occasione", "affare"]): cat = "💰 Ribasso"
    elif any(x in t for x in ["vendita", "vendesi"]): cat = "🏠 Vendita"
    
    return tipo_imm, citta, cat

# --- SERVIZI GOOGLE ---
def get_google_services():
    creds_dict = json.loads(GOOGLE_SECRETS)
    creds_g = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    creds_yt = OauthCredentials(token=None, refresh_token=YT2_REFRESH_TOKEN, client_id=YT2_CLIENT_ID, client_secret=YT2_CLIENT_SECRET, token_uri="https://oauth2.googleapis.com/token")
    return gspread.authorize(creds_g), build('drive', 'v3', credentials=creds_g), build('youtube', 'v3', credentials=creds_yt)

def cerca_id_drive_per_nome(drive_service, nome_file):
    try:
        q = f"name = '{nome_file.replace(chr(39), chr(92)+chr(39))}' and trashed = false"
        res = drive_service.files().list(q=q, fields='files(id, name)', pageSize=1).execute()
        return res.get('files', [])[0]['id'] if res.get('files') else None
    except: return None

# --- PUBBLICAZIONE ---
def posta_su_youtube(youtube, file_path, titolo, desc):
    try:
        body = {'snippet': {'title': titolo, 'description': desc}, 'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}}
        res = youtube.videos().insert(part='snippet,status', body=body, media_body=MediaFileUpload(file_path, resumable=True)).execute()
        return f"https://www.youtube.com/watch?v={res['id']}"
    except: return None

def posta_su_facebook(testo, video_path):
    try:
        url = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/videos"
        with open(video_path, 'rb') as f:
            r = requests.post(url, data={'access_token': FB_PAGE_TOKEN, 'description': testo}, files={'source': f}, timeout=300)
        return f"https://www.facebook.com/{FB_PAGE_ID}/videos/{r.json().get('id')}" if r.status_code == 200 else None
    except: return None

def posta_su_telegram(testo, video_path=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    with open(video_path, "rb") as f:
        requests.post(url, data={"chat_id": CHAT_ID, "caption": testo[:1024], "parse_mode": "HTML"}, files={"video": f})

# --- MAIN ---
def main():
    gc, drive, youtube = get_google_services()
    sheet = gc.open_by_key(SHEET_ID).sheet1
    
    # Fix colonne vuote e caricamento dati
    raw = sheet.get_all_values()
    headers = raw[0]
    col = {n: headers.index(n) for n in headers if n.strip()}
    records = [dict(zip(headers, r + [""]*(len(headers)-len(r)))) for r in raw[1:]]

    # 1. AUTO-DISCOVERY (Cerca post vecchi/nuovi 9 mesi)
    print("🕵️ Discovery post esistenti...")
    link_esistenti = [str(r.get("Link_Facebook", "")) for r in records]
    url_fb = f"https://graph.facebook.com/v18.0/me/published_posts?fields=message,created_time,permalink_url&limit=100&access_token={FB_PAGE_TOKEN}"
    fb_data = requests.get(url_fb).json().get('data', [])
    
    nuove_righe = []
    for p in reversed(fb_data):
        url = p.get('permalink_url', '')
        if url and ("/videos/" in url or "/reel/" in url) and url not in link_esistenti:
            txt = p.get('message', '')
            tipo_i, citta, cat = analizza_testo_annuncio(txt)
            d, o = estrai_data_ora(p.get('created_time'))
            riga = [""] * len(headers)
            if "Tipo" in col: riga[col["Tipo"]] = "POST"
            if "Data" in col: riga[col["Data"]] = d
            if "Ora" in col: riga[col["Ora"]] = o
            if "Tipologia" in col: riga[col["Tipologia"]] = cat
            if "Descrizione" in col: riga[col["Descrizione"]] = txt
            if "Tipologia_Immobile" in col: riga[col["Tipologia_Immobile"]] = tipo_i
            if "Citta" in col: riga[col["Citta"]] = citta
            if "Link_Facebook" in col: riga[col["Link_Facebook"]] = url
            if "Pubblicato" in col: riga[headers.index("Pubblicato")] = "SI" # Segna SI perché già esiste su FB
            nuove_righe.append(riga)

    if nuove_righe:
        sheet.append_rows(nuove_righe)
        print(f"📝 Aggiunti {len(nuove_righe)} post storici.")
        records = [dict(zip(headers, r + [""]*(len(headers)-len(r)))) for r in sheet.get_all_values()[1:]]

    # 2. PUBBLICAZIONE (Solo righe senza "SI" in Colonna Z)
    col_z_idx = 26 # Colonna Z
    for i, r in enumerate(records, start=2):
        if str(r.get("Pubblicato", "")).upper() == "SI": continue
        
        fname = r.get("Nome_File_Video")
        if not fname: continue
        
        fid = cerca_id_drive_per_nome(drive, fname)
        if fid:
            print(f"🎬 Pubblico: {fname}")
            v_path = f"video_{i}.mp4"
            with open(v_path, "wb") as f: f.write(drive.files().get_media(fileId=fid).execute())
            
            yt = posta_su_youtube(youtube, v_path, f"Immobiliare Giancani - {fname}", r.get("Descrizione"))
            fb = posta_su_facebook(r.get("Descrizione"), v_path)
            
            msg = f"🏠 <b>{r.get('Tipologia_Immobile')} a {r.get('Citta')}</b>\n\n{r.get('Descrizione')[:500]}"
            posta_su_telegram(msg, v_path)
            
            sheet.update_cell(i, col_z_idx, "SI")
            if yt and "Link_YouTube" in col: sheet.update_cell(i, col["Link_YouTube"]+1, yt)
            if fb and "Link_Facebook" in col: sheet.update_cell(i, col["Link_Facebook"]+1, fb)
            
            os.remove(v_path)
            break # Uno al giorno

    # 3. STATISTICHE
    agg = []
    for i, r in enumerate(records, start=2):
        fbid = extract_fb_id(r.get("Link_Facebook"))
        if fbid:
            try:
                res = requests.get(f"https://graph.facebook.com/v18.0/{fbid}?fields=views,likes.summary(true),comments.summary(true)&access_token={FB_PAGE_TOKEN}").json()
                agg.append({'range': gspread.utils.rowcol_to_a1(i, col["Visualizzazioni"]+1), 'values': [[res.get('views', 0)]]})
                agg.append({'range': gspread.utils.rowcol_to_a1(i, col["Mi_Piace"]+1), 'values': [[res.get('likes', {}).get('summary', {}).get('total_count', 0)]]})
            except: pass
    if agg: sheet.batch_update(agg)
    print("🎉 Operazioni completate.")

if __name__ == "__main__": main()
