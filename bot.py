import os
import json
import requests
import gspread
import base64
import time
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as OauthCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from datetime import datetime

# --- CONFIGURAZIONE SEGRETI ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
WP_PASSWORD = os.environ.get("WP_PASSWORD")
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
YT2_CLIENT_ID = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN = os.environ.get("YT2_REFRESH_TOKEN")

# Segreti Facebook
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")

WP_USER = "Antonio Giancani"
WP_API_URL = "https://www.immobiliaregiancani.it/wp-json/wp/v2/property"
SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"


# --- VALIDAZIONE SECRETS ALL'AVVIO ---
def validate_secrets():
    required = {
        "GOOGLE_APPLICATION_CREDENTIALS": GOOGLE_SECRETS,
        "YT2_CLIENT_ID": YT2_CLIENT_ID,
        "YT2_CLIENT_SECRET": YT2_CLIENT_SECRET,
        "YT2_REFRESH_TOKEN": YT2_REFRESH_TOKEN,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(
            f"❌ Variabili d'ambiente mancanti: {', '.join(missing)}\n"
            "Vai su GitHub → Settings → Secrets and variables → Actions\n"
            "e assicurati che i nomi corrispondano esattamente."
        )
    try:
        json.loads(GOOGLE_SECRETS)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"❌ GOOGLE_APPLICATION_CREDENTIALS non è un JSON valido: {e}\n"
            "Assicurati di incollare il contenuto completo del file .json."
        )
    print("✅ Tutti i secrets essenziali sono presenti e validi.")


# --- AUTENTICAZIONE GOOGLE ---
def get_google_services():
    creds_dict = json.loads(GOOGLE_SECRETS)

    creds_gspread = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ])

    creds_yt = OauthCredentials(
        token=None,
        refresh_token=YT2_REFRESH_TOKEN,
        client_id=YT2_CLIENT_ID,
        client_secret=YT2_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token"
    )

    gc = gspread.authorize(creds_gspread)
    drive = build('drive', 'v3', credentials=creds_gspread)
    youtube = build('youtube', 'v3', credentials=creds_yt)

    return gc, drive, youtube


# --- CERCA FILE SU DRIVE PER NOME ---
def cerca_id_drive_per_nome(drive_service, nome_file):
    try:
        nome_escaped = nome_file.replace("'", "\\'")
        query = f"name = '{nome_escaped}' and trashed = false"
        result = drive_service.files().list(
            q=query, spaces='drive', fields='files(id, name)', pageSize=1
        ).execute()

        files = result.get('files', [])
        if not files:
            print(f"⚠️ File '{nome_file}' non trovato su Google Drive.")
            return None

        file_id = files[0]['id']
        print(f"✅ Trovato su Drive: '{nome_file}' → ID: {file_id}")
        return file_id
    except Exception as e:
        print(f"❌ Errore ricerca Drive per '{nome_file}': {e}")
        return None


# --- PUBBLICAZIONE YOUTUBE ---
def posta_su_youtube(youtube, file_path, titolo, descrizione):
    try:
        print(f"🎬 Caricamento su YouTube: {titolo}")
        body = {
            'snippet': {
                'title': titolo,
                'description': descrizione,
                'tags': ['immobiliare', 'casa', 'vendita', 'Favara', 'Sicilia']
            },
            'status': {
                'privacyStatus': 'public',
                'selfDeclaredMadeForKids': False
            }
        }
        insert_request = youtube.videos().insert(
            part='snippet,status',
            body=body,
            media_body=MediaFileUpload(file_path, chunksize=-1, resumable=True)
        )
        response = insert_request.execute()
        link = f"https://www.youtube.com/watch?v={response['id']}"
        print(f"✅ YouTube OK: {link}")
        return link
    except Exception as e:
        print(f"❌ Errore YouTube: {e}")
        return None


# --- PUBBLICAZIONE WORDPRESS ---
def posta_su_wordpress(titolo, testo, yt_url):
    if not WP_PASSWORD:
        print("⚠️ WP_PASSWORD non impostata, salto WordPress.")
        return None
    try:
        video_id = yt_url.split("v=")[-1] if "v=" in yt_url else yt_url.split("/")[-1]
        video_html = (
            f'\n\n<iframe width="560" height="315" '
            f'src="https://www.youtube.com/embed/{video_id}" '
            f'frameborder="0" allowfullscreen></iframe>\n\n'
        )
        auth_str = f"{WP_USER}:{WP_PASSWORD}"
        auth_base64 = base64.b64encode(auth_str.encode()).decode()
        headers = {
            'Authorization': f'Basic {auth_base64}',
            'Content-Type': 'application/json'
        }
        payload = {
            'title': titolo,
            'content': testo + video_html,
            'status': 'publish'
        }
        r = requests.post(WP_API_URL, headers=headers, json=payload, timeout=30)
        if r.status_code == 201:
            link = r.json().get('link')
            print(f"✅ WordPress OK: {link}")
            return link
        else:
            print(f"⚠️ WordPress risposta inattesa: {r.status_code} - {r.text[:200]}")
            return None
    except Exception as e:
        print(f"❌ Errore WordPress: {e}")
        return None


# --- PUBBLICAZIONE FACEBOOK ---
def posta_su_facebook(testo, video_path):
    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("⚠️ FB_PAGE_TOKEN o FB_PAGE_ID non impostati, salto Facebook.")
        return None
    try:
        print("🟦 Caricamento su Facebook in corso...")
        url = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/videos"
        payload = {
            'access_token': FB_PAGE_TOKEN,
            'description': testo
        }
        with open(video_path, 'rb') as f:
            files = {'source': f}
            r = requests.post(url, data=payload, files=files, timeout=300) # Timeout lungo per i video
            
        if r.status_code == 200:
            video_id = r.json().get('id')
            link = f"https://www.facebook.com/{FB_PAGE_ID}/videos/{video_id}"
            print(f"✅ Facebook OK: {link}")
            return link
        else:
            print(f"⚠️ Errore API Facebook: {r.status_code} - {r.text}")
            return None
    except Exception as e:
        print(f"❌ Errore Facebook: {e}")
        return None


