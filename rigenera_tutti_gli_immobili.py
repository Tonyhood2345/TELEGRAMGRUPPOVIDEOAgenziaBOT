import os
import sys
import json
import gspread
from google.oauth2.service_account import Credentials

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

LOG_SHEET_ID = "1s68pw0WEUcV0ZqltiahAqCp_r5rsycSjxKNh0VZQq_g"

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
        sh = gc.open_by_key(LOG_SHEET_ID)
        
        ws = None
        for w in sh.worksheets():
            if w.title.lower() == "piano_editorale_2026":
                ws = w
                break
                
        if not ws:
            print("Piano_editorale_2026 non trovato.")
            return
            
        all_vals = ws.get_all_values()
        headers = [h.strip().upper() for h in all_vals[0]]
        
        # Stampiamo i dati completi di ogni riga attiva (da riga 173 a 182)
        for idx in range(173, 183):
            row = all_vals[idx - 1]
            print(f"\n=== RIGA {idx} ===")
            for h, val in zip(headers, row):
                if val.strip():
                    print(f"  {h}: '{val}'")
            print("-" * 50)
            
    except Exception as e:
        print("Errore:", str(e))

if __name__ == "__main__":
    main()
