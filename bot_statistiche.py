import os
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import re
from datetime import datetime

# --- CONFIGURAZIONE ---
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
YT_API_KEY = os.environ.get("YT_API_KEY")

SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc" 

def extract_yt_id(url):
    match = re.search(r"v=([a-zA-Z0-9_-]+)", str(url))
    return match.group(1) if match else None

def extract_fb_id(url):
    # ATTENZIONE: Cerca rigorosamente solo "videos/" o "reel/"
    match = re.search(r"(?:videos/|reel/)(\d+)", str(url))
    return match.group(1) if match else None

def analizza_testo_annuncio(testo):
    """Analizza il testo del post per estrarre Tipologia e Città"""
    if not testo:
        return "Altro", "Non specificata"
        
    testo_min = testo.lower()
    
    # 1. PULIZIA: Rimuove le firme per evitare falsi positivi sulla città
    firme_da_ignorare = [
        "corso vittorio veneto 15 favara",
        "corso vittorio veneto 15",
        "corso vittorio veneto",
        "agenzia immobiliare giancani",
        "immobiliare giancani",
        "giancani"
    ]
    for firma in firme_da_ignorare:
        testo_min = testo_min.replace(firma, "")

    # 2. TROVA TIPOLOGIA
    tipologie_chiave = {
        "villa": "Villa",
        "appartamento": "Appartamento",
        "casa singola": "Casa Singola",
        "terreno": "Terreno",
        "magazzino": "Magazzino",
        "attico": "Attico",
        "b&b": "B&B",
        "colonia": "Casa in Campagna"
    }
    
    tipo_trovato = "Altro"
    for chiave, valore in tipologie_chiave.items():
        if chiave in testo_min:
            tipo_trovato = valore
            break 

    # 3. TROVA CITTÀ (Ignora la punteggiatura e mappa le contrade)
    testo_pulito = re.sub(r'[^\w\s]', ' ', testo_min)
    
    mappa_citta = {
        "favara": "Favara",
        "priolo": "Favara",
        "agrigento": "Agrigento",
        "zingarello": "Agrigento",
        "villaggio mosè": "Agrigento",
        "licata": "Licata",
        "aragona": "Aragona",
        "caldare": "Aragona",
        "lampedusa": "Lampedusa",
        "linosa": "Linosa",
        "palma di montechiaro": "Palma di Montechiaro"
    }
    
    citta_trovata = "Non specificata"
    for chiave, citta_reale in mappa_citta.items():
        # Cerca la parola esatta (es: trova "Favara" ma ignora "Favarotta")
        if re.search(r'\b' + re.escape(chiave) + r'\b', testo_pulito):
            citta_trovata = citta_reale
            break

    return tipo_trovato, citta_trovata