# --- PUBBLICAZIONE TELEGRAM ---
def posta_su_telegram(testo, video_path=None):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ TELEGRAM_TOKEN o CHAT_ID non impostati, salto Telegram.")
        return
    try:
        if video_path and os.path.exists(video_path):
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
            with open(video_path, "rb") as f:
                r = requests.post(
                    url,
                    data={"chat_id": CHAT_ID, "caption": testo[:1024], "parse_mode": "HTML"},
                    files={"video": f},
                    timeout=120
                )
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            r = requests.post(
                url,
                json={"chat_id": CHAT_ID, "text": testo, "parse_mode": "HTML"},
                timeout=30
            )
        if r.status_code == 200:
            print("✅ Telegram OK")
        else:
            print(f"⚠️ Telegram risposta inattesa: {r.status_code} - {r.text[:200]}")
    except Exception as e:
        print(f"❌ Errore Telegram: {e}")


# --- CORE DEL BOT ---
def main():
    # 1. Valida secrets
    validate_secrets()

    # 2. Autenticazione
    gc, drive_service, youtube_service = get_google_services()
    sheet = gc.open_by_key(SHEET_ID).sheet1
    records = sheet.get_all_records()

    # 3. Trova colonna "Pubblicato" dinamicamente
    headers = sheet.row_values(1)
    print(f"📋 Colonne trovate nel foglio: {headers}")

    try:
        col_pub_idx = headers.index("Pubblicato") + 1
    except ValueError:
        print("❌ Colonna 'Pubblicato' non trovata nel foglio!")
        print(f"   Colonne disponibili: {headers}")
        return

    processati = 0
    saltati = 0

    for i, post in enumerate(records, start=2):

        # Salta righe già pubblicate
        if str(post.get("Pubblicato", "")).strip().upper() == "SI":
            saltati += 1
            continue

        # Legge i campi dalle colonne reali del foglio
        nome_file   = str(post.get("Nome_File_Video", "")).strip()
        descrizione = str(post.get("Descrizione", "")).strip()
        data_post   = str(post.get("Data", datetime.now().strftime("%Y-%m-%d"))).strip()
        tipologia   = str(post.get("Tipologia", "Immobile")).strip()

        # Salta righe senza video associato
        if not nome_file:
            continue

        print(f"\n🆕 Elaborazione riga {i}: {nome_file} ({tipologia} - {data_post})")

        # Titolo da usare su YouTube e WordPress
        titolo_video = f"Immobiliare Giancani - {tipologia} - {data_post}"

        # 4. Cerca il file su Google Drive per nome
        drive_file_id = cerca_id_drive_per_nome(drive_service, nome_file)
        if not drive_file_id:
            print(f"⏭️ Riga {i} saltata: '{nome_file}' non trovato su Drive.")
            continue

        # 5. Scarica il video da Drive
        video_locale = f"temp_video_{i}.mp4"
        try:
            request = drive_service.files().get_media(fileId=drive_file_id)
            with open(video_locale, "wb") as f:
                f.write(request.execute())
            print(f"✅ Video scaricato: {video_locale}")
        except Exception as e:
            print(f"❌ Errore download Drive (riga {i}): {e}")
            if os.path.exists(video_locale):
                os.remove(video_locale)
            continue

        # 6. Pubblica su YouTube
        yt_link = posta_su_youtube(youtube_service, video_locale, titolo_video, descrizione)
        if not yt_link:
            print("🛑 Errore critico YouTube (probabile limite giornaliero raggiunto). Mi fermo qui.")
            if os.path.exists(video_locale):
                os.remove(video_locale)
            break # FERMA IL BOT IN CASO DI ERRORE YOUTUBE

        # 7. Pubblica su WordPress
        wp_link = posta_su_wordpress(titolo_video, descrizione, yt_link)

        # 8. Pubblica su Facebook (NUOVO)
        testo_fb = f"{titolo_video}\n\n{descrizione}"
        fb_link = posta_su_facebook(testo_fb, video_locale)

        # 9. Componi messaggio e pubblica su Telegram
        desc_troncata = descrizione[:500] + "..." if len(descrizione) > 500 else descrizione
        testo_social = (
            f"🏠 <b>{tipologia} - {data_post}</b>\n\n"
            f"{desc_troncata}\n\n"
            f"📺 <a href='{yt_link}'>Guarda su YouTube</a>"
        )
        if wp_link:
            testo_social += f"\n🌐 <a href='{wp_link}'>Vedi sul sito</a>"
        if fb_link:
            testo_social += f"\n🟦 <a href='{fb_link}'>Vedi su Facebook</a>"

        posta_su_telegram(testo_social, video_locale)

        # 10. Segna come pubblicato nel foglio
        sheet.update_cell(i, col_pub_idx, "SI")
        print(f"✅ Riga {i} completata e segnata come SI.")
        processati += 1

        # 11. Pulizia file temporaneo
        if os.path.exists(video_locale):
            os.remove(video_locale)

        # 🛑 STOP: Ferma il ciclo dopo aver pubblicato 1 singolo video con successo
        print("\n🛑 Pubblicazione di UN video completata! Il bot si ferma qui fino a domani.")
        break 

    print(f"\n🏁 Bot completato. Processati oggi: {processati} | Già pubblicati saltati: {saltati}")


if __name__ == "__main__":
    main()
