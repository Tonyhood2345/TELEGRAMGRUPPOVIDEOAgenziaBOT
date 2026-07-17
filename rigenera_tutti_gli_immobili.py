import os
import sys
import json
import gspread
from google.oauth2.service_account import Credentials
import re
import subprocess

SPREADSHEET_ID = "1s68pw0WEUcV0ZqltiahAqCp_r5rsycSjxKNh0VZQq_g"
TARGET_GID = 1161427165 # GID di DATABASE_IMMOBILI (146 righe totali)

def get_google_sheets_client():
    creds_val = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_val:
        raise ValueError("Variabile GOOGLE_APPLICATION_CREDENTIALS non definita.")
    
    # Se il valore contiene le parentesi graffe di un JSON, lo parsa direttamente come stringa
    if creds_val.strip().startswith("{"):
        creds_dict = json.loads(creds_val)
    else:
        # Altrimenti, assume sia il percorso di un file e lo legge
        with open(creds_val, "r", encoding="utf-8") as f:
            creds_dict = json.load(f)
            
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
            if int(w.id) == TARGET_GID:
                ws = w
                break
                
        if not ws:
            print(f"❌ Foglio con GID {TARGET_GID} non trovato.")
            return
            
        all_vals = ws.get_all_values()
        if not all_vals or len(all_vals) <= 1:
            print("Il foglio è vuoto.")
            return
            
        headers = [h.strip().upper() for h in all_vals[0]]
        print("Headers trovati:", headers)
        
        idx_desc = headers.index("DESCRIZIONE") if "DESCRIZIONE" in headers else 4
        
        idx_video = -1
        for col_name in ["LINK_YOUTUBE", "LINK", "LINK_FACEBOOK"]:
            if col_name in headers:
                idx_video = headers.index(col_name)
                break
        if idx_video == -1:
            idx_video = 15 # default fallback
            
        idx_pub = headers.index("PUBBLICATO") if "PUBBLICATO" in headers else -1
        
        print(f"Mappatura Colonne: idx_desc={idx_desc}, idx_video={idx_video}, idx_pub={idx_pub}")
        
        rows = all_vals[1:]
        
        print(f"=== ESECUZIONE PIPELINE GITHUB ACTIONS ===")
        processed_count = 0
        
        for idx, row in enumerate(rows, start=2):
            r_len = len(row)
            desc_text = row[idx_desc].strip() if idx_desc < r_len else ""
            video_url = row[idx_video].strip() if idx_video < r_len else ""
            
            is_published = True
            if idx_pub != -1 and idx_pub < r_len:
                is_published = (row[idx_pub].strip().upper() == "SI")
                
            if desc_text and video_url and video_url.startswith("http") and is_published:
                processed_count += 1
                
                # Estraiamo la prima riga della descrizione come titolo pulito
                first_line = desc_text.split("\n")[0].strip()
                clean_title = re.sub(r'\b\d{4}[-/]\d.py\b', '', first_line)
                clean_title = re.sub(r'\b\d{2}[-/]\d{2}[-/]\d{4}\b', '', clean_title)
                clean_title = re.sub(r'\s*-\s*$', '', clean_title.strip())
                clean_title = re.sub(r'^\s*-\s*', '', clean_title)
                clean_title = clean_title.strip()
                
                if len(clean_title) > 80:
                    clean_title = clean_title[:77] + "..."
                    
                print(f"\n--- Elaborazione riga {idx}: {clean_title} ---")
                print(f"  URL Video: {video_url}")
                
                metadata = {
                    "title": clean_title,
                    "description": desc_text
                }
                
                with open("metadata.json", "w", encoding="utf-8") as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=4)
                    
                cmd = f'python crea_annuncio_wp.py "{video_url}"'
                print(f"  Avvio: {cmd}")
                
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                
                if os.path.exists("metadata.json"):
                    os.remove("metadata.json")
                    
                if res.returncode == 0:
                    print(f"  ✅ Riga {idx} completata con successo!")
                    output_lines = res.stdout.strip().split('\n')
                    for line in output_lines:
                        if "published" in line.lower() or "pubblicato" in line.lower() or "http" in line:
                            print(f"    {line}")
                else:
                    print(f"  ❌ Errore durante l'esecuzione per la riga {idx}.")
                    print(f"  Logs Errore:\n{res.stderr}")
                    
        print(f"\n🎉 PIPELINE COMPLETATA! Elaborati {processed_count} immobili.")
        
    except Exception as e:
        print("Errore generale durante la rigenerazione:", str(e))

if __name__ == "__main__":
    main()
