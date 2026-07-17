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

def rigenera_tutto():
    try:
        gc = get_google_sheets_client()
        sh = gc.open_by_key(SPREADSHEET_ID)
        
        print("Tutte le schede disponibili nel foglio:")
        for w in sh.worksheets():
            print(f" - {w.title}")
            
        # Proviamo a caricare DATABASE_IMMOBILI
        ws = None
        for name in ["DATABASE_IMMOBILI", "DB_IMMOBILI", "Piano_Editoriale_2026", "ANNUNCI_ATTIVI", "Foglio1"]:
            try:
                ws = sh.worksheet(name)
                print(f"\n✅ Foglio selezionato per test: {name}")
                break
            except Exception:
                continue
                
        if not ws:
            print("Nessun foglio trovato.")
            return
            
        all_values = ws.get_all_values()
        if not all_values:
            print("Il foglio è vuoto.")
            return
            
        print("\nIntestazioni (Headers):")
        for idx, h in enumerate(all_values[0]):
            print(f"  Colonna {idx} (Lettera {chr(65+idx)}): '{h}'")
            
        print("\nPrimi 5 record di dati:")
        for idx, row in enumerate(all_values[1:6], start=2):
            print(f"  Riga {idx}: {row[:15]}")
            
    except Exception as e:
        print("Errore:", str(e))

if __name__ == "__main__":
    rigenera_tutto()
