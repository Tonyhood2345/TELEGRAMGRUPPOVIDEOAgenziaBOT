import os
import sys
import json
import gspread
from google.oauth2.service_account import Credentials

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

MAIN_SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"
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
        
        print(f"=== SCHEDE IN MAIN ({MAIN_SHEET_ID}) ===")
        sh_main = gc.open_by_key(MAIN_SHEET_ID)
        for w in sh_main.worksheets():
            print(f"  - {w.title}")
            
        print(f"\n=== SCHEDE IN LOG ({LOG_SHEET_ID}) ===")
        sh_log = gc.open_by_key(LOG_SHEET_ID)
        for w in sh_log.worksheets():
            print(f"  - {w.title}")
            
    except Exception as e:
        print("Errore:", str(e))

if __name__ == "__main__":
    main()
