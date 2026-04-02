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

SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc" 

def extract_yt_id(url):
    match = re.search(r"v=([a-zA-Z0-9_-]+)", str(url))
    return match.group(1) if match else None

def extract_fb_id(url):
    match = re.search(r"(?:videos/|reel/)(\d+)", str(url))
    return match.group(1) if match else None

def main():
    print("🦉 Avvio Bot Statistiche...")
    
    try:
        # Setup Google Sheets
        creds_dict = json.loads(GOOGLE_SECRETS)
        creds_gs = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds_gs)
        sheet = gc.open_by_key(SHEET_ID).sheet1
        
        # Setup YouTube
        youtube = build('youtube', 'v3', developerKey=YT_API_KEY)
        
        records = sheet.get_all_records()
        headers = sheet.row_values(1)
        
        try:
            idx_yt = headers.index("Link_YouTube") + 1
            idx_fb = headers.index("Link_Facebook") + 1
            idx_views = headers.index("Visualizzazioni") + 1
            idx_likes = headers.index("Mi_Piace") + 1
            idx_comments = headers.index("Commenti") + 1
        except ValueError:
            print("⚠️ Errore: Colonne non trovate nel foglio Excel!")
            return

        aggiornamenti = []
        print("🔄 Lettura statistiche in corso...")
        
        for i, row in enumerate(records, start=2):
            yt_url = str(row.get("Link_YouTube", "")).strip()
            fb_url = str(row.get("Link_Facebook", "")).strip()
            
            if not yt_url and not fb_url:
                continue
                
            tot_views, tot_likes, tot_comments = 0, 0, 0
            
            # --- YOUTUBE ---
            if yt_url:
                yt_id = extract_yt_id(yt_url)
                if yt_id:
                    try:
                        req = youtube.videos().list(part="statistics", id=yt_id)
                        res = req.execute()
                        if res.get('items'):
                            stats = res['items'][0]['statistics']
                            tot_views += int(stats.get('viewCount', 0))
                            tot_likes += int(stats.get('likeCount', 0))
                            tot_comments += int(stats.get('commentCount', 0))
                    except Exception:
                        pass # Ignora silenziomente errori YT

            # --- FACEBOOK ---
            if fb_url:
                fb_id = extract_fb_id(fb_url)
                if fb_id:
                    try:
                        # RIMOSSO 'shares' DALLA RICHIESTA PER RISOLVERE L'ERRORE #100
                        url = f"https://graph.facebook.com/v18.0/{fb_id}?fields=views,likes.summary(true),comments.summary(true)&access_token={FB_PAGE_TOKEN}"
                        r = requests.get(url).json()
                        
                        if 'error' not in r:
                            tot_views += int(r.get('views', 0))
                            if 'likes' in r:
                                tot_likes += int(r['likes']['summary']['total_count'])
                            if 'comments' in r:
                                tot_comments += int(r['comments']['summary']['total_count'])
                    except Exception:
                        pass # Ignora se non ha permessi o video non esiste
                        
            # Prepara l'aggiornamento
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_views), 'values': [[tot_views]]})
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_likes), 'values': [[tot_likes]]})
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_comments), 'values': [[tot_comments]]})
            
            print(f"✅ Riga {i}: {tot_views} V | {tot_likes} L | {tot_comments} C")

        # Invia gli aggiornamenti al foglio
        if aggiornamenti:
            sheet.batch_update(aggiornamenti)
            print("🎉 FOGLIO EXCEL AGGIORNATO CON SUCCESSO!")

    except Exception as e:
        print(f"❌ Errore critico nel Bot: {e}")

if __name__ == "__main__":
    main()
