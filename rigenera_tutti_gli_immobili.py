import os
import sys
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
import urllib.parse

# Importa le funzioni di pubblicazione dal file locale
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from crea_annuncio_wp import create_wp_listing, aggiorna_database_json
except ImportError:
    # Se import fallisce (es. se eseguito in una cartella diversa), definiamo le funzioni stub
    pass

# CONFIGURAZIONI SHEET E GOOGLE API
SPREADSHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"
SHEET_NAME = "Foglio1"

def get_google_sheets_client():
    """Inizializza il client per le API di Google Sheets usando i credentials d'ambiente."""
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_json:
        raise ValueError("Variabile GOOGLE_APPLICATION_CREDENTIALS non definita.")
        
    try:
        # Se è una stringa JSON
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            creds_dict, 
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        )
    except Exception:
        # Se è un percorso file
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
        sheet = sh.worksheet(SHEET_NAME)
    except Exception as e:
        print(f"❌ Errore connessione Google Sheets: {e}")
        return

    # Legge tutte le righe del foglio
    raw_data = sheet.get_all_values()
    if not raw_data:
        print("Il foglio Google è vuoto.")
        return
        
    headers = [str(h).strip().lower() for h in raw_data[0]]
    rows = raw_data[1:]
    
    # Mappa colonne
    col_mapping = {h: idx for idx, h in enumerate(headers)}
    
    print(f"Trovate {len(rows)} righe nel database. Avvio elaborazione...")
    
    success_count = 0
    for idx, row in enumerate(rows):
        # Mappa i dati della riga corrente
        def get_val(col_name, default=""):
            col_idx = col_mapping.get(col_name)
            if col_idx is not None and col_idx < len(row):
                return row[col_idx].strip()
            return default

        id_immobile = get_val("id") or f"ROW-{idx+2}"
        titolo = get_val("titolo")
        descrizione = get_val("descrizione") or get_val("testo") or get_val("testo seo")
        prezzo = get_val("prezzo")
        indirizzo = get_val("indirizzo") or get_val("comune")
        video_url = get_val("video") or get_val("video url") or get_val("link video")
        foto_url_str = get_val("foto") or get_val("foto urls") or get_val("link foto")
        ape_class = get_val("ape") or get_val("classe energetica") or "E"
        pubblicato = get_val("pubblicato").upper()

        if pubblicato != "SI":
            print(f"⏭️ Riga {idx+2} ({titolo[:30]}...): Salto perché 'Pubblicato' non è impostato su 'SI'.")
            continue

        if not titolo:
            print(f"⏭️ Riga {idx+2}: Salto perché il titolo è vuoto.")
            continue

        print(f"\nProcessing {success_count+1}: '{titolo}' (ID: {id_immobile})...")

        # Parsing foto (separate da virgola o a capo)
        foto_urls = []
        if foto_url_str:
            if "," in foto_url_str:
                foto_urls = [f.strip() for f in foto_url_str.split(",") if f.strip()]
            else:
                foto_urls = [f.strip() for f in foto_url_str.split("\n") if f.strip()]

        # Se non ci sono foto, usiamo un placeholder
        featured_id = 0
        if foto_urls:
            # Per evitare di ri-caricare la foto su WP ogni volta, possiamo inserire l'URL come featured_media in WP_CPT o passarla come url
            # In questo bulk script, passiamo le foto già esistenti nella galleria
            pass

        # Imposta variabili d'ambiente temporanee per far funzionare crea_annuncio_wp
        os.environ["INPUT_INDIRIZZO"] = indirizzo
        
        try:
            # Esegui la creazione dell'annuncio
            link_creato = create_wp_listing(
                title=titolo,
                content=descrizione,
                featured_media_id=0, # 0 se non vogliamo caricare file fisici ma usare url in html
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
