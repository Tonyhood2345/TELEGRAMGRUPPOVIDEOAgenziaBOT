import os
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import re

# --- CONFIGURAZIONE SECRETS ---
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
YT_API_KEY = os.environ.get("YT_API_KEY")

# Il tuo canale YouTube e il tuo Foglio
YT_CHANNEL_ID = "UC7jCI1x_cwh_sOrNPJpaKyQ"
SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc" 

def extract_yt_id(url):
    match = re.search(r"(?:v=|youtu\.be/)([^&]+)", str(url))
    return match.group(1) if match else None

def extract_fb_id(url):
    match = re.search(r"(?:videos/|reel/|posts/)(\d+)", str(url))
    return match.group(1) if match else None

def estrai_data_ora(timestamp_str):
    """Estrae YYYY-MM-DD e HH:MM da un timestamp standard"""
    if not timestamp_str:
        return "", ""
    parti = timestamp_str.split('T')
    data = parti[0]
    ora = parti[1][:5] if len(parti) > 1 else ""
    return data, ora

def analizza_testo_annuncio(testo):
    """Analizza il testo per estrarre Tipologia Immobile, Città e Categoria Post"""
    if not testo:
        return "Altro", "Non specificata", "📢 Altro"
        
    testo_min = testo.lower()
    
    # 1. PULIZIA FIRME (Per non confondere l'indirizzo dell'agenzia)
    firme_da_ignorare = [
        "corso vittorio veneto 15 favara", "corso vittorio veneto 15", 
        "corso vittorio veneto", "agenzia immobiliare giancani", 
        "immobiliare giancani", "giancani"
    ]
    for firma in firme_da_ignorare:
        testo_min = testo_min.replace(firma, "")

    # 2. TROVA TIPOLOGIA IMMOBILE
    tipologie_chiave = {
        "villa": "Villa", "appartamento": "Appartamento", "casa singola": "Casa Singola",
        "terreno": "Terreno", "magazzino": "Magazzino", "attico": "Attico",
        "b&b": "B&B", "colonia": "Casa in Campagna"
    }
    tipo_immobile = "Altro"
    for chiave, valore in tipologie_chiave.items():
        if chiave in testo_min:
            tipo_immobile = valore
            break 

    # 3. TROVA CITTÀ 
    testo_pulito = re.sub(r'[^\w\s]', ' ', testo_min) 
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

    # 4. TROVA CATEGORIA DEL POST (Per la colonna "Tipologia" con emoji)
    categoria_post = "📢 Altro"
    if any(parola in testo_min for parola in ["ribasso", "prezzo shock", "occasione", "affare"]):
        categoria_post = "💰 Ribasso"
    elif any(parola in testo_min for parola in ["vendita", "vendesi", "comprare", "acquisto"]):
        categoria_post = "🏠 Vendita"
    elif any(parola in testo_min for parola in ["affitto", "locazione"]):
        categoria_post = "🔑 Affitto"

    return tipo_immobile, citta_trovata, categoria_post


