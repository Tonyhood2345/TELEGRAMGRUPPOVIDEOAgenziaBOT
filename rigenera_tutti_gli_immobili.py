import os
import sys
import json
import gspread
from google.oauth2.service_account import Credentials

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
        
        print("=== INFO FOGLI ===")
        for w in sh.worksheets():
            all_vals = w.get_all_values()
            row_count = len(all_vals)
            col_count = len(all_vals[0]) if all_vals else 0
            print(f"Foglio: '{w.title}' | Righe: {row_count} | Colonne: {col_count}")
            if row_count > 0:
                print(f"  Headers: {all_vals[0][:10]}")
                if row_count > 1:
                    print(f"  Riga 2 : {all_vals[1][:10]}")
            print("-" * 50)
            
    except Exception as e:
        print("Errore:", str(e))

if __name__ == "__main__":
    main()
