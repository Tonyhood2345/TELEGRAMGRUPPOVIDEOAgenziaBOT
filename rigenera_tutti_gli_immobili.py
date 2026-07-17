import os
import sys
import json
import gspread
from google.oauth2.service_account import Credentials

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

SPREADSHEET_ID = "1s68pw0WEUcV0ZqltiahAqCp_r5rsycSjxKNh0VZQq_g"
TARGET_GID = 1923610482

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
        
        target_ws = None
        for w in sh.worksheets():
            if int(w.id) == TARGET_GID:
                target_ws = w
                break
                
        if not target_ws:
            print(f"Nessun foglio trovato con GID {TARGET_GID}")
            print("Schede disponibili:")
            for w in sh.worksheets():
                print(f"  - Nome: '{w.title}' | GID: {w.id}")
            return
            
        print(f"✅ Trovato foglio per GID {TARGET_GID}: '{target_ws.title}'")
        all_vals = target_ws.get_all_values()
        if not all_vals:
            print("Il foglio è vuoto.")
            return
            
        print("\nHeaders del foglio:")
        print(all_vals[0])
        
        print("\nPrimi 10 record:")
        for idx, row in enumerate(all_vals[1:11], start=2):
            print(f"  Riga {idx}: {row[:12]}")
            
    except Exception as e:
        print("Errore:", str(e))

if __name__ == "__main__":
    main()
