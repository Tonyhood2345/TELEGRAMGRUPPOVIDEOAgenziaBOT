import os
import sys
import json
import gspread
from google.oauth2.service_account import Credentials
import re
import subprocess

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
        
        # Mappatura delle colonne
        idx_desc = headers.index("PIANO_EDITORIALE_2026") if "PIANO_EDITORIALE_2026" in headers else 0
        idx_fb_text = headers.index("TESTO_ORIGINALE_FB") if "TESTO_ORIGINALE_FB" in headers else idx_desc
        idx_video = headers.index("LINK_MEDIA_SORGENTE") if "LINK_MEDIA_SORGENTE" in headers else 4
        
        print(f"Indices: idx_desc={idx_desc}, idx_fb_text={idx_fb_text}, idx_video={idx_video}")
        
        rows = all_vals[1:]
        
        print(f"=== ESECUZIONE PIPELINE GITHUB ACTIONS PER GLI IMMOBILI ===")
        processed_count = 0
        
        for idx, row in enumerate(rows, start=2):
            r_len = len(row)
            desc_text = row[idx_fb_text].strip() if idx_fb_text < r_len else ""
            video_url = row[idx_video].strip() if idx_video < r_len else ""
            
            print(f"Riga {idx} | desc_len={len(desc_text)} | video_url='{video_url}'")
            
            # Se la riga ha sia descrizione che video link, la elaboriamo
            if desc_text and video_url and video_url.startswith("http"):
                processed_count += 1
                
                # Estraiamo la prima riga della descrizione come titolo pulito
                first_line = desc_text.split("\n")[0].strip()
                clean_title = re.sub(r'\b\d{4}[-/]\d{2}[-/]\d{2}\b', '', first_line)
                clean_title = re.sub(r'\b\d{2}[-/]\d{2}[-/]\d{4}\b', '', clean_title)
                clean_title = re.sub(r'\s*-\s*$', '', clean_title.strip())
                clean_title = re.sub(r'^\s*-\s*', '', clean_title)
                clean_title = clean_title.strip()
                
                print(f"\n--- [{processed_count}] Elaborazione riga {idx}: {clean_title} ---")
                
                # Scriviamo temporaneamente metadati.json for crea_annuncio_wp.py
                metadata = {
                    "title": clean_title,
                    "description": desc_text
                }
                
                with open("metadata.json", "w", encoding="utf-8") as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=4)
                    
                # Eseguiamo il .py di WordPress
                cmd = f'python crea_annuncio_wp.py "{video_url}"'
                print(f"  Avvio: {cmd}")
                
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                
                if os.path.exists("metadata.json"):
                    os.remove("metadata.json")
                    
                if res.returncode == 0:
                    print(f"  ✅ Completato per la riga {idx}!")
                    output_lines = res.stdout.strip().split('\n')
                    for line in output_lines[-5:]:
                        print(f"    {line}")
                else:
                    print(f"  ❌ Errore alla riga {idx}.")
                    print(f"  Logs Errore:\n{res.stderr}")
                    
        print(f"\n🎉 PIPELINE COMPLETATA! Elaborati {processed_count} immobili.")
        
    except Exception as e:
        print("Errore generale durante la rigenerazione:", str(e))

if __name__ == "__main__":
    main()
