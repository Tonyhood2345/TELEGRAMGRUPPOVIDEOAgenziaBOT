import os
import sys
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
import urllib.parse
import re

# Importa le funzioni di pubblicazione dal file locale
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from crea_annuncio_wp import create_wp_listing, aggiorna_database_json
except ImportError:
    pass

# CONFIGURAZIONI SHEET E GOOGLE API
SPREADSHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"

def get_google_sheets_client():
    """Inizializza il client per le API di Google Sheets usando i credentials d'ambiente."""
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_json:
        raise ValueError("Variabile GOOGLE_APPLICATION_CREDENTIALS non definita.")
        
    try:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            creds_dict, 
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        )
    except Exception:
        creds = Credentials.from_service_account_file(
            creds_json, 
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        )
        
    return gspread.authorize(creds)

def rigenera_tutto():
    """Legge tutti gli immobili dal foglio Google e li pubblica/aggiorna su WordPress."""
    print("=== AVVIO RIGENERAZIONE IN BLOCCO DI TUTTO IL PORTAFOGLIO IMMOBILI ===")
    
    try:
        gc = get_google_sheets_client()
        sh = gc.open_by_key(SPREADSHEET_ID)
        
        # Prova prima Piano_Editoriale_2026, poi ANNUNCI_ATTIVI, poi Foglio1
        ws = None
        for sheet_name in ["Piano_Editoriale_2026", "ANNUNCI_ATTIVI", "Foglio1"]:
            try:
                ws = sh.worksheet(sheet_name)
                print(f"✅ Trovato foglio: {sheet_name}")
                break
            except Exception:
                continue
                
        if not ws:
            print("❌ Impossibile trovare la scheda Piano_Editoriale_2026 o ANNUNCI_ATTIVI o Foglio1")
            return
            
    except Exception as e:
        print(f"❌ Errore connessione Google Sheets: {e}")
        return

    # Legge tutte le righe del foglio
    raw_data = ws.get_all_values()
    if not raw_data or len(raw_data) <= 1:
        print("Il foglio Google è vuoto.")
        return
        
    headers = [str(h).strip().upper() for h in raw_data[0]]
    
    def get_col_idx(names, default):
        for name in names:
            if name.upper() in headers:
                return headers.index(name.upper())
        return default
        
    # Regola di estrazione dati: il testo descrittivo dell'immobile viene prelevato rigorosamente dalla Colonna F (Indice 5)
    idx_testo = 5
    idx_tipo = get_col_idx(["TIPO", "TIPOLOGIA"], 3)
    idx_link = get_col_idx(["LINK", "LINK_VIDEO", "LINK_YOUTUBE", "VIDEO"], 4)
    idx_stato = get_col_idx(["STATO", "PUBBLICATO"], 2)
    idx_data = get_col_idx(["DATA", "DATA_PUBBLICAZIONE"], 1)
    idx_id = get_col_idx(["ID", "ID_ANNUNCIO", "ID_IMMOBILE"], 0)
    idx_prezzo = get_col_idx(["PREZZO"], -1)
    idx_indirizzo = get_col_idx(["INDIRIZZO", "ZONA", "COMUNE"], -1)
    
    rows = raw_data[1:]
    print(f"Trovate {len(rows)} righe nel database. Avvio elaborazione...")
    
    success_count = 0
    for idx, row in enumerate(rows, start=2):
        r_len = len(row)
        
        # Controlla stato e testo
        stato = row[idx_stato].strip().upper() if idx_stato < r_len else ""
        testo = row[idx_testo].strip() if idx_testo < r_len else ""
        
        if not (testo and stato in ("SI", "ATTIVO", "DISPONIBILE", "PUBBLICATO")):
            continue

        # Estrai altri campi
        titolo_completo = row[idx_testo].split("\n")[0].strip()
        idx_titolo = get_col_idx(["TITOLO"], -1)
        if idx_titolo != -1 and idx_titolo < r_len and row[idx_titolo].strip():
            titolo = row[idx_titolo].strip()
        else:
            titolo = titolo_completo[:60] + "..." if len(titolo_completo) > 60 else titolo_completo
            
        prezzo = row[idx_prezzo].strip() if (idx_prezzo != -1 and idx_prezzo < r_len) else ""
        indirizzo = row[idx_indirizzo].strip() if (idx_indirizzo != -1 and idx_indirizzo < r_len) else ""
        video_url = row[idx_link].strip() if idx_link < r_len else ""
        
        # Cerca link foto o immagini nel testo o nelle colonne
        foto_urls = []
        idx_foto = get_col_idx(["FOTO", "FOTO_URLS", "LINK_FOTO"], -1)
        if idx_foto != -1 and idx_foto < r_len and row[idx_foto].strip():
            foto_url_str = row[idx_foto].strip()
            if "," in foto_url_str:
                foto_urls = [f.strip() for f in foto_url_str.split(",") if f.strip()]
            else:
                foto_urls = [f.strip() for f in foto_url_str.split("\n") if f.strip()]

        print(f"\nProcessing {success_count+1}: '{titolo}' (Stato: {stato})...")

        # Imposta indirizzo nella variabile d'ambiente temporanea per far funzionare crea_annuncio_wp
        os.environ["INPUT_INDIRIZZO"] = indirizzo
        
        try:
            # Esegui la creazione dell'annuncio
            link_creato = create_wp_listing(
                title=titolo,
                content=testo,
                featured_media_id=0,
                images_urls=foto_urls,
                video_url=video_url
            )
            
            if link_creato:
                print(f"✅ Annuncio aggiornato/creato su WordPress: {link_creato}")
                success_count += 1
            else:
                print(f"❌ Errore durante la pubblicazione su WP per '{titolo}'")
        except Exception as ex:
            print(f"❌ Eccezione durante l'elaborazione di '{titolo}': {ex}")

    print(f"\n🎉 RIGENERAZIONE BLOCCO COMPLETATA CON SUCCESSO!")
    print(f"Immobili elaborati e aggiornati: {success_count}")

if __name__ == "__main__":
    rigenera_tutto()
