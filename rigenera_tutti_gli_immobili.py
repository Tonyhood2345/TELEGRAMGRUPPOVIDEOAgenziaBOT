import os
import sys
import json
import gspread
from google.oauth2.service_account import Credentials
import re
import requests
import urllib.parse

# Importiamo le funzioni e variabili dal nostro script principale crea_annuncio_wp.py
import crea_annuncio_wp
from crea_annuncio_wp import (
    create_wp_listing,
    optimize_description_with_groq,
    extract_price_from_text,
    upload_photo_to_wp,
    extract_frames,
    call_mcp_tool
)

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

def extract_address_from_desc(description, city="Favara"):
    """Estrae una via/corso indicativo per la localizzazione della mappa."""
    match = re.search(r'\b(via|corso|viale|piazza)\s+([A-Za-z0-9À-ÿ\s]+?)(?=\.|\,|\n|in vendita|in affitto|con|ha|off|classe|\d|$)', description, re.IGNORECASE)
    if match:
        street_type = match.group(1).strip()
        street_name = match.group(2).strip()
        street_name = re.split(r'\s+(?:al|con|di|da|per|in)\b', street_name, flags=re.IGNORECASE)[0]
        return f"{street_type} {street_name}, {city}"
    return f"{city}"

def find_existing_wp_listing(title, link_suffix):
    """
    Cerca se esiste già un annuncio property su WordPress con lo stesso titolo o link.
    Ritorna l'ID se trovato, altrimenti None.
    """
    try:
        res = call_mcp_tool("wp_list_cpt_items", {
            "rest_base": "property",
            "per_page": 100
        })
        if not res or 'items' not in res:
            return None
            
        # Proviamo prima a confrontare il link/slug
        clean_suffix = link_suffix.strip().lower()
        for item in res['items']:
            item_link = item.get('link', '').lower()
            if clean_suffix in item_link:
                print(f"  -> Trovato match per URL/Slug: {item_link} (ID WordPress: {item['id']})")
                return item['id']
                
        # Fallback confronto per titolo esatto
        for item in res['items']:
            item_title = item.get('title', {}).get('rendered', '') if isinstance(item.get('title'), dict) else item.get('title', '')
            if item_title == title:
                print(f"  -> Trovato match per Titolo: '{title}' (ID WordPress: {item['id']})")
                return item['id']
                
    except Exception as e:
        print("  [Warning] Impossibile verificare duplicati WordPress:", str(e))
    return None

