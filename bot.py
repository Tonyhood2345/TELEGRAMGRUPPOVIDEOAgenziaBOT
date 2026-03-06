import os
import json
import requests
import gspread
import base64
import time
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as OauthCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from datetime import datetime, timedelta
import io

# --- CONFIGURAZIONE SEGRETI ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
WP_PASSWORD = os.environ.get("WP_PASSWORD")
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
YT2_CLIENT_ID = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN = os.environ.get("YT2_REFRESH_TOKEN")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")

WP_USER = "Antonio Giancani"
WP_API_URL = "https://www.immobiliaregiancani.it/wp-json/wp/v2/property"
SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"

# Nome della cartella su Google Drive dove salvare i video scaricati da FB
DRIVE_FOLDER_NAME = "Video_Da_Ripubblicare"

# Quanti giorni aspettare prima di ripubblicare un video (default: 30)
GIORNI_RIPUBBLICAZIONE = 30


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


# --- CERCA O CREA CARTELLA SU DRIVE ---
def get_or_create_drive_folder(drive_service, folder_name):
    """Cerca una cartella su Drive per nome, la crea se non esiste. Restituisce l'ID."""
    try:
        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        result = drive_service.files().list(
            q=query, spaces='drive', fields='files(id, name)', pageSize=1
        ).execute()
        files = result.get('files', [])
        if files:
            folder_id = files[0]['id']
            print(f"📁 Cartella Drive trovata: '{folder_name}' → {folder_id}")
            return folder_id
        # Crea la cartella
        metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = drive_service.files().create(body=metadata, fields='id').execute()
        folder_id = folder.get('id')
        print(f"📁 Cartella Drive creata: '{folder_name}' → {folder_id}")
        return folder_id
    except Exception as e:
        print(f"❌ Errore get/create cartella Drive: {e}")
        return None


# --- UPLOAD FILE SU DRIVE ---
def upload_video_su_drive(drive_service, local_path, nome_file, folder_id=None):
    """Carica un file video su Google Drive. Restituisce l'ID del file caricato."""
    try:
        metadata = {'name': nome_file}
        if folder_id:
            metadata['parents'] = [folder_id]
        media = MediaFileUpload(local_path, mimetype='video/mp4', resumable=True)
        file = drive_service.files().create(
            body=metadata, media_body=media, fields='id'
        ).execute()
        file_id = file.get('id')
        print(f"✅ Video caricato su Drive: '{nome_file}' → ID: {file_id}")
        return file_id
    except Exception as e:
        print(f"❌ Errore upload su Drive: {e}")
        return None


