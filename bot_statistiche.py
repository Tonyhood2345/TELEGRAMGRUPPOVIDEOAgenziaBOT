import os
import json
import requests
import gspread
import re
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as OauthCredentials
from googleapiclient.discovery import build
from datetime import datetime

# --- CONFIGURAZIONE ---
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
YT2_CLIENT_ID = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN = os.environ.get("YT2_REFRESH_TOKEN")
SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"

def estrai_ticket(testo):
    match = re.search(r'\b([A-Z0-9]+-[0-9]+)\b', testo, re.IGNORECASE)
    return match.group(1).upper() if match else ""

def analizza_testo_annuncio(testo):
    if not testo: return "Altro", "Non specificata", "📢 Altro"
    t = testo.lower()
    tipologies = {"villa": "Villa", "appartamento": "Appartamento", "casa singola": "Casa Singola", "terreno": "Terreno"}
    tipo_imm = next((v for k, v in tipologies.items() if k in t), "Altro")
    mappa_citta = {"favara": "Favara", "agrigento": "Agrigento", "licata": "Licata", "aragona": "Aragona"}
    citta = next((v for k, v in mappa_citta.items() if re.search(r'\b' + re.escape(k) + r'\b', t)), "Non specificata")
    cat = "🏠 Vendita" if any(x in t for x in ["vendita", "vendesi"]) else "📢 Altro"
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
    
    # 1. RECUPERO NUOVI LINK DA FACEBOOK (SENZA PUBBLICARE)
    print("🕵️ Controllo nuovi post su Facebook...")
    records = [dict(zip(headers, r + [""]*(len(headers)-len(r)))) for r in raw[1:]]
    link_esistenti = [str(r.get("Link_Facebook", "")) for r in records]
    
    # Leggiamo gli ultimi 100 post (per coprire i mesi scorsi)
    url_fb = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/published_posts?fields=message,created_time,permalink_url&limit=100&access_token={FB_PAGE_TOKEN}"
    fb_data = requests.get(url_fb).json().get('data', [])
    
    for p in reversed(fb_data):
        url = p.get('permalink_url', '')
        if url and ("/videos/" in url or "/reel/" in url) and url not in link_esistenti:
            msg = p.get('message', '')
            tipo_i, citta, cat = analizza_testo_annuncio(msg)
            ticket = estrai_ticket(msg)
            
            # Aggiungiamo la riga "vuota" (senza link YT che non abbiamo creato)
            riga = [""] * len(headers)
            if "Tipo" in col: riga[col["Tipo"]] = "POST"
            if "Data" in col: riga[col["Data"]] = p.get('created_time').split('T')[0]
            if "Descrizione" in col: riga[col["Descrizione"]] = msg
            if "Tipologia_Immobile" in col: riga[col["Tipologia_Immobile"]] = tipo_i
            if "Citta" in col: riga[col["Citta"]] = citta
            if "Link_Facebook" in col: riga[col["Link_Facebook"]] = url
            if "Ticket" in col: riga[col["Ticket"]] = ticket
            
            sheet.append_row(riga)
            print(f"✅ Nuovo annuncio trovato e aggiunto: {ticket if ticket else 'Senza Ticket'}")

    # 2. AGGIORNAMENTO STATISTICHE (Il vero lavoro da commercialista)
    print("📊 Aggiornamento visualizzazioni in corso...")
    # Ricarichiamo i dati dopo le aggiunte
    records = [dict(zip(headers, r + [""]*(len(headers)-len(r)))) for r in sheet.get_all_values()[1:]]
    aggiornamenti = []
    
    for i, r in enumerate(records, start=2):
        visite_tot = 0
        
        # Conta FB
        fbid = re.search(r"(?:videos/|reel/)(\d+)", r.get("Link_Facebook", ""))
        if fbid:
            try:
                res = requests.get(f"https://graph.facebook.com/v18.0/{fbid.group(1)}?fields=views&access_token={FB_PAGE_TOKEN}").json()
                visite_tot += int(res.get('views', 0))
            except: pass

        # Conta YT (se hai messo il link a mano o se esiste)
        ytid = re.search(r"(?:v=|youtu\.be/)([^&]+)", r.get("Link_YouTube", ""))
        if ytid:
            try:
                res = youtube.videos().list(part="statistics", id=ytid.group(1)).execute()
                if res.get('items'):
                    visite_tot += int(res['items'][0]['statistics'].get('viewCount', 0))
            except: pass

        if "Visualizzazioni" in col: 
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, col["Visualizzazioni"]+1), 'values': [[visite_tot]]})

    if aggiornamenti:
        sheet.batch_update(aggiornamenti)
        print(f"✅ Statistiche aggiornate per {len(aggiornamenti)} righe.")

    print("🎉 Il commercialista ha finito ed è andato a dormire.")

if __name__ == "__main__":
    main()
