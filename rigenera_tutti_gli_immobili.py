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
        
        # 1. Carica prezzi da MAIN_SHEET_ID Foglio1
        print("Caricamento storico prezzi da main sheet...")
        sh_main = gc.open_by_key(MAIN_SHEET_ID)
        ws_main = sh_main.worksheet("Foglio1")
        vals_main = ws_main.get_all_values()
        
        headers_main = [h.strip().upper() for h in vals_main[0]]
        idx_main_desc = headers_main.index("TESTO")
        idx_main_prezzo = headers_main.index("PREZZO") if "PREZZO" in headers_main else -1
        # Se non c'è PREZZO, cerchiamo nella colonna G (indice 6)
        if idx_main_prezzo == -1:
            idx_main_prezzo = 6
            print(f"Colonna PREZZO non trovata per nome, uso indice 6 (Lettera G)")
            
        prezzo_dict = {}
        for row in vals_main[1:]:
            r_len = len(row)
            desc = row[idx_main_desc].strip() if idx_main_desc < r_len else ""
            prezzo = row[idx_main_prezzo].strip() if idx_main_prezzo < r_len else ""
            if desc and prezzo:
                # Normalizziamo la descrizione (primi 100 caratteri puliti)
                norm_key = " ".join(desc.lower().split())[:100]
                prezzo_dict[norm_key] = prezzo
                
        print(f"Mappati {len(prezzo_dict)} testi con prezzi.")
        
        # 2. Carica Piano_editorale_2026 da LOG_SHEET_ID
        print("\nCaricamento Piano_editorale_2026...")
        sh_log = gc.open_by_key(LOG_SHEET_ID)
        ws_log = None
        for w in sh_log.worksheets():
            if w.title.lower() == "piano_editorale_2026":
                ws_log = w
                break
                
        if not ws_log:
            print("Piano_editorale_2026 non trovato.")
            return
            
        vals_log = ws_log.get_all_values()
        headers_log = [h.strip().upper() for h in vals_log[0]]
        
        idx_log_desc = headers_log.index("DESCRIZIONE")
        idx_log_pub = headers_log.index("PUBBLICATO")
        idx_log_citta = headers_log.index("CITTA") if "CITTA" in headers_log else -1
        
        print("\n=== VERIFICA RIGHE ATTIVE CON INCROCIO PREZZO ===")
        match_count = 0
        for idx, row in enumerate(vals_log[1:], start=2):
            r_len = len(row)
            pub = row[idx_log_pub].strip().upper() if idx_log_pub < r_len else ""
            desc = row[idx_log_desc].strip() if idx_log_desc < r_len else ""
            citta = row[idx_log_citta].strip() if (idx_log_citta != -1 and idx_log_citta < r_len) else ""
            
            if pub == "SI" and desc:
                norm_key = " ".join(desc.lower().split())[:100]
                prezzo = prezzo_dict.get(norm_key)
                
                title = desc.split("\n")[0].strip()
                if prezzo:
                    match_count += 1
                    print(f"Riga {idx} | '{title[:50]}...' | Città: {citta} | PREZZO TROVATO: {prezzo} €")
                else:
                    print(f"Riga {idx} | '{title[:50]}...' | Città: {citta} | PREZZO NON TROVATO (Trattativa Riservata)")
                    
        print(f"\nTotale incrociati con successo: {match_count}")
        
    except Exception as e:
        print("Errore:", str(e))

if __name__ == "__main__":
    main()