# ============================================================
# --- NUOVA FUNZIONE: SINCRONIZZA VIDEO DA FACEBOOK A SHEET ---
# ============================================================
def sincronizza_video_da_facebook(sheet, drive_service):
    """
    Controlla la pagina Facebook alla ricerca di video e reel nuovi.
    Per ogni video nuovo (non già presente nello sheet):
      1. Lo scarica temporaneamente
      2. Lo carica su Google Drive nella cartella dedicata
      3. Aggiunge una nuova riga allo sheet con data futura (+GIORNI_RIPUBBLICAZIONE)
         e Pubblicato = NO, pronto per essere ripubblicato dal bot in futuro
    """
    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("⚠️ FB_PAGE_TOKEN o FB_PAGE_ID mancanti. Salto sincronizzazione Facebook.")
        return

    print("\n🔍 Inizio sincronizzazione video da Facebook...")

    # Recupera tutti i Nome_File_Video già presenti nello sheet per evitare doppioni
    records = sheet.get_all_records()
    headers = sheet.row_values(1)
    nomi_esistenti = set(
        str(r.get("Nome_File_Video", "")).strip()
        for r in records
        if str(r.get("Nome_File_Video", "")).strip()
    )
    # Recupera anche gli fb_video_id già salvati per controllo doppio
    fb_ids_esistenti = set(
        str(r.get("FB_Video_ID", "")).strip()
        for r in records
        if str(r.get("FB_Video_ID", "")).strip()
    )

    print(f"   📋 Video già presenti nello sheet: {len(nomi_esistenti)}")

    # Cerca o crea la cartella su Drive
    folder_id = get_or_create_drive_folder(drive_service, DRIVE_FOLDER_NAME)

    # Recupera i video dalla pagina Facebook tramite Graph API
    # Prende sia i "video" che i "reels" (i reels sono video con post_type=reel)
    nuovi_aggiunti = 0
    url = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/videos"
    params = {
        "access_token": FB_PAGE_TOKEN,
        "fields": "id,title,description,created_time,source,permalink_url",
        "limit": 25  # quanti video controllare per ogni run
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code != 200:
            print(f"❌ Errore API Facebook videos: {r.status_code} - {r.text[:300]}")
            return
        data = r.json()
        videos = data.get("data", [])
        print(f"   🎬 Video trovati su Facebook: {len(videos)}")
    except Exception as e:
        print(f"❌ Errore chiamata API Facebook: {e}")
        return

    for video in videos:
        fb_id = str(video.get("id", "")).strip()
        titolo_raw = str(video.get("title", "")).strip()
        descrizione = str(video.get("description", "")).strip()
        created_time = str(video.get("created_time", "")).strip()
        source_url = str(video.get("source", "")).strip()

        if not fb_id:
            continue

        # Controlla doppioni tramite FB_Video_ID
        if fb_id in fb_ids_esistenti:
            print(f"   ⏭️ Video FB ID {fb_id} già presente nello sheet. Salto.")
            continue

        # Genera nome file unico basato sull'ID Facebook
        nome_file = f"fb_video_{fb_id}.mp4"

        # Controlla doppioni anche per nome file (doppia sicurezza)
        if nome_file in nomi_esistenti:
            print(f"   ⏭️ '{nome_file}' già presente nello sheet. Salto.")
            continue

        print(f"\n   🆕 Nuovo video trovato: ID={fb_id} | Creato: {created_time}")

        # Scarica il video da Facebook (se l'URL source è disponibile)
        if not source_url:
            print(f"   ⚠️ URL sorgente non disponibile per video {fb_id}. "
                  "Potrebbe richiedere permessi aggiuntivi (video_url scope). Salto download.")
            # Aggiungiamo comunque allo sheet con flag speciale per download mancante
            video_su_drive = False
        else:
            video_su_drive = False
            video_locale = f"temp_fb_{fb_id}.mp4"
            try:
                print(f"   ⬇️ Download video da Facebook...")
                resp = requests.get(source_url, stream=True, timeout=300)
                if resp.status_code == 200:
                    with open(video_locale, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                    size_mb = os.path.getsize(video_locale) / (1024 * 1024)
                    print(f"   ✅ Video scaricato: {size_mb:.1f} MB")

                    # Carica su Drive
                    drive_id = upload_video_su_drive(drive_service, video_locale, nome_file, folder_id)
                    if drive_id:
                        video_su_drive = True
                else:
                    print(f"   ⚠️ Download fallito: HTTP {resp.status_code}")
            except Exception as e:
                print(f"   ❌ Errore durante download/upload: {e}")
            finally:
                if os.path.exists(video_locale):
                    os.remove(video_locale)
                    print(f"   🗑️ File temporaneo rimosso: {video_locale}")

        # Calcola la data di ripubblicazione (oggi + GIORNI_RIPUBBLICAZIONE)
        data_ripubblicazione = (datetime.now() + timedelta(days=GIORNI_RIPUBBLICAZIONE)).strftime("%Y-%m-%d")

        # Ricava tipologia dal titolo o usa default
        tipologia = "Immobile"
        keywords_tipologia = {
            "villa": "Villa",
            "appartamento": "Appartamento",
            "terreno": "Terreno",
            "locale": "Locale Commerciale",
            "negozio": "Negozio",
            "box": "Box/Garage",
            "garage": "Box/Garage",
        }
        titolo_lower = titolo_raw.lower() + descrizione.lower()
        for kw, tip in keywords_tipologia.items():
            if kw in titolo_lower:
                tipologia = tip
                break

        # Prepara la nuova riga — rispetta l'ordine delle colonne dello sheet
        # Colonne attese: Nome_File_Video, Descrizione, Data, Tipologia, Pubblicato, FB_Video_ID
        # (aggiungere FB_Video_ID allo sheet se non esiste già)
        nuova_riga = [
            nome_file,                                  # Nome_File_Video
            descrizione or titolo_raw,                  # Descrizione
            data_ripubblicazione,                       # Data (quando ripubblicare)
            tipologia,                                  # Tipologia
            "NO" if video_su_drive else "SKIP",         # Pubblicato: NO = da pubblicare, SKIP = nessun video
            fb_id                                       # FB_Video_ID (colonna antiduplicato)
        ]

        sheet.append_row(nuova_riga)
        nomi_esistenti.add(nome_file)
        fb_ids_esistenti.add(fb_id)
        nuovi_aggiunti += 1

        print(f"   ✅ Riga aggiunta allo sheet: '{nome_file}' → Da ripubblicare il {data_ripubblicazione}")
        print(f"      Drive: {'✅ Caricato' if video_su_drive else '❌ Non caricato'}")

        # Piccola pausa per non sovraccaricare le API
        time.sleep(1)

    print(f"\n✅ Sincronizzazione Facebook completata. Nuovi video aggiunti: {nuovi_aggiunti}")


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
            r = requests.post(url, data=payload, files=files, timeout=300)

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
        invia_video = False
        if video_path and os.path.exists(video_path):
            peso_mb = os.path.getsize(video_path) / (1024 * 1024)
            if peso_mb < 49:
                invia_video = True
            else:
                print(f"⚠️ Il video pesa {peso_mb:.1f} MB (limite Telegram 50 MB). Invierò solo testo e link.")

        if invia_video:
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

    # ============================================================
    # STEP NUOVO: Sincronizza video da Facebook verso Sheet+Drive
    # Questo avviene PRIMA della pubblicazione, così i video
    # scoperti oggi vengono aggiunti e saranno pronti tra 1 mese
    # ============================================================
    sincronizza_video_da_facebook(sheet, drive_service)

    # Ricarica i record dopo la sincronizzazione (potrebbero esserci nuove righe)
    records = sheet.get_all_records()

    # 3. Trova colonna "Pubblicato" dinamicamente
    headers = sheet.row_values(1)
    print(f"\n📋 Colonne trovate nel foglio: {headers}")

    try:
        col_pub_idx = headers.index("Pubblicato") + 1
    except ValueError:
        print("❌ Colonna 'Pubblicato' non trovata nel foglio!")
        print(f"   Colonne disponibili: {headers}")
        return

    processati = 0
    saltati = 0
    oggi = datetime.now().strftime("%Y-%m-%d")

    for i, post in enumerate(records, start=2):

        # Salta righe già pubblicate o con SKIP (video non scaricato)
        stato = str(post.get("Pubblicato", "")).strip().upper()
        if stato in ("SI", "SKIP"):
            saltati += 1
            continue

        nome_file   = str(post.get("Nome_File_Video", "")).strip()
        descrizione = str(post.get("Descrizione", "")).strip()
        data_post   = str(post.get("Data", oggi)).strip()
        tipologia   = str(post.get("Tipologia", "Immobile")).strip()

        # Salta righe senza video
        if not nome_file:
            continue

        # Salta se la data di ripubblicazione è nel futuro
        try:
            data_pub = datetime.strptime(data_post, "%Y-%m-%d")
            if data_pub.date() > datetime.now().date():
                print(f"   ⏳ Riga {i} ({nome_file}): programmata per {data_post}. Salto.")
                saltati += 1
                continue
        except ValueError:
            pass  # Se la data non è parsabile, procede comunque

        print(f"\n🆕 Elaborazione riga {i}: {nome_file} ({tipologia} - {data_post})")

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
        wp_link = None

        if not yt_link:
            print("⚠️ Errore YouTube. Procedo con Facebook e Telegram senza link YouTube.")
        else:
            # 7. Pubblica su WordPress solo se YouTube ha funzionato
            wp_link = posta_su_wordpress(titolo_video, descrizione, yt_link)

        # 8. Pubblica su Facebook
        testo_fb = f"{titolo_video}\n\n{descrizione}"
        fb_link = posta_su_facebook(testo_fb, video_locale)

        # 9. Pubblica su Telegram
        desc_troncata = descrizione[:500] + "..." if len(descrizione) > 500 else descrizione
        testo_social = (
            f"🏠 <b>{tipologia} - {data_post}</b>\n\n"
            f"{desc_troncata}\n"
        )
        if yt_link:
            testo_social += f"\n📺 <a href='{yt_link}'>Guarda su YouTube</a>"
        if wp_link:
            testo_social += f"\n🌐 <a href='{wp_link}'>Vedi sul sito</a>"
        if fb_link:
            testo_social += f"\n🟦 <a href='{fb_link}'>Vedi su Facebook</a>"

        posta_su_telegram(testo_social, video_locale)

        # 10. Segna come pubblicato
        sheet.update_cell(i, col_pub_idx, "SI")
        print(f"✅ Riga {i} completata e segnata come SI.")
        processati += 1

        # 11. Pulizia
        if os.path.exists(video_locale):
            os.remove(video_locale)

        # 🛑 STOP dopo 1 video pubblicato
        print("\n🛑 Pubblicazione di UN video completata! Il bot si ferma qui fino a domani.")
        break

    print(f"\n🏁 Bot completato. Processati oggi: {processati} | Saltati: {saltati}")


if __name__ == "__main__":
    main()