def main():
    try:
        gc = get_google_sheets_client()
        
        # 1. Caricamento storico prezzi da MAIN_SHEET_ID Foglio1
        print("Caricamento storico prezzi da main sheet per associazione...")
        sh_main = gc.open_by_key(MAIN_SHEET_ID)
        ws_main = sh_main.worksheet("Foglio1")
        vals_main = ws_main.get_all_values()
        
        headers_main = [h.strip().upper() for h in vals_main[0]]
        idx_main_desc = headers_main.index("TESTO")
        idx_main_prezzo = headers_main.index("PREZZO") if "PREZZO" in headers_main else 6
        
        prezzo_dict = {}
        for row in vals_main[1:]:
            r_len = len(row)
            desc = row[idx_main_desc].strip() if idx_main_desc < r_len else ""
            prezzo = row[idx_main_prezzo].strip() if idx_main_prezzo < r_len else ""
            if desc and prezzo:
                norm_key = " ".join(desc.lower().split())[:100]
                prezzo_dict[norm_key] = prezzo
                
        print(f"Mappati {len(prezzo_dict)} testi con prezzi dallo storico.")
        
        # 2. Caricamento Piano_Editoriale_2026 da LOG_SHEET_ID
        print("\nCaricamento foglio Piano_Editoriale_2026...")
        sh_log = gc.open_by_key(LOG_SHEET_ID)
        
        ws_log = None
        for w in sh_log.worksheets():
            if w.title.lower() == "piano_editorale_2026":
                ws_log = w
                break
                
        if not ws_log:
            print("❌ Foglio Piano_Editoriale_2026 non trovato nel foglio LOG.")
            return
            
        vals_log = ws_log.get_all_values()
        headers_log = [h.strip().upper() for h in vals_log[0]]
        
        idx_log_desc = headers_log.index("DESCRIZIONE")
        idx_log_pub = headers_log.index("PUBBLICATO")
        idx_log_citta = headers_log.index("CITTA") if "CITTA" in headers_log else -1
        idx_log_yt = headers_log.index("LINK_YOUTUBE") if "LINK_YOUTUBE" in headers_log else -1
        idx_log_fb = headers_log.index("LINK_FACEBOOK") if "LINK_FACEBOOK" in headers_log else -1
        idx_log_link = headers_log.index("LINK") if "LINK" in headers_log else -1
        
        # Filtriamo le righe attive con PUBBLICATO == 'SI'
        listings_to_process = []
        for idx, row in enumerate(vals_log[1:], start=2):
            r_len = len(row)
            pub = row[idx_log_pub].strip().upper() if idx_log_pub < r_len else ""
            desc = row[idx_log_desc].strip() if idx_log_desc < r_len else ""
            yt_url = row[idx_log_yt].strip() if (idx_log_yt != -1 and idx_log_yt < r_len) else ""
            fb_url = row[idx_log_fb].strip() if (idx_log_fb != -1 and idx_log_fb < r_len) else ""
            link_url = row[idx_log_link].strip() if (idx_log_link != -1 and idx_log_link < r_len) else ""
            
            video_url = yt_url or fb_url or link_url
            
            if pub == "SI" and desc and video_url:
                citta = row[idx_log_citta].strip() if (idx_log_citta != -1 and idx_log_citta < r_len) else "Favara"
                listings_to_process.append({
                    "riga": idx,
                    "descrizione": desc,
                    "video_url": video_url,
                    "citta": citta
                })
                
        print(f"Trovati {len(listings_to_process)} immobili da rigenerare su WordPress.")
        if not listings_to_process:
            print("Nessun immobile da elaborare.")
            return
            
        # 3. Ottimizzazione: scarichiamo il video principale una sola volta per i fotogrammi
        video_url_template = listings_to_process[0]["video_url"]
        video_filename = "video_annuncio_temp.mp4"
        
        print(f"\nScarico il video di riferimento per fotogrammi: {video_url_template}")
        if video_url_template.startswith("http") and ".mp4" in video_url_template:
            res = requests.get(video_url_template, verify=False)
            with open(video_filename, "wb") as f:
                f.write(res.content)
        else:
            download_cmd = f'yt-dlp -f "best" -o "{video_filename}" "{video_url_template}"'
            import subprocess
            subprocess.run(download_cmd, shell=True)
            
        if not os.path.exists(video_filename) or os.path.getsize(video_filename) == 0:
            print("Download del video template fallito, impossibile continuare.")
            return
            
        photo_files = extract_frames(video_filename, num_frames=18)
        if not photo_files:
            print("Estrazione fotogrammi fallita.")
            return
            
        # Carichiamo i fotogrammi una sola volta
        media_ids = []
        media_urls = []
        print(f"Caricamento di {len(photo_files)} fotogrammi su WordPress...")
        for photo in photo_files:
            m_id, m_url = upload_photo_to_wp(photo)
            if m_id and m_url:
                media_ids.append(m_id)
                media_urls.append(m_url)
                
        if not media_ids:
            print("Nessun fotogramma caricato, impossibile procedere.")
            return
            
        featured_id = media_ids[0]
        
        # Pulizia file temporanei locali
        try:
            os.remove(video_filename)
            for photo in photo_files:
                os.remove(photo)
        except Exception:
            pass
            
        # 4. Elaboriamo e pubblichiamo/aggiorniamo ciascun immobile
        for index_item, item in enumerate(listings_to_process):
            desc = item["descrizione"]
            v_url = item["video_url"]
            citta = item["citta"]
            riga_num = item["riga"]
            
            # Titolo
            titolo_originale = desc.split("\n")[0].strip()
            clean_title = re.sub(r'\b\d{4}[-/]\d{2}[-/]\d{2}\b', '', titolo_originale)
            clean_title = re.sub(r'\b\d{2}[-/]\d{2}[-/]\d{4}\b', '', clean_title)
            clean_title = re.sub(r'\s*-\s*$', '', clean_title.strip())
            clean_title = re.sub(r'^\s*-\s*', '', clean_title)
            clean_title = clean_title.strip()
            
            print(f"\n--- [{index_item+1}/{len(listings_to_process)}] Elaborazione Riga {riga_num}: {clean_title} ---")
            
            # Incrocio prezzo
            norm_key = " ".join(desc.lower().split())[:100]
            prezzo_storico = prezzo_dict.get(norm_key)
            if prezzo_storico:
                print(f"  -> Prezzo incrociato dallo storico: {prezzo_storico} €")
                # Iniettiamo il prezzo nella logica del modulo crea_annuncio_wp
                crea_annuncio_wp.price = int(re.sub(r'[^\d]', '', prezzo_storico))
                crea_annuncio_wp.has_declared_price = True
            else:
                extracted = extract_price_from_text(desc)
                if extracted:
                    print(f"  -> Prezzo estratto dal testo: {extracted} €")
                    crea_annuncio_wp.price = extracted
                    crea_annuncio_wp.has_declared_price = True
                else:
                    print("  -> Nessun prezzo trovato. Trattativa Riservata.")
                    crea_annuncio_wp.price = 0
                    crea_annuncio_wp.has_declared_price = False
                    
            # Estrazione e iniezione indirizzo per la mappa
            indirizzo = extract_address_from_desc(desc, citta)
            print(f"  -> Indirizzo per mappa: {indirizzo}")
            crea_annuncio_wp.PROPERTY_ADDRESS = indirizzo
            
            # Ottimizzazione descrizione con Groq
            optimized_text = optimize_description_with_groq(clean_title, desc)
            
            # Controllo duplicati: cerchiamo se l'annuncio esiste già su WordPress
            # Usiamo un suffisso per identificare la pagina (es: "vendita-11")
            slug_suffix = f"vendita-{riga_num - 162}" # riga 173 -> vendita-11, riga 174 -> vendita-12, ecc.
            existing_id = find_existing_wp_listing(clean_title, slug_suffix)
            
            if existing_id:
                print(f"  -> L'immobile esiste già (ID {existing_id}). Eseguo l'aggiornamento...")
                # Aggiorniamo l'annuncio esistente modificando la logica di crea_annuncio_wp per usare wp_update_cpt_item
                # Per farlo, modifichiamo al volo la chiamata del tool
                def create_wp_listing_update(title, content, featured_media_id, images_urls, video_url):
                    # Ricreiamo il layout completo come fa la funzione originale
                    return create_wp_listing(title, content, featured_media_id, images_urls, video_url)
                
                # Modifichiamo temporaneamente la funzione wp_create_cpt_item in crea_annuncio_wp con una patch per aggiornare
                original_create_tool = crea_annuncio_wp.call_mcp_tool
                
                def patched_call_mcp_tool(tool_name, arguments):
                    if tool_name == "wp_create_cpt_item":
                        # Convertiamo a update
                        tool_name = "wp_update_cpt_item"
                        arguments["item_id"] = existing_id
                    return original_create_tool(tool_name, arguments)
                    
                crea_annuncio_wp.call_mcp_tool = patched_call_mcp_tool
                
                try:
                    wp_link = create_wp_listing(
                        title=clean_title,
                        content=optimized_text,
                        featured_media_id=featured_id,
                        images_urls=media_urls,
                        video_url=v_url
                    )
                finally:
                    # Ripristiniamo la funzione originale
                    crea_annuncio_wp.call_mcp_tool = original_create_tool
            else:
                print("  -> Nuovo immobile. Procedo con la creazione...")
                wp_link = create_wp_listing(
                    title=clean_title,
                    content=optimized_text,
                    featured_media_id=featured_id,
                    images_urls=media_urls,
                    video_url=v_url
                )
                
            if wp_link:
                print(f"✅ Riga {riga_num} RIGENERATA/AGGIORNATA CON SUCCESSO: {wp_link}")
            else:
                print(f"❌ Riga {riga_num} ERRORE durante l'elaborazione.")
                
        print("\n🎉 TUTTE LE OPERAZIONI DI RIGENERAZIONE SONO STATE COMPLETATE!")
        
    except Exception as e:
        print("Errore generale durante la rigenerazione:", str(e))

if __name__ == "__main__":
    main()
