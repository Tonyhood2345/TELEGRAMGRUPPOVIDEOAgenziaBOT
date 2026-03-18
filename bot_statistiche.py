import os
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import re

# --- CONFIGURAZIONE ---
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
YT_API_KEY = os.environ.get("YT_API_KEY")

# Usa l'ID del foglio che usi su GitHub per la pubblicazione
SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc" 

def extract_yt_id(url):
    match = re.search(r"v=([a-zA-Z0-9_-]+)", str(url))
    return match.group(1) if match else None

def extract_fb_id(url):
    match = re.search(r"videos/(\d+)", str(url))
    return match.group(1) if match else None

def main():
    print("🦉 Avvio Bot Commercialista Notturno...")
    
    try:
        # Setup Google Sheets
        creds_dict = json.loads(GOOGLE_SECRETS)
        creds_gs = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds_gs)
        
        # Prova ad aprire il foglio (usa sheet1 o 'DATABASE_IMMOBILI')
        sheet = gc.open_by_key(SHEET_ID).sheet1
        
        # Setup YouTube
        youtube = build('youtube', 'v3', developerKey=YT_API_KEY)
        
        records = sheet.get_all_records()
        headers = sheet.row_values(1)
        
        # Trova la posizione esatta delle colonne nel tuo Excel
        try:
            idx_yt = headers.index("Link_YouTube") + 1
            idx_fb = headers.index("Link_Facebook") + 1
            idx_views = headers.index("Visualizzazioni") + 1
            idx_likes = headers.index("Mi_Piace") + 1
            idx_comments = headers.index("Commenti") + 1
            idx_shares = headers.index("Condivisioni") + 1
        except ValueError:
            print("⚠️ Errore: Colonne non trovate! Hai creato le colonne 'Link_YouTube', 'Visualizzazioni', ecc.?")
            return

        aggiornamenti = []
        print("🔄 Inizio la lettura e il conteggio delle statistiche...")
        
        for i, row in enumerate(records, start=2):
            yt_url = str(row.get("Link_YouTube", "")).strip()
            fb_url = str(row.get("Link_Facebook", "")).strip()
            
            if not yt_url and not fb_url:
                continue
                
            tot_views = 0
            tot_likes = 0
            tot_comments = 0
            tot_shares = 0
            
            # --- LEGGI STATISTICHE YOUTUBE ---
            if yt_url:
                yt_id = extract_yt_id(yt_url)
                if yt_id:
                    try:
                        req = youtube.videos().list(part="statistics", id=yt_id)
                        res = req.execute()
                        if res['items']:
                            stats = res['items'][0]['statistics']
                            tot_views += int(stats.get('viewCount', 0))
                            tot_likes += int(stats.get('likeCount', 0))
                            tot_comments += int(stats.get('commentCount', 0))
                    except Exception as e:
                        print(f"⚠️ Errore YT (Riga {i}): {e}")

            # --- LEGGI STATISTICHE FACEBOOK ---
            if fb_url:
                fb_id = extract_fb_id(fb_url)
                if fb_id:
                    try:
                        # Richiede a FB le views, likes, commenti e condivisioni del video
                        url = f"https://graph.facebook.com/v18.0/{fb_id}?fields=views,likes.summary(true),comments.summary(true),shares&access_token={FB_PAGE_TOKEN}"
                        r = requests.get(url).json()
                        
                        tot_views += int(r.get('views', 0))
                        if 'likes' in r:
                            tot_likes += int(r['likes']['summary']['total_count'])
                        if 'comments' in r:
                            tot_comments += int(r['comments']['summary']['total_count'])
                        if 'shares' in r:
                            tot_shares += int(r['shares'].get('count', 0))
                    except Exception as e:
                        print(f"⚠️ Errore FB (Riga {i}): {e}")
                        
            # Prepara il "pacchetto" di aggiornamenti per il foglio Excel
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_views), 'values': [[tot_views]]})
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_likes), 'values': [[tot_likes]]})
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_comments), 'values': [[tot_comments]]})
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_shares), 'values': [[tot_shares]]})
            
            print(f"✅ Riga {i} aggiornata: {tot_views} Views | {tot_likes} Likes | {tot_comments} Commenti | {tot_shares} Condivisioni")

        # Invia tutti gli aggiornamenti al foglio Excel in un colpo solo
        if aggiornamenti:
            sheet.batch_update(aggiornamenti)
            print("🎉 FOGLIO EXCEL AGGIORNATO CON SUCCESSO!")
        else:
            print("Nessun link social trovato per aggiornare le statistiche.")

    except Exception as e:
        print(f"❌ Errore critico nel Bot Spia: {e}")

if __name__ == "__main__":
    main()
