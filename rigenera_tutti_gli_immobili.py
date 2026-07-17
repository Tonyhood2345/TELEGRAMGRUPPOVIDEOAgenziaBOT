import os
import sys
import json
import gspread
from google.oauth2.service_account import Credentials
import re

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

SPREADSHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"

def get_google_sheets_client():
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_json:
        raise ValueError("Variabile GOOGLE_APPLICATION_CREDENTIALS non definita.")
    creds_dict = json.loads(creds_json)
    return gspread.authorize(Credentials.from_service_account_info(
        creds_dict, 
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    ))

def main():
    try:
        gc = get_google_sheets_client()
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet("Foglio1")
        
        all_vals = ws.get_all_values()
        if not all_vals or len(all_vals) <= 1:
            print("Il foglio è vuoto.")
            return
            
        headers = [h.strip().upper() for h in all_vals[0]]
        print(f"Headers: {headers}")
        
        idx_fb = headers.index("LINK_FACEBOOK")
        idx_yt = headers.index("LINK_YOUTUBE")
        idx_pub = headers.index("PUBBLICATO")
        idx_testo = headers.index("TESTO")
        
        rows = all_vals[1:]
        
        # Filtra e raggruppa
        unique_properties = {}
        
        for idx, row in enumerate(rows, start=2):
            r_len = len(row)
            pub = row[idx_pub].strip().upper() if idx_pub < r_len else ""
            testo = row[idx_testo].strip() if idx_testo < r_len else ""
            fb_url = row[idx_fb].strip() if idx_fb < r_len else ""
            yt_url = row[idx_yt].strip() if idx_yt < r_len else ""
            
            # La proprietà è considerata se è stata pubblicata/riciclata ed ha un testo
            if pub in ("SI", "RICICLATO") and testo:
                video_url = yt_url or fb_url
                if not video_url:
                    continue
                    
                # Usiamo la prima riga del testo come titolo identificatore
                first_line = testo.split("\n")[0].strip()
                
                # Raggruppiamo per video_url unico
                unique_properties[video_url] = {
                    "riga": idx,
                    "titolo": first_line,
                    "testo": testo,
                    "video_url": video_url
                }
                
        print(f"\nAnalisi completata:")
        print(f" - Totale righe: {len(rows)}")
        print(f" - Proprietà uniche trovate: {len(unique_properties)}")
        
        print("\nElenco delle prime 15 proprietà uniche:")
        for idx, (url, prop) in enumerate(list(unique_properties.items())[:15], start=1):
            print(f" {idx}. Riga {prop['riga']}: '{prop['titolo'][:60]}...' (Video: {url[:50]}...)")
            
    except Exception as e:
        print("Errore:", str(e))

if __name__ == "__main__":
    main()
