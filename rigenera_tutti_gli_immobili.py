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
        
        ws = None
        for w in sh.worksheets():
            if w.title.lower() == "piano_editorale_2026":
                ws = w
                break
                
        if not ws:
            print("Nessun foglio Piano_editorale_2026 trovato.")
            return
            
        all_vals = ws.get_all_values()
        headers = [h.strip().upper() for h in all_vals[0]]
        
        idx_desc = headers.index("DESCRIZIONE")
        idx_pub = headers.index("PUBBLICATO")
        idx_fb = headers.index("LINK_FACEBOOK") if "LINK_FACEBOOK" in headers else -1
        idx_yt = headers.index("LINK_YOUTUBE") if "LINK_YOUTUBE" in headers else -1
        idx_link = headers.index("LINK") if "LINK" in headers else -1
        idx_citta = headers.index("CITTA") if "CITTA" in headers else -1
        
        print("=== DETTAGLIO RIGHE 170-184 ===")
        for idx in range(170, min(len(all_vals), 185)):
            row = all_vals[idx - 1]
            r_len = len(row)
            pub = row[idx_pub].strip() if idx_pub < r_len else ""
            desc = row[idx_desc].strip() if idx_desc < r_len else ""
            fb = row[idx_fb].strip() if (idx_fb != -1 and idx_fb < r_len) else ""
            yt = row[idx_yt].strip() if (idx_yt != -1 and idx_yt < r_len) else ""
            lnk = row[idx_link].strip() if (idx_link != -1 and idx_link < r_len) else ""
            citta = row[idx_citta].strip() if (idx_citta != -1 and idx_citta < r_len) else ""
            
            print(f"Riga {idx} | Pubblicato: '{pub}' | Città: '{citta}'")
            print(f"  YT: '{yt}'")
            print(f"  FB: '{fb}'")
            print(f"  LINK: '{lnk}'")
            print(f"  Desc: '{desc[:100]}...'")
            print("-" * 50)
            
    except Exception as e:
        print("Errore:", str(e))

if __name__ == "__main__":
    main()