def main():
    print("🚀 Avvio Super Bot (Auto-Discovery + Statistiche)...")
    
    try:
        # Setup Google Sheets
        creds_dict = json.loads(GOOGLE_SECRETS)
        creds_gs = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds_gs)
        sheet = gc.open_by_key(SHEET_ID).sheet1
        
        youtube = build('youtube', 'v3', developerKey=YT_API_KEY)
        records = sheet.get_all_records()
        headers = sheet.row_values(1)
        
        # Mappatura Colonne
        try:
            idx_yt = headers.index("Link_YouTube") + 1
            idx_fb = headers.index("Link_Facebook") + 1
            idx_views = headers.index("Visualizzazioni") + 1
            idx_likes = headers.index("Mi_Piace") + 1
            idx_comments = headers.index("Commenti") + 1
        except ValueError:
            print("⚠️ Errore: Colonne non trovate! Verifica le intestazioni nel foglio Excel.")
            return

        # --- FASE 1: AUTO-DISCOVERY (Solo VIDEO e REEL) ---
        print("🕵️ Ricerca di nuovi Video e Reel su Facebook...")
        link_esistenti = [str(r.get("Link_Facebook", "")).strip() for r in records if r.get("Link_Facebook")]
        nuovi_inserimenti = []
        
        try:
            # Legge gli ultimi 25 post
            url_feed = f"https://graph.facebook.com/v18.0/me/published_posts?fields=id,message,permalink_url&limit=25&access_token={FB_PAGE_TOKEN}"
            feed_req = requests.get(url_feed).json()
            
            if 'data' in feed_req:
                for post in reversed(feed_req['data']):
                    fb_url = post.get('permalink_url', '')
                    testo_post = post.get('message', '')
                    
                    # FILTRO CRITICO: Aggiunge SOLO se l'URL contiene "videos" o "reel"
                    if fb_url and ("/videos/" in fb_url or "/reel/" in fb_url) and fb_url not in link_esistenti:
                        tipologia, citta = analizza_testo_annuncio(testo_post)
                        
                        nuova_riga = [""] * len(headers)
                        
                        if "Data Pubblicazione" in headers:
                            nuova_riga[headers.index("Data Pubblicazione")] = datetime.now().strftime("%Y-%m-%d")
                        if "Link_Facebook" in headers:
                            nuova_riga[headers.index("Link_Facebook")] = fb_url
                        if "Descrizione" in headers:
                            nuova_riga[headers.index("Descrizione")] = (testo_post[:150] + '...') if testo_post else ""
                        if "Tipologia_Immobile" in headers:
                            nuova_riga[headers.index("Tipologia_Immobile")] = tipologia
                        if "Citta" in headers:
                            nuova_riga[headers.index("Citta")] = citta
                        if "Pubblicato" in headers:
                            nuova_riga[headers.index("Pubblicato")] = "SI"
                            
                        nuovi_inserimenti.append(nuova_riga)
                        link_esistenti.append(fb_url)
                        print(f"🌟 Trovato nuovo VIDEO/REEL! Tipo: {tipologia} | Città: {citta}")
                        
        except Exception as e:
            print(f"⚠️ Errore durante l'Auto-Discovery: {e}")

        # Se ha trovato nuovi video, li aggiunge in basso
        if nuovi_inserimenti:
            sheet.append_rows(nuovi_inserimenti)
            print(f"📝 Aggiunti {len(nuovi_inserimenti)} nuovi video nel database!")
            records = sheet.get_all_records() # Ricarica per calcolare le stats dei nuovi

        # --- FASE 2: AGGIORNAMENTO STATISTICHE ---
        aggiornamenti = []
        print("🔄 Calcolo statistiche in corso...")
        
        for i, row in enumerate(records, start=2):
            yt_url = str(row.get("Link_YouTube", "")).strip()
            fb_url = str(row.get("Link_Facebook", "")).strip()
            
            if not yt_url and not fb_url:
                continue
                
            tot_views, tot_likes, tot_comments = 0, 0, 0
            
            # LETTURA YOUTUBE
            if yt_url:
                yt_id = extract_yt_id(yt_url)
                if yt_id:
                    try:
                        req = youtube.videos().list(part="statistics", id=yt_id)
                        res = req.execute()
                        if res.get('items'):
                            stats = res['items'][0]['statistics']
                            tot_views += int(stats.get('viewCount', 0))
                            tot_likes += int(stats.get('likeCount', 0))
                            tot_comments += int(stats.get('commentCount', 0))
                    except Exception:
                        pass 

            # LETTURA FACEBOOK
            if fb_url:
                fb_id = extract_fb_id(fb_url)
                if fb_id:
                    try:
                        url = f"https://graph.facebook.com/v18.0/{fb_id}?fields=views,likes.summary(true),comments.summary(true)&access_token={FB_PAGE_TOKEN}"
                        r = requests.get(url).json()
                        
                        if 'error' not in r:
                            tot_views += int(r.get('views', 0))
                            if 'likes' in r:
                                tot_likes += int(r['likes']['summary']['total_count'])
                            if 'comments' in r:
                                tot_comments += int(r['comments']['summary']['total_count'])
                    except Exception:
                        pass 
                        
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_views), 'values': [[tot_views]]})
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_likes), 'values': [[tot_likes]]})
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_comments), 'values': [[tot_comments]]})

        if aggiornamenti:
            sheet.batch_update(aggiornamenti)
            print("🎉 TUTTO FATTO! EXCEL AGGIORNATO CON SUCCESSO.")

    except Exception as e:
        print(f"❌ Errore critico nel Bot: {e}")

if __name__ == "__main__":
    main()
