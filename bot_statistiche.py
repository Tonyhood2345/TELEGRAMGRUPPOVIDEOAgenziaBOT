import os
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import re
from datetime import datetime

# --- CONFIGURAZIONE SECRETS ---
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
YT_API_KEY = os.environ.get("YT_API_KEY")
YT_CHANNEL_ID = os.environ.get("YT_CHANNEL_ID") # Aggiungi questo su GitHub per trovare i nuovi video YT

SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc" 

def extract_yt_id(url):
    match = re.search(r"(?:v=|youtu\.be/)([^&]+)", str(url))
    return match.group(1) if match else None

def extract_fb_id(url):
    match = re.search(r"(?:videos/|reel/|posts/)(\d+)", str(url))
    return match.group(1) if match else None

def analizza_testo_annuncio(testo):
    """Analizza il testo del post per estrarre Tipologia e Città in modo intelligente"""
    if not testo:
        return "Altro", "Non specificata"
        
    testo_min = testo.lower()
    
    # 1. PULIZIA FIRME (Evita che il bot metta "Favara" ovunque a causa della sede agenzia)
    firme_da_ignorare = [
        "corso vittorio veneto 15 favara", "corso vittorio veneto 15", 
        "corso vittorio veneto", "agenzia immobiliare giancani", 
        "immobiliare giancani", "giancani"
    ]
    for firma in firme_da_ignorare:
        testo_min = testo_min.replace(firma, "")

    # 2. TROVA TIPOLOGIA
    tipologie_chiave = {
        "villa": "Villa", "appartamento": "Appartamento", "casa singola": "Casa Singola",
        "terreno": "Terreno", "magazzino": "Magazzino", "attico": "Attico",
        "b&b": "B&B", "colonia": "Casa in Campagna"
    }
    
    tipo_trovato = "Altro"
    for chiave, valore in tipologie_chiave.items():
        if chiave in testo_min:
            tipo_trovato = valore
            break 

    # 3. TROVA CITTÀ 
    testo_pulito = re.sub(r'[^\w\s]', ' ', testo_min) # Rimuove la punteggiatura
    
    mappa_citta = {
        "favara": "Favara", "priolo": "Favara",
        "agrigento": "Agrigento", "zingarello": "Agrigento", "villaggio mosè": "Agrigento",
        "licata": "Licata", "aragona": "Aragona", "caldare": "Aragona",
        "lampedusa": "Lampedusa", "linosa": "Linosa", "palma di montechiaro": "Palma di Montechiaro"
    }
    
    citta_trovata = "Non specificata"
    for chiave, citta_reale in mappa_citta.items():
        if re.search(r'\b' + re.escape(chiave) + r'\b', testo_pulito):
            citta_trovata = citta_reale
            break

    return tipo_trovato, citta_trovata

