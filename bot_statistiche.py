import os
import json
import requests
import gspread
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- CONFIGURAZIONE ---
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
YT2_CLIENT_ID = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN = os.environ.get("YT2_REFRESH_TOKEN")

# ID DEL FOGLIO ORIGINALE (dove ci sono fisicamente i dati)
SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"

def get_google_services():
    """Autenticazione a Google Sheets e YouTube"""
    creds_dict = json.loads(GOOGLE_SECRETS)
    creds_g = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    
    # Per le statistiche pubbliche di YouTube spesso basta l'API Key, ma usiamo il tuo setup Oauth
    from google.oauth2.credentials import Credentials as OauthCredentials
    creds_yt = OauthCredentials(token=None, refresh_token=YT2_REFRESH_TOKEN, client_id=YT2_CLIENT_ID, client_secret=YT2_CLIENT_SECRET, token_uri="https://oauth2.googleapis.com/token")
    
    return gspread.authorize(creds_g), build('youtube', 'v3', credentials=creds_yt)

def extract_yt_id(url):
    """Estrae l'ID del video da un link YouTube"""
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
    return match.group(1) if match else None

def extract_fb_id(url):
    """Estrae l'ID del video da un link Facebook"""
    match = re.search(r"videos\/(\d+)", url)
    return match.group(1) if match else None

def main():
    gc, youtube = get_google_services()
    sheet = gc.open_by_key(SHEET_ID).worksheet("Foglio1")    
    raw = sheet.get_all_values()
    headers = [h.strip() for h in raw[0]]
    col = {n: headers.index(n) for n in headers if n}
    records = [dict(zip(headers, r + [""]*(len(headers)-len(r)))) for r in raw[1:]]

    # Identifico le colonne da aggiornare (+1 perché gspread parte da 1 e non da 0)
    col_vis = col.get("Visualizzazioni", -1) + 1
    col_like = col.get("Mi_Piace", -1) + 1
    col_comm = col.get("Commenti", -1) + 1
    col_cond = col.get("Condivisioni", -1) + 1
    col_eng = col.get("Engagement", -1) + 1

    if any(c == 0 for c in [col_vis, col_like, col_comm, col_cond, col_eng]):
        print("❌ Errore: Assicurati che le colonne Visualizzazioni, Mi_Piace, Commenti, Condivisioni, Engagement esistano nel foglio.")
        return

    for index, r in enumerate(records):
        riga_foglio = index + 2  # Riga 1 è l'intestazione
        
        link_fb = r.get("Link_Facebook", "")
        link_yt = r.get("Link_YouTube", "")
        
        # Saltiamo le righe vuote o senza link
        if not link_fb and not link_yt:
            continue
            
        print(f"📊 Aggiornamento statistiche riga {riga_foglio}...")
        
        tot_vis = 0
        tot_like = 0
        tot_comm = 0
        tot_cond = 0

        # --- STATISTICHE YOUTUBE ---
        if link_yt:
            yt_id = extract_yt_id(link_yt)
            if yt_id:
                try:
                    res = youtube.videos().list(part="statistics", id=yt_id).execute()
                    if res["items"]:
                        stats = res["items"][0]["statistics"]
                        tot_vis += int(stats.get("viewCount", 0))
                        tot_like += int(stats.get("likeCount", 0))
                        tot_comm += int(stats.get("commentCount", 0))
                except Exception as e:
                    print(f"  ⚠️ Errore YouTube per riga {riga_foglio}: {e}")

        # --- STATISTICHE FACEBOOK ---
        if link_fb:
            fb_id = extract_fb_id(link_fb)
            if fb_id:
                try:
                    # Endpoint Graph API per ottenere i dati del video
                    url = f"https://graph.facebook.com/v18.0/{fb_id}?fields=views,likes.summary(true),comments.summary(true),shares&access_token={FB_PAGE_TOKEN}"
                    res = requests.get(url).json()
                    
                    tot_vis += res.get("views", 0)
                    if "likes" in res:
                        tot_like += res["likes"]["summary"]["total_count"]
                    if "comments" in res:
                        tot_comm += res["comments"]["summary"]["total_count"]
                    if "shares" in res:
                        tot_cond += res["shares"]["count"]
                except Exception as e:
                    print(f"  ⚠️ Errore Facebook per riga {riga_foglio}: {e}")

        # Calcolo Engagement Totale (somma delle interazioni attive)
        tot_eng = tot_like + tot_comm + tot_cond

        # --- AGGIORNAMENTO FOGLIO GOOGLE ---
        # Aggiorniamo le singole celle per questa riga
        try:
            sheet.update_cell(riga_foglio, col_vis, tot_vis)
            sheet.update_cell(riga_foglio, col_like, tot_like)
            sheet.update_cell(riga_foglio, col_comm, tot_comm)
            sheet.update_cell(riga_foglio, col_cond, tot_cond)
            sheet.update_cell(riga_foglio, col_eng, tot_eng)
            print(f"  ✅ Dati salvati: {tot_vis} Vis | {tot_like} Like | {tot_comm} Comm | {tot_cond} Cond")
        except Exception as e:
            print(f"  ❌ Errore salvataggio su Google Sheets riga {riga_foglio}: {e}")

if __name__ == "__main__":
    print("🚀 Avvio bot aggiornamento statistiche...")
    main()
    print("🏁 Aggiornamento completato.")
