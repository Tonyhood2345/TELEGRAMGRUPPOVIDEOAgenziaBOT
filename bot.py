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
from datetime import datetime, timedelta

# --- CONFIGURAZIONE SEGRETI ---
TELEGRAM_TOKEN      = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID             = os.environ.get("CHAT_ID")
WP_PASSWORD         = os.environ.get("WP_PASSWORD")
GOOGLE_SECRETS      = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
YT2_CLIENT_ID       = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET   = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN   = os.environ.get("YT2_REFRESH_TOKEN")
FB_PAGE_TOKEN       = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID          = os.environ.get("FB_PAGE_ID")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY")   # ← aggiungi su GitHub Secrets

WP_USER     = "Antonio Giancani"
WP_API_URL  = "https://www.immobiliaregiancani.it/wp-json/wp/v2/property"
SHEET_ID    = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"

DRIVE_FOLDER_NAME      = "Video_Da_Ripubblicare"
GIORNI_RIPUBBLICAZIONE = 30

# Ordine ESATTO colonne sheet:
# Tipo | Data | Ora | Tipologia | Descrizione | 👍 Like | 💬 Commenti | 🔁 Condivisioni | Engagement | Anteprima | Link | Nome_File_Video | Pubblicato


# ---------------------------------------------------------------------------
# VALIDAZIONE SECRETS
# ---------------------------------------------------------------------------
def validate_secrets():
    required = {
        "GOOGLE_APPLICATION_CREDENTIALS": GOOGLE_SECRETS,
        "YT2_CLIENT_ID":     YT2_CLIENT_ID,
        "YT2_CLIENT_SECRET": YT2_CLIENT_SECRET,
        "YT2_REFRESH_TOKEN": YT2_REFRESH_TOKEN,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(f"❌ Variabili mancanti: {', '.join(missing)}")
    try:
        json.loads(GOOGLE_SECRETS)
    except json.JSONDecodeError as e:
        raise ValueError(f"❌ GOOGLE_APPLICATION_CREDENTIALS non è JSON valido: {e}")
    print("✅ Tutti i secrets sono presenti e validi.")


# ---------------------------------------------------------------------------
# AUTENTICAZIONE GOOGLE
# ---------------------------------------------------------------------------
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
    gc      = gspread.authorize(creds_gspread)
    drive   = build('drive', 'v3', credentials=creds_gspread)
    youtube = build('youtube', 'v3', credentials=creds_yt)
    return gc, drive, youtube


# ---------------------------------------------------------------------------
# UTILS DRIVE
# ---------------------------------------------------------------------------
def cerca_id_drive_per_nome(drive_service, nome_file):
    try:
        nome_escaped = nome_file.replace("'", "\\'")
        result = drive_service.files().list(
            q=f"name = '{nome_escaped}' and trashed = false",
            spaces='drive', fields='files(id, name)', pageSize=1
        ).execute()
        files = result.get('files', [])
        if not files:
            print(f"⚠️ '{nome_file}' non trovato su Drive.")
            return None
        fid = files[0]['id']
        print(f"✅ Drive trovato: '{nome_file}' → {fid}")
        return fid
    except Exception as e:
        print(f"❌ Errore ricerca Drive: {e}")
        return None


def get_or_create_drive_folder(drive_service, folder_name):
    try:
        result = drive_service.files().list(
            q=f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            spaces='drive', fields='files(id, name)', pageSize=1
        ).execute()
        files = result.get('files', [])
        if files:
            fid = files[0]['id']
            print(f"📁 Cartella Drive: '{folder_name}' → {fid}")
            return fid
        folder = drive_service.files().create(
            body={'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'},
            fields='id'
        ).execute()
        fid = folder.get('id')
        print(f"📁 Cartella Drive creata: '{folder_name}' → {fid}")
        return fid
    except Exception as e:
        print(f"❌ Errore cartella Drive: {e}")
        return None


def upload_video_su_drive(drive_service, local_path, nome_file, folder_id=None):
    try:
        metadata = {'name': nome_file}
        if folder_id:
            metadata['parents'] = [folder_id]
        media = MediaFileUpload(local_path, mimetype='video/mp4', resumable=True)
        file = drive_service.files().create(body=metadata, media_body=media, fields='id').execute()
        fid = file.get('id')
        print(f"✅ Caricato su Drive: '{nome_file}' → {fid}")
        return fid
    except Exception as e:
        print(f"❌ Errore upload Drive: {e}")
        return None


# ---------------------------------------------------------------------------
# RISCRITTURA DESCRIZIONE CON CLAUDE AI
# ---------------------------------------------------------------------------
def riscrivi_descrizione_con_claude(descrizione_originale, tipologia="Immobile"):
    """
    Usa Claude Haiku (modello più economico) per riscrivere la descrizione
    in modo più coinvolgente per i social. Se manca la chiave o va in errore,
    restituisce la descrizione originale senza bloccare il bot.
    """
    if not ANTHROPIC_API_KEY:
        print("⚠️ ANTHROPIC_API_KEY mancante. Uso descrizione originale.")
        return descrizione_originale

    try:
        print("🤖 Riscrittura descrizione con Claude AI...")
        prompt = (
            f"Sei un esperto di marketing immobiliare italiano.\n"
            f"Riscrivi questa descrizione di un {tipologia} per i social media italiani.\n\n"
            f"Regole:\n"
            f"- Mantieni indirizzo, caratteristiche e contatti originali\n"
            f"- Aggiungi un hook iniziale accattivante\n"
            f"- Usa emoji pertinenti ma senza esagerare\n"
            f"- Chiudi con una call-to-action chiara\n"
            f"- Massimo 300 parole\n"
            f"- Scrivi SOLO la descrizione, senza commenti aggiuntivi\n\n"
            f"Descrizione originale:\n{descrizione_originale}"
        )
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        if response.status_code == 200:
            testo = response.json()["content"][0]["text"].strip()
            print("✅ Descrizione riscritta con successo.")
            return testo
        else:
            print(f"⚠️ Claude API: {response.status_code}. Uso descrizione originale.")
            return descrizione_originale
    except Exception as e:
        print(f"❌ Errore Claude AI: {e}. Uso descrizione originale.")
        return descrizione_originale


# ---------------------------------------------------------------------------
# SINCRONIZZA VIDEO DA FACEBOOK → SHEET + DRIVE
# ---------------------------------------------------------------------------
def sincronizza_video_da_facebook(sheet, drive_service):
    """
    Controlla la pagina Facebook cercando video/reel nuovi.

    SE non ci sono video nuovi → stampa un messaggio e continua senza fare nulla.
    SE trova video nuovi → per ognuno:
        1. Scarica il video e lo carica su Google Drive
        2. Riscrive la descrizione con Claude AI
        3. Aggiunge UNA riga allo sheet con TUTTE le colonne nell'ordine corretto:
           Tipo | Data | Ora | Tipologia | Descrizione | 👍 Like | 💬 Commenti |
           🔁 Condivisioni | Engagement | Anteprima | Link | Nome_File_Video | Pubblicato
        4. Data = data pubblicazione Facebook + 30 giorni (quando il bot lo ripubblicherà)
        5. Pubblicato = NO  (pronto per essere pubblicato tra 30 giorni)
    """
    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("⚠️ Credenziali Facebook mancanti. Salto sincronizzazione.")
        return

    print("\n🔍 Sincronizzazione video da Facebook...")

    # Carica link già presenti per evitare doppioni
    records = sheet.get_all_records()
    links_esistenti = set(str(r.get("Link", "")).strip() for r in records if str(r.get("Link", "")).strip())
    nomi_esistenti  = set(str(r.get("Nome_File_Video", "")).strip() for r in records if str(r.get("Nome_File_Video", "")).strip())
    print(f"   📋 Video già nello sheet: {len(nomi_esistenti)}")

    folder_id    = get_or_create_drive_folder(drive_service, DRIVE_FOLDER_NAME)
    nuovi_aggiunti = 0

    # Recupera video dalla pagina Facebook
    try:
        r = requests.get(
            f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/videos",
            params={
                "access_token": FB_PAGE_TOKEN,
                "fields": "id,title,description,created_time,source,permalink_url,thumbnails,likes.summary(true),comments.summary(true),shares",
                "limit": 25
            },
            timeout=30
        )
        if r.status_code != 200:
            print(f"❌ Errore API Facebook: {r.status_code} - {r.text[:300]}")
            return
        videos = r.json().get("data", [])
        print(f"   🎬 Video trovati sulla pagina: {len(videos)}")
    except Exception as e:
        print(f"❌ Errore chiamata Facebook: {e}")
        return

    if not videos:
        print("   ℹ️ Nessun video sulla pagina Facebook. Nulla da fare.")
        return

    for video in videos:
        fb_id       = str(video.get("id", "")).strip()
        titolo_raw  = str(video.get("title", "")).strip()
        descrizione = str(video.get("description", "")).strip() or titolo_raw
        created_time = str(video.get("created_time", "")).strip()
        source_url  = str(video.get("source", "")).strip()
        permalink   = str(video.get("permalink_url", "")).strip()

        # Statistiche
        likes        = video.get("likes", {}).get("summary", {}).get("total_count", 0)
        commenti     = video.get("comments", {}).get("summary", {}).get("total_count", 0)
        condivisioni = video.get("shares", {}).get("count", 0) if video.get("shares") else 0
        engagement   = likes + commenti + condivisioni

        # Thumbnail
        thumbnails = video.get("thumbnails", {}).get("data", [])
        anteprima  = thumbnails[0].get("uri", "") if thumbnails else ""

        link_video = permalink or f"https://www.facebook.com/{FB_PAGE_ID}/videos/{fb_id}"

        if not fb_id:
            continue

        # Controllo doppioni
        if link_video in links_esistenti or f"fb_video_{fb_id}.mp4" in nomi_esistenti:
            print(f"   ⏭️ Video {fb_id} già presente. Salto.")
            continue

        nome_file = f"fb_video_{fb_id}.mp4"
        print(f"\n   🆕 Nuovo video: {fb_id} | {created_time}")

        # Parsing data/ora
        try:
            dt_obj         = datetime.strptime(created_time, "%Y-%m-%dT%H:%M:%S+0000")
            data_originale = dt_obj.strftime("%Y-%m-%d")
            ora_originale  = dt_obj.strftime("%H:%M")
        except Exception:
            data_originale = datetime.now().strftime("%Y-%m-%d")
            ora_originale  = datetime.now().strftime("%H:%M")

        # Data ripubblicazione = originale + 30 giorni
        try:
            data_ripub = (datetime.strptime(data_originale, "%Y-%m-%d") + timedelta(days=GIORNI_RIPUBBLICAZIONE)).strftime("%Y-%m-%d")
        except Exception:
            data_ripub = (datetime.now() + timedelta(days=GIORNI_RIPUBBLICAZIONE)).strftime("%Y-%m-%d")

        # Rileva tipologia
        tipologia = "Immobile"
        for kw, tip in {
            "villa": "Villa", "appartamento": "Appartamento", "terreno": "Terreno",
            "locale": "Locale Commerciale", "negozio": "Negozio",
            "box": "Box/Garage", "garage": "Box/Garage"
        }.items():
            if kw in (descrizione + titolo_raw).lower():
                tipologia = tip
                break

        # Riscrive descrizione con Claude AI
        descrizione_ai = riscrivi_descrizione_con_claude(descrizione, tipologia)

        # Scarica video e carica su Drive
        video_su_drive = False
        if source_url:
            video_locale = f"temp_sync_{fb_id}.mp4"
            try:
                print(f"   ⬇️ Download video...")
                resp = requests.get(source_url, stream=True, timeout=300)
                if resp.status_code == 200:
                    with open(video_locale, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                    size_mb = os.path.getsize(video_locale) / (1024 * 1024)
                    print(f"   ✅ Scaricato: {size_mb:.1f} MB")
                    if upload_video_su_drive(drive_service, video_locale, nome_file, folder_id):
                        video_su_drive = True
                else:
                    print(f"   ⚠️ Download fallito: HTTP {resp.status_code}")
            except Exception as e:
                print(f"   ❌ Errore download/upload: {e}")
            finally:
                if os.path.exists(video_locale):
                    os.remove(video_locale)
        else:
            print("   ⚠️ URL sorgente non disponibile (serve permesso video_url sul token FB).")

        # Riga nello sheet — ordine ESATTO delle colonne:
        # Tipo|Data|Ora|Tipologia|Descrizione|👍Like|💬Commenti|🔁Condivisioni|Engagement|Anteprima|Link|Nome_File_Video|Pubblicato
        nuova_riga = [
            "Video",                              # Tipo
            data_ripub,                           # Data (data ripubblicazione = originale +30gg)
            ora_originale,                        # Ora
            tipologia,                            # Tipologia
            descrizione_ai,                       # Descrizione (riscritta con Claude AI)
            likes,                                # 👍 Like
            commenti,                             # 💬 Commenti
            condivisioni,                         # 🔁 Condivisioni
            engagement,                           # Engagement
            anteprima,                            # Anteprima (URL thumbnail)
            link_video,                           # Link (permalink Facebook originale)
            nome_file,                            # Nome_File_Video
            "NO" if video_su_drive else "SKIP",   # Pubblicato: NO=pronto, SKIP=video mancante
        ]

        sheet.append_row(nuova_riga)
        links_esistenti.add(link_video)
        nomi_esistenti.add(nome_file)
        nuovi_aggiunti += 1

        print(f"   ✅ Sheet aggiornato: '{nome_file}' → ripubblica il {data_ripub} | Drive: {'✅' if video_su_drive else '❌'}")
        time.sleep(1)  # pausa cortesia API

    if nuovi_aggiunti == 0:
        print("   ℹ️ Nessun video nuovo trovato. Sheet già aggiornato, il bot prosegue normalmente.")
    else:
        print(f"\n✅ Sincronizzazione completata. Nuovi video aggiunti: {nuovi_aggiunti}")


# ---------------------------------------------------------------------------
# PUBBLICAZIONE YOUTUBE
# ---------------------------------------------------------------------------
def posta_su_youtube(youtube, file_path, titolo, descrizione):
    try:
        print(f"🎬 Caricamento su YouTube: {titolo}")
        body = {
            'snippet': {
                'title': titolo,
                'description': descrizione,
                'tags': ['immobiliare', 'casa', 'vendita', 'Favara', 'Sicilia']
            },
            'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
        }
        response = youtube.videos().insert(
            part='snippet,status', body=body,
            media_body=MediaFileUpload(file_path, chunksize=-1, resumable=True)
        ).execute()
        link = f"https://www.youtube.com/watch?v={response['id']}"
        print(f"✅ YouTube OK: {link}")
        return link
    except Exception as e:
        print(f"❌ Errore YouTube: {e}")
        return None


# ---------------------------------------------------------------------------
# PUBBLICAZIONE WORDPRESS
# ---------------------------------------------------------------------------
def posta_su_wordpress(titolo, testo, yt_url):
    if not WP_PASSWORD:
        print("⚠️ WP_PASSWORD mancante. Salto WordPress.")
        return None
    try:
        video_id = yt_url.split("v=")[-1] if "v=" in yt_url else yt_url.split("/")[-1]
        video_html = (
            f'\n\n<iframe width="560" height="315" '
            f'src="https://www.youtube.com/embed/{video_id}" '
            f'frameborder="0" allowfullscreen></iframe>\n\n'
        )
        auth_base64 = base64.b64encode(f"{WP_USER}:{WP_PASSWORD}".encode()).decode()
        r = requests.post(
            WP_API_URL,
            headers={'Authorization': f'Basic {auth_base64}', 'Content-Type': 'application/json'},
            json={'title': titolo, 'content': testo + video_html, 'status': 'publish'},
            timeout=30
        )
        if r.status_code == 201:
            link = r.json().get('link')
            print(f"✅ WordPress OK: {link}")
            return link
        print(f"⚠️ WordPress: {r.status_code} - {r.text[:200]}")
        return None
    except Exception as e:
        print(f"❌ Errore WordPress: {e}")
        return None


# ---------------------------------------------------------------------------
# PUBBLICAZIONE FACEBOOK
# ---------------------------------------------------------------------------
def posta_su_facebook(testo, video_path):
    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("⚠️ Credenziali Facebook mancanti. Salto.")
        return None
    try:
        print("🟦 Caricamento su Facebook...")
        with open(video_path, 'rb') as f:
            r = requests.post(
                f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/videos",
                data={'access_token': FB_PAGE_TOKEN, 'description': testo},
                files={'source': f},
                timeout=300
            )
        if r.status_code == 200:
            vid_id = r.json().get('id')
            link = f"https://www.facebook.com/{FB_PAGE_ID}/videos/{vid_id}"
            print(f"✅ Facebook OK: {link}")
            return link
        print(f"⚠️ Facebook: {r.status_code} - {r.text}")
        return None
    except Exception as e:
        print(f"❌ Errore Facebook: {e}")
        return None


# ---------------------------------------------------------------------------
# PUBBLICAZIONE TELEGRAM
# ---------------------------------------------------------------------------
def posta_su_telegram(testo, video_path=None):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Credenziali Telegram mancanti. Salto.")
        return
    try:
        peso_mb = os.path.getsize(video_path) / (1024 * 1024) if video_path and os.path.exists(video_path) else 999
        if peso_mb < 49:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
            with open(video_path, "rb") as f:
                r = requests.post(
                    url,
                    data={"chat_id": CHAT_ID, "caption": testo[:1024], "parse_mode": "HTML"},
                    files={"video": f}, timeout=120
                )
        else:
            if video_path:
                print(f"⚠️ Video {peso_mb:.1f} MB > 49 MB. Invio solo testo.")
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": testo, "parse_mode": "HTML"},
                timeout=30
            )
        print("✅ Telegram OK" if r.status_code == 200 else f"⚠️ Telegram: {r.status_code}")
    except Exception as e:
        print(f"❌ Errore Telegram: {e}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    validate_secrets()
    gc, drive_service, youtube_service = get_google_services()
    sheet = gc.open_by_key(SHEET_ID).sheet1

    # STEP 1 — Sincronizza nuovi video da Facebook verso Sheet + Drive
    # Se non ci sono video nuovi → nessuna azione, il bot prosegue
    sincronizza_video_da_facebook(sheet, drive_service)

    # STEP 2 — Ricarica records (potrebbero esserci nuove righe aggiunte sopra)
    records = sheet.get_all_records()
    headers = sheet.row_values(1)
    print(f"\n📋 Colonne sheet: {headers}")

    try:
        col_pub_idx = headers.index("Pubblicato") + 1
    except ValueError:
        print(f"❌ Colonna 'Pubblicato' non trovata! Disponibili: {headers}")
        return

    processati = 0
    saltati    = 0
    oggi       = datetime.now().date()

    for i, post in enumerate(records, start=2):
        stato = str(post.get("Pubblicato", "")).strip().upper()

        # Salta già pubblicati o senza video (SKIP)
        if stato in ("SI", "SKIP"):
            saltati += 1
            continue

        nome_file   = str(post.get("Nome_File_Video", "")).strip()
        descrizione = str(post.get("Descrizione", "")).strip()
        data_post   = str(post.get("Data", str(oggi))).strip()
        tipologia   = str(post.get("Tipologia", "Immobile")).strip()

        if not nome_file:
            continue

        # Salta se la data di ripubblicazione non è ancora arrivata
        try:
            if datetime.strptime(data_post, "%Y-%m-%d").date() > oggi:
                print(f"   ⏳ Riga {i} ({nome_file}): programmata per {data_post}. Salto.")
                saltati += 1
                continue
        except ValueError:
            pass

        print(f"\n🆕 Elaborazione riga {i}: {nome_file} ({tipologia} - {data_post})")
        titolo_video = f"Immobiliare Giancani - {tipologia} - {data_post}"

        # Cerca su Drive
        drive_file_id = cerca_id_drive_per_nome(drive_service, nome_file)
        if not drive_file_id:
            print(f"⏭️ '{nome_file}' non trovato su Drive. Salto riga {i}.")
            continue

        # Scarica da Drive
        video_locale = f"temp_video_{i}.mp4"
        try:
            request = drive_service.files().get_media(fileId=drive_file_id)
            with open(video_locale, "wb") as f:
                f.write(request.execute())
            print(f"✅ Video scaricato: {video_locale}")
        except Exception as e:
            print(f"❌ Download Drive fallito (riga {i}): {e}")
            if os.path.exists(video_locale):
                os.remove(video_locale)
            continue

        # Pubblica YouTube → WordPress → Facebook → Telegram
        yt_link = posta_su_youtube(youtube_service, video_locale, titolo_video, descrizione)
        wp_link = posta_su_wordpress(titolo_video, descrizione, yt_link) if yt_link else None
        if not yt_link:
            print("⚠️ YouTube fallito. Procedo con Facebook e Telegram senza link YouTube.")

        fb_link = posta_su_facebook(f"{titolo_video}\n\n{descrizione}", video_locale)

        desc_troncata = descrizione[:500] + "..." if len(descrizione) > 500 else descrizione
        testo_tg = f"🏠 <b>{tipologia} - {data_post}</b>\n\n{desc_troncata}\n"
        if yt_link: testo_tg += f"\n📺 <a href='{yt_link}'>Guarda su YouTube</a>"
        if wp_link: testo_tg += f"\n🌐 <a href='{wp_link}'>Vedi sul sito</a>"
        if fb_link: testo_tg += f"\n🟦 <a href='{fb_link}'>Vedi su Facebook</a>"
        posta_su_telegram(testo_tg, video_locale)

        # Segna come pubblicato
        sheet.update_cell(i, col_pub_idx, "SI")
        print(f"✅ Riga {i} → Pubblicato = SI")
        processati += 1

        if os.path.exists(video_locale):
            os.remove(video_locale)

        print("\n🛑 Un video pubblicato. Il bot si ferma qui fino a domani.")
        break

    print(f"\n🏁 Fine. Pubblicati oggi: {processati} | Saltati: {saltati}")


if __name__ == "__main__":
    main()