def main():
    print("🚀 Avvio BOT DEFINITIVO (FB + IG + YT + Testo Completo + Mesi Arretrati)...")
    
    try:
        # Auth Google Sheets
        creds_dict = json.loads(GOOGLE_SECRETS)
        creds_gs = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds_gs)
        sheet = gc.open_by_key(SHEET_ID).sheet1
        
        youtube = build('youtube', 'v3', developerKey=YT_API_KEY)
        records = sheet.get_all_records()
        headers = sheet.row_values(1)
        
        # Mappatura Esatta Colonne (Zero-based index)
        col = {nome: headers.index(nome) for nome in headers if nome in headers}
        
        # Verifica colonne minime vitali
        if "Visualizzazioni" not in col or "Mi_Piace" not in col:
            print("⚠️ Errore: Colonne statistiche non trovate. Controlla che le intestazioni siano perfette.")
            return

        # --- FASE 1: AUTO-DISCOVERY (100 Post per cercare mesi indietro) ---
        print("🕵️ Ricerca di vecchi e nuovi contenuti (fino a 100 post fa)...")
        link_esistenti = [str(r.get("Link_Facebook", "")).strip() + str(r.get("Link_YouTube", "")).strip() + str(r.get("Link_Instagram", "")).strip() for r in records]
        nuovi_inserimenti = []
        
        # 1.A FACEBOOK
        try:
            url_fb = f"https://graph.facebook.com/v18.0/me/published_posts?fields=id,message,created_time,permalink_url&limit=100&access_token={FB_PAGE_TOKEN}"
            feed_fb = requests.get(url_fb).json().get('data', [])
            for post in reversed(feed_fb):
                fb_url = post.get('permalink_url', '')
                if fb_url and ("/videos/" in fb_url or "/reel/" in fb_url) and fb_url not in "".join(link_esistenti):
                    testo_post = post.get('message', '')
                    data_post, ora_post = estrai_data_ora(post.get('created_time', ''))
                    tipo_immobile, citta, cat_post = analizza_testo_annuncio(testo_post)
                    
                    riga = [""] * len(headers)
                    if "Tipo" in col: riga[col["Tipo"]] = "POST"
                    if "Data" in col: riga[col["Data"]] = data_post
                    if "Ora" in col: riga[col["Ora"]] = ora_post
                    if "Tipologia" in col: riga[col["Tipologia"]] = cat_post
                    if "Descrizione" in col: riga[col["Descrizione"]] = testo_post  # TUTTO IL TESTO, senza tagli!
                    if "Tipologia_Immobile" in col: riga[col["Tipologia_Immobile"]] = tipo_immobile
                    if "Data Pubblicazione" in col: riga[col["Data Pubblicazione"]] = data_post
                    if "Citta" in col: riga[col["Citta"]] = citta
                    if "Pubblicato" in col: riga[col["Pubblicato"]] = "SI"
                    if "Link_Facebook" in col: riga[col["Link_Facebook"]] = fb_url
                    
                    nuovi_inserimenti.append(riga)
                    link_esistenti.append(fb_url)
                    print(f"✅ Trovato FB: {citta} - {tipo_immobile} - {data_post}")
        except Exception as e: print(f"⚠️ Errore Discovery FB: {e}")

        # 1.B INSTAGRAM
        try:
            url_ig_acc = f"https://graph.facebook.com/v18.0/me?fields=instagram_business_account&access_token={FB_PAGE_TOKEN}"
            ig_data = requests.get(url_ig_acc).json()
            if 'instagram_business_account' in ig_data:
                ig_id = ig_data['instagram_business_account']['id']
                url_ig_media = f"https://graph.facebook.com/v18.0/{ig_id}/media?fields=caption,timestamp,permalink,media_type&limit=100&access_token={FB_PAGE_TOKEN}"
                feed_ig = requests.get(url_ig_media).json().get('data', [])
                for media in reversed(feed_ig):
                    ig_url = media.get('permalink', '')
                    if ig_url and media.get('media_type') in ['VIDEO', 'REELS'] and ig_url not in "".join(link_esistenti):
                        testo_post = media.get('caption', '')
                        data_post, ora_post = estrai_data_ora(media.get('timestamp', ''))
                        tipo_immobile, citta, cat_post = analizza_testo_annuncio(testo_post)
                        
                        riga = [""] * len(headers)
                        if "Tipo" in col: riga[col["Tipo"]] = "POST"
                        if "Data" in col: riga[col["Data"]] = data_post
                        if "Ora" in col: riga[col["Ora"]] = ora_post
                        if "Tipologia" in col: riga[col["Tipologia"]] = cat_post
                        if "Descrizione" in col: riga[col["Descrizione"]] = testo_post
                        if "Tipologia_Immobile" in col: riga[col["Tipologia_Immobile"]] = tipo_immobile
                        if "Data Pubblicazione" in col: riga[col["Data Pubblicazione"]] = data_post
                        if "Citta" in col: riga[col["Citta"]] = citta
                        if "Pubblicato" in col: riga[col["Pubblicato"]] = "SI"
                        if "Link_Instagram" in col: riga[col["Link_Instagram"]] = ig_url
                        
                        nuovi_inserimenti.append(riga)
                        link_esistenti.append(ig_url)
                        print(f"✅ Trovato IG: {citta} - {tipo_immobile} - {data_post}")
        except Exception as e: print(f"⚠️ Errore Discovery IG: {e}")

        # 1.C YOUTUBE
        if YT_CHANNEL_ID:
            try:
                # maxResults=50 è il massimo per chiamata API gratuita di ricerca YT, sufficiente per mesi arretrati
                req_yt = youtube.search().list(part="snippet", channelId=YT_CHANNEL_ID, maxResults=50, order="date", type="video").execute()
                for item in reversed(req_yt.get('items', [])):
                    vid_id = item['id']['videoId']
                    yt_url = f"https://www.youtube.com/watch?v={vid_id}"
                    if yt_url not in "".join(link_esistenti):
                        desc = item['snippet']['description']
                        testo_post = item['snippet']['title'] + " " + desc
                        data_post, ora_post = estrai_data_ora(item['snippet']['publishedAt'])
                        tipo_immobile, citta, cat_post = analizza_testo_annuncio(testo_post)
                        
                        riga = [""] * len(headers)
                        if "Tipo" in col: riga[col["Tipo"]] = "POST"
                        if "Data" in col: riga[col["Data"]] = data_post
                        if "Ora" in col: riga[col["Ora"]] = ora_post
                        if "Tipologia" in col: riga[col["Tipologia"]] = cat_post
                        if "Descrizione" in col: riga[col["Descrizione"]] = testo_post
                        if "Tipologia_Immobile" in col: riga[col["Tipologia_Immobile"]] = tipo_immobile
                        if "Data Pubblicazione" in col: riga[col["Data Pubblicazione"]] = data_post
                        if "Citta" in col: riga[col["Citta"]] = citta
                        if "Pubblicato" in col: riga[col["Pubblicato"]] = "SI"
                        if "Link_YouTube" in col: riga[col["Link_YouTube"]] = yt_url
                        
                        nuovi_inserimenti.append(riga)
                        link_esistenti.append(yt_url)
                        print(f"✅ Trovato YT: {citta} - {tipo_immobile} - {data_post}")
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
            
            # Formattazione per la batch_update (usando col)
            idx_v = col["Visualizzazioni"] + 1
            idx_l = col["Mi_Piace"] + 1
            idx_c = col["Commenti"] + 1
            
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_v), 'values': [[tot_views]]})
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_l), 'values': [[tot_likes]]})
            aggiornamenti.append({'range': gspread.utils.rowcol_to_a1(i, idx_c), 'values': [[tot_comments]]})

        if aggiornamenti:
            sheet.batch_update(aggiornamenti)
            print("🎉 STATISTICHE TOTALI AGGIORNATE.")

    except Exception as e:
        print(f"❌ Errore critico nel Bot: {e}")

if __name__ == "__main__":
    main()
