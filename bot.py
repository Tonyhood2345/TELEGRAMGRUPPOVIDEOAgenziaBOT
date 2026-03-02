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
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
YT2_CLIENT_ID = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN = os.environ.get("YT2_REFRESH_TOKEN")
WP_PASSWORD = os.environ.get("WP_PASSWORD")
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")

WP_USER = "Antonio Giancani"
WP_API_URL = "https://www.immobiliaregiancani.it/wp-json/wp/v2/property"
SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"


# --- VALIDAZIONE SECRETS ALL'AVVIO ---
def validate_secrets():
    required = {
        "GOOGLE_APPLICATION_CREDENTIALS_JSON": GOOGLE_SECRETS,
        "YT2_CLIENT_ID": YT2_CLIENT_ID,
        "YT2_CLIENT_SECRET": YT2_CLIENT_SECRET,
        "YT2_REFRESH_TOKEN": YT2_REFRESH_TOKEN,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(
            f"❌ Variabili d'ambiente mancanti: {', '.join(missing)}\n"
            "Controlla i Secrets nelle impostazioni del repository GitHub."
        )
    # Verifica che GOOGLE_SECRETS sia un JSON valido
    try:
        json.loads(GOOGLE_SECRETS)
    except json.JSONDecodeError as e:
        raise ValueError(f"❌ GOOGLE_APPLICATION_CREDENTIALS_JSON non è un JSON valido: {e}")
    print("✅ Tutti i secrets sono presenti e validi.")


# --- FUNZIONI DI AUTENTICAZIONE ---
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


# --- FUNZIONI DI PUBBLICAZIONE ---
def posta_su_youtube(youtube, file_path, titolo, descrizione):
    try:
        print(f"🎬 Caricamento su YouTube: {titolo}")
        body = {
            'snippet': {
                'title': titolo,
                'description': descrizione,
                'tags': ['immobiliare', 'casa', 'vendita']
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


def posta_su_wordpress_ere(titolo, testo, yt_url):
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


def posta_su_telegram(testo, video_path=None):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ TELEGRAM_TOKEN o CHAT_ID non impostati, salto Telegram.")
        return
    try:
        if video_path and os.path.exists(video_path):
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
            with open(video_path, "rb") as f:
                r = requests.post(url, data={"chat_id": CHAT_ID, "caption": testo, "parse_mode": "HTML"}, files={"video": f}, timeout=120)
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            r = requests.post(url, json={"chat_id": CHAT_ID, "text": testo, "parse_mode": "HTML"}, timeout=30)
        if r.status_code == 200:
            print("✅ Telegram OK")
        else:
            print(f"⚠️ Telegram risposta inattesa: {r.status_code} - {r.text[:200]}")
    except Exception as e:
        print(f"❌ Errore Telegram: {e}")


# --- CORE DEL BOT ---
def main():
    # 1. Valida tutti i secrets prima di fare qualsiasi cosa
    validate_secrets()

    # 2. Autenticazione
    gc, drive_service, youtube_service = get_google_services()
    sheet = gc.open_by_key(SHEET_ID).sheet1
    records = sheet.get_all_records()

    # 3. Trova colonna "Pubblicato" dinamicamente
    headers = sheet.row_values(1)
    try:
        col_pub_idx = headers.index("Pubblicato") + 1
    except ValueError:
        print("❌ Colonna 'Pubblicato' non trovata nel foglio!")
        return

    for i, post in enumerate(records, start=2):
        if str(post.get("Pubblicato", "")).strip().upper() == "SI":
            continue

        titolo_riga = post.get('Titolo', f'Riga {i}')
        print(f"\n🆕 Elaborazione riga {i}: {titolo_riga}")

        video_id_drive = post.get("ID_Video_Drive", "").strip()
        if not video_id_drive:
            print(f"⚠️ Nessun ID_Video_Drive per riga {i}, salto.")
            continue

        desc_base = post.get("Descrizione", "")
        data_sheet = post.get("Data", datetime.now().strftime("%d/%m/%Y"))
        titolo_video = f"Casa a Favara - {data_sheet}"
        video_local = f"temp_video_{i}.mp4"

        # 4. Download da Drive
        try:
            request = drive_service.files().get_media(fileId=video_id_drive)
            with open(video_local, "wb") as f:
                f.write(request.execute())
            print(f"✅ Video scaricato: {video_local}")
        except Exception as e:
            print(f"❌ Errore download Drive (riga {i}): {e}")
            continue

        # 5. Pubblica su YouTube
        yt_link = posta_su_youtube(youtube_service, video_local, titolo_video, desc_base)
        if not yt_link:
            if os.path.exists(video_local):
                os.remove(video_local)
            continue

        # 6. Pubblica su WordPress
        wp_link = posta_su_wordpress_ere(f"Immobile del {data_sheet}", desc_base, yt_link)

        # 7. Pubblica su Telegram
        testo_social = f"🏠 <b>Nuova Proposta {data_sheet}</b>\n\n{desc_base}\n\n📺 YouTube: {yt_link}"
        if wp_link:
            testo_social += f"\n🌐 Sito: {wp_link}"
        posta_su_telegram(testo_social, video_local)

        # 8. Segna come pubblicato nel foglio
        sheet.update_cell(i, col_pub_idx, "SI")
        print(f"✅ Riga {i} completata e segnata come SI.")

        # 9. Pulizia file temporaneo
        if os.path.exists(video_local):
            os.remove(video_local)

        time.sleep(5)

    print("\n🏁 Bot completato.")


if __name__ == "__main__":
    main()
