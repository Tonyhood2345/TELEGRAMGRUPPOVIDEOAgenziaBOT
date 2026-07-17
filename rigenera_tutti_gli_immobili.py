import os
import sys
import json
import gspread
from google.oauth2.service_account import Credentials

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

SPREADSHEET_ID = "1s68pw0WEUcV0ZqltiahAqCp_r5rsycSjxKNh0VZQq_g"

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
        
        # Cerca Piano_editoriale_2026 (case-insensitive)
        ws = None
        for w in sh.worksheets():
            if w.title.lower() == "piano_editorale_2026":
                ws = w
                break
                
        if not ws:
            print("Nessun foglio Piano_editoriale_2026 trovato.")
            return
            
        print(f"✅ Trovato foglio: {ws.title}")
        all_vals = ws.get_all_values()
        if not all_vals or len(all_vals) <= 1:
            print("Il foglio è vuoto.")
            return
            
        headers = [h.strip().upper() for h in all_vals[0]]
        print(f"Headers: {headers}")
        
        idx_desc = headers.index("DESCRIZIONE")
        idx_pub = headers.index("PUBBLICATO")
        
        idx_fb = headers.index("LINK_FACEBOOK") if "LINK_FACEBOOK" in headers else -1
        idx_yt = headers.index("LINK_YOUTUBE") if "LINK_YOUTUBE" in headers else -1
        idx_link = headers.index("LINK") if "LINK" in headers else -1
        idx_citta = headers.index("CITTA") if "CITTA" in headers else -1
        
        rows = all_vals[1:]
        
        unique_properties = {}
        
        for idx, row in enumerate(rows, start=2):
            r_len = len(row)
            pub = row[idx_pub].strip().upper() if idx_pub < r_len else ""
            desc = row[idx_desc].strip() if idx_desc < r_len else ""
            
            fb_url = row[idx_fb].strip() if (idx_fb != -1 and idx_fb < r_len) else ""
            yt_url = row[idx_yt].strip() if (idx_yt != -1 and idx_yt < r_len) else ""
            link_url = row[idx_link].strip() if (idx_link != -1 and idx_link < r_len) else ""
            
            video_url = yt_url or fb_url or link_url
            
            # Filtro degli attivi: ad esempio pub == 'SI' o stato attivo
            # Stampa anche quelli con pub non vuoto per diagnostica
            if pub in ("SI", "ATTIVO", "DISPONIBILE", "PUBBLICATO") and desc and video_url:
                first_line = desc.split("\n")[0].strip()
                
                # Raggruppiamo per video_url per evitare duplicati
                unique_properties[video_url] = {
                    "riga": idx,
                    "titolo": first_line,
                    "descrizione": desc,
                    "video_url": video_url,
                    "citta": row[idx_citta].strip() if (idx_citta != -1 and idx_citta < r_len) else "",
                    "pubblicato_val": pub
                }
                
        print(f"\nAnalisi completata per Piano_editoriale_2026:")
        print(f" - Totale righe: {len(rows)}")
        print(f" - Proprietà attive uniche trovate: {len(unique_properties)}")
        
        for idx, (url, prop) in enumerate(list(unique_properties.items())[:20], start=1):
            print(f" {idx}. Riga {prop['riga']}: '{prop['titolo'][:60]}...' (Video: {url[:50]}...) | Stato: {prop['pubblicato_val']}")
            
    except Exception as e:
        print("Errore:", str(e))

if __name__ == "__main__":
    main()
