import os
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# --- VARIABILI SEGRETE PRESE DA GITHUB SECRETS ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"

def get_sheet_client():
    if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        print("❌ ERRORE: Variabile GOOGLE_APPLICATION_CREDENTIALS mancante.")
        return None
        
    info = json.loads(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

def posta_su_telegram(testo, image_url=None):
    if image_url:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        data = {'chat_id': CHAT_ID, 'photo': image_url, 'caption': testo[:1024]}
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {'chat_id': CHAT_ID, 'text': testo}
    
    r = requests.post(url, data=data)
    return r.status_code == 200

def posta_su_facebook(testo, image_url=None):
    if image_url:
        url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos"
        data = {
            'url': image_url,
            'message': testo,
            'access_token': FB_PAGE_TOKEN
        }
    else:
        url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/feed"
        data = {
            'message': testo,
            'access_token': FB_PAGE_TOKEN
        }
    
    r = requests.post(url, data=data)
    return r.status_code == 200

def estrai_url_immagine(anteprima_str):
    """Estrae l'URL dell'immagine dalla formula =IMAGE("url")"""
    if 'IMAGE("' in anteprima_str:
        return anteprima_str.split('IMAGE("')[1].split('")')[0]
    return None

def main():
    print("🔍 Connessione a Google Sheets...")
    client = get_sheet_client()
    if not client: return
    
    # Apri il foglio e prendi tutti i record
    sheet = client.open_by_key(SHEET_ID).sheet1
    records = sheet.get_all_records()
    
    # Trova la riga da pubblicare (la più vecchia non ancora pubblicata)
    # Assumiamo che tu abbia aggiunto una colonna "Pubblicato"
    riga_da_pubblicare = None
    indice_riga = 2 # Parte da 2 perché la riga 1 è l'intestazione
    
    # Ordiniamo i record per data (dal più vecchio al più nuovo) se necessario,
    # altrimenti assumiamo che scansionando dall'alto verso il basso (se ordinati nel foglio) 
    # o dal basso verso l'alto troviamo quello giusto.
    # Qui scansioniamo i record e prendiamo il primo che NON ha "SI" in Pubblicato.
    
    # Per essere sicuri di prendere la data più vecchia, filtriamo e ordiniamo in Python
    post_non_pubblicati = []
    for i, row in enumerate(records):
        pubblicato = str(row.get('Pubblicato', '')).strip().upper()
        if pubblicato != 'SI':
            post_non_pubblicati.append((i + 2, row)) # +2 per l'indice reale nel foglio
            
    if not post_non_pubblicati:
        print("✅ Nessun nuovo post da pubblicare. Tutti i post sono segnati come 'SI'.")
        return

    # Ordina per data (colonna 'Data') e prendi il più vecchio
    post_non_pubblicati.sort(key=lambda x: datetime.strptime(x[1]['Data'], "%Y-%m-%d"))
    
    indice_riga, post = post_non_pubblicati[0]
    
    descrizione = post.get('Descrizione', '')
    anteprima = post.get('Anteprima', '')
    immagine_url = estrai_url_immagine(anteprima)
    
    print(f"🚀 Pubblicazione del post del {post['Data']} in corso...")
    
    # 1. Pubblica su Telegram
    tg_ok = posta_su_telegram(descrizione, immagine_url)
    if tg_ok:
        print("✅ Pubblicato su Telegram!")
    else:
        print("❌ Errore pubblicazione Telegram")

    # 2. Pubblica su Facebook
    fb_ok = posta_su_facebook(descrizione, immagine_url)
    if fb_ok:
        print("✅ Pubblicato su Facebook!")
    else:
        print("❌ Errore pubblicazione Facebook")
        
    # 3. Aggiorna il foglio Google se almeno uno è andato a buon fine
    if tg_ok or fb_ok:
        # Trova l'indice della colonna "Pubblicato"
        intestazioni = sheet.row_values(1)
        if "Pubblicato" in intestazioni:
            col_index = intestazioni.index("Pubblicato") + 1
            sheet.update_cell(indice_riga, col_index, "SI")
            print(f"📝 Foglio aggiornato: Riga {indice_riga} marcata come pubblicata.")
        else:
            print("⚠️ Colonna 'Pubblicato' non trovata nel foglio! Assicurati di crearla.")

if __name__ == "__main__":
    main()