def main():
    print("🚀 Avvio BOT OMNISCIENTE (FB + IG + YT + Statistiche)...")
    
    try:
        # Auth Google Sheets
        creds_dict = json.loads(GOOGLE_SECRETS)
        creds_gs = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds_gs)
        sheet = gc.open_by_key(SHEET_ID).sheet1
        
        youtube = build('youtube', 'v3', developerKey=YT_API_KEY)
        records = sheet.get_all_records()
        headers = sheet.row_values(1)
        
        # Mapping dinamico di tutte le colonne
        col = {nome: headers.index(nome) + 1 for nome in headers}
        idx_views, idx_likes, idx_comments = col.get("Visualizzazioni"), col.get("Mi_Piace"), col.get("Commenti")
        
        if not all([idx_views, idx_likes, idx_comments]):
            print("⚠️ Errore: Colonne statistiche base mancanti nel foglio Excel.")
            return

        # --- FASE 1: AUTO-DISCOVERY MULTI PIATTAFORMA ---
        print("🕵️ Ricerca di nuovi contenuti sui social...")
        link_esistenti = [str(r.get("Link_Facebook", "")).strip() + str(r.get("Link_YouTube", "")).strip() + str(r.get("Link_Instagram", "")).strip() for r in records]
        nuovi_inserimenti = []
        
        # 1.A FACEBOOK AUTO-DISCOVERY
        try:
            url_fb = f"https://graph.facebook.com/v18.0/me/published_posts?fields=id,message,permalink_url&limit=20&access_token={FB_PAGE_TOKEN}"
            feed_fb = requests.get(url_fb).json().get('data', [])
            for post in reversed(feed_fb):
                fb_url = post.get('permalink_url', '')
                if fb_url and ("/videos/" in fb_url or "/reel/" in fb_url) and fb_url not in "".join(link_esistenti):
                    tipologia, citta = analizza_testo_annuncio(post.get('message', ''))
                    riga = [""] * len(headers)
                    if "Tipo" in headers: riga[col["Tipo"]-1] = "POST"
                    if "Data Pubblicazione" in headers: riga[col["Data Pubblicazione"]-1] = datetime.now().strftime("%Y-%m-%d")
                    if "Link_Facebook" in headers: riga[col["Link_Facebook"]-1] = fb_url
                    if "Descrizione" in headers: riga[col["Descrizione"]-1] = (post.get('message', '')[:100] + '...')
                    if "Tipologia_Immobile" in headers: riga[col["Tipologia_Immobile"]-1] = tipologia
                    if "Citta" in headers: riga[col["Citta"]-1] = citta
                    if "Pubblicato" in headers: riga[col["Pubblicato"]-1] = "SI"
                    nuovi_inserimenti.append(riga)
                    link_esistenti.append(fb_url)
                    print(f"✅ Trovato nuovo video FB: {citta} - {tipologia}")
        except Exception as e: print(f"⚠️ Errore Discovery FB: {e}")

        # 1.B INSTAGRAM AUTO-DISCOVERY (Se collegato a Facebook)
        try:
            url_ig_acc = f"https://graph.facebook.com/v18.0/me?fields=instagram_business_account&access_token={FB_PAGE_TOKEN}"
            ig_data = requests.get(url_ig_acc).json()
            if 'instagram_business_account' in ig_data:
                ig_id = ig_data['instagram_business_account']['id']
                url_ig_media = f"https://graph.facebook.com/v18.0/{ig_id}/media?fields=caption,permalink,media_type&limit=20&access_token={FB_PAGE_TOKEN}"
                feed_ig = requests.get(url_ig_media).json().get('data', [])
                for media in reversed(feed_ig):
                    ig_url = media.get('permalink', '')
                    if ig_url and media.get('media_type') in ['VIDEO', 'REELS'] and ig_url not in "".join(link_esistenti):
                        tipologia, citta = analizza_testo_annuncio(media.get('caption', ''))
                        riga = [""] * len(headers)
                        if "Tipo" in headers: riga[col["Tipo"]-1] = "POST"
                        if "Data Pubblicazione" in headers: riga[col["Data Pubblicazione"]-1] = datetime.now().strftime("%Y-%m-%d")
                        if "Link_Instagram" in headers: riga[col["Link_Instagram"]-1] = ig_url
                        if "Descrizione" in headers: riga[col["Descrizione"]-1] = (media.get('caption', '')[:100] + '...')
                        if "Tipologia_Immobile" in headers: riga[col["Tipologia_Immobile"]-1] = tipologia
                        if "Citta" in headers: riga[col["Citta"]-1] = citta
                        if "Pubblicato" in headers: riga[col["Pubblicato"]-1] = "SI"
                        nuovi_inserimenti.append(riga)
                        link_esistenti.append(ig_url)
                        print(f"✅ Trovato nuovo Reel IG: {citta} - {tipologia}")
        except Exception as e: print(f"⚠️ Errore Discovery IG: {e}")

        # 1.C YOUTUBE AUTO-DISCOVERY
        if YT_CHANNEL_ID:
            try:
                req_yt = youtube.search().list(part="snippet", channelId=YT_CHANNEL_ID, maxResults=15, order="date", type="video").execute()
                for item in reversed(req_yt.get('items', [])):
                    vid_id = item['id']['videoId']
                    yt_url = f"https://www.youtube.com/watch?v={vid_id}"
                    if yt_url not in "".join(link_esistenti):
                        desc = item['snippet']['description']
                        tipologia, citta = analizza_testo_annuncio(item['snippet']['title'] + " " + desc)
                        riga = [""] * len(headers)
                        if "Tipo" in headers: riga[col["Tipo"]-1] = "POST"
                        if "Data Pubblicazione" in headers: riga[col["Data Pubblicazione"]-1] = datetime.now().strftime("%Y-%m-%d")
                        if "Link_YouTube" in headers: riga[col["Link_YouTube"]-1] = yt_url
                        if "Descrizione" in headers: riga[col["Descrizione"]-1] = item['snippet']['title']
                        if "Tipologia_Immobile" in headers: riga[col["Tipologia_Immobile"]-1] = tipologia
                        if "Citta" in headers: riga[col["Citta"]-1] = citta
                        if "Pubblicato" in headers: riga[col["Pubblicato"]-1] = "SI"
                        nuovi_inserimenti.append(riga)
                        link_esistenti.append(yt_url)
                        print(f"✅ Trovato nuovo Video YT: {citta} - {tipologia}")
            except Exception as e: print(f"⚠️ Errore Discovery YT: {e}")

        if nuovi_inserimenti:
            sheet.append_rows(nuovi_inserimenti)
            print(f"📝 {len(nuovi_inserimenti)} nuovi inserimenti caricati perfettamente nel foglio!")
            records = sheet.get_all_records()

        # --- FASE 2: AGGIORNAMENTO STATISTICHE GLOBALI ---
        aggiornamenti = []
        print("🔄 Calcolo visualizzazioni globali...")
        
        for i, row in enumerate(records, start=2):
            yt_url = str(row.get("Link_YouTube", "")).strip()
            fb_url = str(row.get("Link_Facebook", "")).strip()
            
            if not yt_url and not fb_url:
                continue
                
            tot_views, tot_likes, tot_comments = 0, 0, 0
            
            if yt_url:
                yt_id = extract_yt_id(yt_url)
                if yt_id:
                    try:
                        res = youtube.videos().list(part="statistics", id=yt_id).execute()
                        if res.get('items'):
                            st = res['items'][0]['statistics']
                            tot_views += int(st.get('viewCount', 0))
                            tot_likes += int(st.get('likeCount', 0))
                            tot_comments += int(st.get('commentCount', 0))
                    except: pass 

            if fb_url:
                fb_id = extract_fb_id(fb_url)
                if fb_id:
                    try:
                        r = requests.get(f"https://graph.facebook.com/v18.0/{fb_id}?fields=views,likes.summary(true),comments.summary(true)&access_token={FB_PAGE_TOKEN}").json()
                        if 'error' not in r:
                            tot_views += int(r.get('views', 0))
                            if 'likes' in r: tot_likes += int(r['likes']['summary']['total_count'])
                            if 'comments' in r: tot_comments += int(r['comments']['summary']['total_count'])
                    except: pass 
                        
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_views), 'values': [[tot_views]]})
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_likes), 'values': [[tot_likes]]})
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_comments), 'values': [[tot_comments]]})

        if aggiornamenti:
            sheet.batch_update(aggiornamenti)
            print("🎉 STATISTICHE TOTALI AGGIORNATE.")

    except Exception as e:
        print(f"❌ Errore critico nel Bot: {e}")

if __name__ == "__main__":
    main()
