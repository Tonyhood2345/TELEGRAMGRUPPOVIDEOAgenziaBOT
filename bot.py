#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot Pubblicazione Immobiliare — Pipeline Multi-Piattaforma
Doppia modalità:
  1. RICICLO (cron giornaliero) — ripubblica vecchi post dal foglio Google
  2. NUOVO IMMOBILE (workflow_dispatch) — pipeline completa con skip duplicati

✨ Antonio Giancani
"""

import os
import json
import time
import requests
import gspread
import subprocess
import re
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as OauthCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from datetime import datetime

# ═══════════════════════════════════════════
# CONFIGURAZIONE
# ═══════════════════════════════════════════
GOOGLE_SECRETS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
YT2_CLIENT_ID = os.environ.get("YT2_CLIENT_ID")
YT2_CLIENT_SECRET = os.environ.get("YT2_CLIENT_SECRET")
YT2_REFRESH_TOKEN = os.environ.get("YT2_REFRESH_TOKEN")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID", "")
BOSS_PHONE = os.environ.get("BOSS_PHONE", "")

# Integrazioni aggiuntive: Sito (WordPress) e Google Business Profile (GMB)
WP_URL = os.environ.get("WP_URL", "")
WP_USER = os.environ.get("WP_USER", "")
WP_PASSWORD = os.environ.get("WP_PASSWORD", "")
GMB_ACCOUNT_ID = os.environ.get("GMB_ACCOUNT_ID", "")
GMB_LOCATION_ID = os.environ.get("GMB_LOCATION_ID", "")

# Input da workflow_dispatch (modalità NUOVO IMMOBILE)
INPUT_JOB_ID = os.environ.get("INPUT_JOB_ID", "")
INPUT_VIDEO_URL = os.environ.get("INPUT_VIDEO_URL", "")
INPUT_SEO_TITLE = os.environ.get("INPUT_SEO_TITLE", "")
INPUT_SEO_DESCRIPTION = os.environ.get("INPUT_SEO_DESCRIPTION", "")
INPUT_SEO_HASHTAGS = os.environ.get("INPUT_SEO_HASHTAGS", "")
INPUT_INDIRIZZO = os.environ.get("INPUT_INDIRIZZO", "")
INPUT_CALLBACK_URL = os.environ.get("INPUT_CALLBACK_URL", "")
INPUT_EXISTING_LINKS = os.environ.get("INPUT_EXISTING_LINKS", "{}")

SHEET_ID = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"
BRANDING = "\n\n✨ Antonio Giancani"

# Variabile globale per trasferire l'URL CDN diretto del video da Facebook a Instagram
LATEST_FB_VIDEO_DIRECT_URL = ""


# ═══════════════════════════════════════════
# UTILITÀ COMUNI
# ═══════════════════════════════════════════

def get_google_services():
    """Inizializza Google Sheets + YouTube con le credenziali."""
    creds_dict = json.loads(GOOGLE_SECRETS)
    creds_g = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"]
    )
    creds_yt = OauthCredentials(
        token=None,
        refresh_token=YT2_REFRESH_TOKEN,
        client_id=YT2_CLIENT_ID,
        client_secret=YT2_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token"
    )
    return gspread.authorize(creds_g), build('youtube', 'v3', credentials=creds_yt)


def download_video(url, sorgente="Auto"):
    """Scarica video da qualsiasi piattaforma social con yt-dlp."""
    output_filename = "video_scaricato.mp4"
    print(f"📥 Scaricamento video da {sorgente}: {url}")
    try:
        comando = [
            'yt-dlp',
            '--socket-timeout', '60',
            '-f', 'b[ext=mp4]/best[ext=mp4]/best',
            url,
            '-o', output_filename,
            '--force-overwrites',
            '--no-playlist'
        ]
        subprocess.run(comando, check=True, timeout=120)
        if os.path.exists(output_filename):
            size_mb = os.path.getsize(output_filename) / (1024 * 1024)
            print(f"✅ Video scaricato: {output_filename} ({size_mb:.1f} MB)")
            return output_filename
        return None
    except subprocess.TimeoutExpired:
        print(f"❌ Timeout download da {sorgente}")
        return None
    except subprocess.CalledProcessError as e:
        print(f"❌ Errore yt-dlp su {sorgente}: {e}")
        return None
    except Exception as e:
        print(f"❌ Errore generico download da {sorgente}: {e}")
        return None


def edit_video(input_file, durata=30):
    """Taglia il video a max 30 secondi e aggiunge watermark 'Antonio Giancani'."""
    output = "video_editato.mp4"
    print(f"🎬 Editing video: trim {durata}s + watermark Antonio Giancani")
    try:
        comando = [
            'ffmpeg', '-y',
            '-i', input_file,
            '-t', str(durata),
            '-vf', (
                "drawtext=text='Antonio Giancani'"
                ":fontsize=24"
                ":fontcolor=white"
                ":x=w-tw-20"
                ":y=h-th-20"
                ":shadowx=2"
                ":shadowy=2"
                ":shadowcolor=black@0.7"
            ),
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-c:a', 'aac',
            '-movflags', '+faststart',
            output
        ]
        subprocess.run(comando, check=True, timeout=120)
        if os.path.exists(output):
            size_mb = os.path.getsize(output) / (1024 * 1024)
            print(f"✅ Video editato: {output} ({size_mb:.1f} MB)")
            return output
        return input_file
    except Exception as e:
        print(f"⚠️ Editing fallito, uso video originale: {e}")
        return input_file


# ═══════════════════════════════════════════
# FUNZIONI INTEGRATIVE FACEBOOK / INSTAGRAM
# ═══════════════════════════════════════════

def extract_facebook_video_id(url):
    """Estrae l'ID numerico del video da una URL di Facebook (share, watch, ecc.)."""
    if not url:
        return ""
    # Esempi: share/v/1ErTi5nk3o/ o watch/?v=8392109843729
    match = re.search(r'(?:v|videos|watch|share/v|live/\?v)=?/?([a-zA-Z0-9]+)', url)
    if match:
        token = match.group(1)
        if token.isdigit():
            return token
        # Fallback se è un token alfanumerico di share: cerchiamo se ci sono numeri lunghi
        numbers = re.findall(r'\d+', url)
        if numbers:
            longest = max(numbers, key=len)
            if len(longest) >= 8:
                return longest
        return token
    return ""


def get_facebook_video_direct_url(video_id):
    """Interroga la Graph API di Facebook per ottenere il link CDN directo al file video MP4."""
    if not video_id or not FB_PAGE_TOKEN:
        return ""
    try:
        url = f"https://graph.facebook.com/v21.0/{video_id}"
        params = {
            'fields': 'source',
            'access_token': FB_PAGE_TOKEN
        }
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 200:
            direct_url = r.json().get('source', '')
            if direct_url:
                print(f"🎬 URL video diretto Facebook trovato: {direct_url[:50]}...")
                return direct_url
        else:
            print(f"⚠️ Errore Graph API recupero sorgente video {video_id}: {r.text[:150]}")
    except Exception as e:
        print(f"⚠️ Errore recupero direct link FB: {e}")
    return ""


# ═══════════════════════════════════════════
# UPLOAD PER PIATTAFORMA
# ═══════════════════════════════════════════

def upload_facebook(video_file, descrizione):
    """Upload video su Facebook Page."""
    print("📘 Upload Facebook...")
    testo = descrizione + BRANDING
    try:
        fb_url = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/videos"
        with open(video_file, 'rb') as f:
            r = requests.post(
                fb_url,
                data={'access_token': FB_PAGE_TOKEN, 'description': testo},
                files={'source': f},
                timeout=300
            )
        if r.status_code == 200:
            video_id = r.json().get('id', '')
            link = f"https://www.facebook.com/{FB_PAGE_ID}/videos/{video_id}"
            print(f"✅ Facebook pubblicato: {link}")
            
            # Cerca e memorizza immediatamente la URL del file MP4 diretto per Instagram Reels
            global LATEST_FB_VIDEO_DIRECT_URL
            LATEST_FB_VIDEO_DIRECT_URL = get_facebook_video_direct_url(video_id)
            
            return link
        else:
            print(f"❌ Errore Facebook ({r.status_code}): {r.text[:200]}")
            return ""
    except Exception as e:
        print(f"❌ Errore Facebook: {e}")
        return ""


def upload_youtube(youtube, video_file, titolo, descrizione):
    """Upload video su YouTube come Short."""
    print("📺 Upload YouTube Short...")
    testo_desc = descrizione + BRANDING
    titolo_yt = titolo[:95] + " #Shorts" if len(titolo) <= 95 else titolo[:92] + "... #Shorts"
    try:
        body = {
            'snippet': {
                'title': titolo_yt,
                'description': testo_desc,
                'categoryId': '22'
            },
            'status': {
                'privacyStatus': 'public',
                'selfDeclaredMadeForKids': False
            }
        }
        res = youtube.videos().insert(
            part='snippet,status',
            body=body,
            media_body=MediaFileUpload(video_file, resumable=True)
        ).execute()
        link = f"https://www.youtube.com/shorts/{res['id']}"
        print(f"✅ YouTube pubblicato: {link}")
        return link
    except Exception as e:
        print(f"❌ Errore YouTube: {e}")
        return ""


def upload_instagram_reel(video_file, caption, fb_video_url=""):
    """Upload Instagram Reel via IG Content Publishing API."""
    print("📸 Upload Instagram Reel...")
    if not IG_USER_ID or not FB_PAGE_TOKEN:
        print("⚠️ Instagram: credenziali mancanti (IG_USER_ID o FB_PAGE_TOKEN)")
        return ""

    testo = caption + BRANDING

    # Instagram richiede un URL pubblico del video.
    video_url_for_ig = ""
    if fb_video_url:
        video_url_for_ig = fb_video_url
    else:
        print("⚠️ Instagram: serve un URL pubblico del video. Uso fallback upload diretto...")
        if INPUT_VIDEO_URL and INPUT_VIDEO_URL.startswith("http"):
            video_url_for_ig = INPUT_VIDEO_URL
        else:
            print("❌ Instagram: nessun URL pubblico disponibile, skip")
            return ""

    try:
        # Step 1: Crea container
        create_url = f"https://graph.facebook.com/v21.0/{IG_USER_ID}/media"
        create_data = {
            'media_type': 'REELS',
            'video_url': video_url_for_ig,
            'caption': testo[:2200],
            'access_token': FB_PAGE_TOKEN
        }
        r1 = requests.post(create_url, data=create_data, timeout=60)
        if r1.status_code != 200:
            print(f"❌ IG container error ({r1.status_code}): {r1.text[:200]}")
            return ""

        container_id = r1.json().get('id')
        print(f"📦 IG Container creato: {container_id}")

        # Step 2: Poll
        status_url = f"https://graph.facebook.com/v21.0/{container_id}"
        for attempt in range(60):
            time.sleep(5)
            r_status = requests.get(
                status_url,
                params={'fields': 'status_code', 'access_token': FB_PAGE_TOKEN},
                timeout=30
            )
            if r_status.status_code == 200:
                status = r_status.json().get('status_code', '')
                if status == 'FINISHED':
                    print(f"✅ IG Container pronto (tentativo {attempt + 1})")
                    break
                elif status == 'ERROR':
                    print(f"❌ IG Container in errore")
                    return ""
                else:
                    if attempt % 6 == 0:
                        print(f"⏳ IG Container status: {status} (tentativo {attempt + 1})")
        else:
            print("❌ IG Container timeout dopo 5 minuti")
            return ""

        # Step 3: Pubblica
        publish_url = f"https://graph.facebook.com/v21.0/{IG_USER_ID}/media_publish"
        r3 = requests.post(
            publish_url,
            data={'creation_id': container_id, 'access_token': FB_PAGE_TOKEN},
            timeout=60
        )
        if r3.status_code == 200:
            media_id = r3.json().get('id', '')
            link = f"https://www.instagram.com/reel/{media_id}/"
            print(f"✅ Instagram Reel pubblicato: {link}")
            return link
        else:
            print(f"❌ IG publish error ({r3.status_code}): {r3.text[:200]}")
            return ""

    except Exception as e:
        print(f"❌ Errore Instagram: {e}")
        return ""


def send_telegram(video_file, caption, channel=True):
    """Invia video su Telegram (canale o chat personale) con gestione errori di parsing HTML."""
    target = TELEGRAM_CHANNEL_ID if (channel and TELEGRAM_CHANNEL_ID) else CHAT_ID
    label = "Canale Telegram" if (channel and TELEGRAM_CHANNEL_ID) else "Telegram personale"
    print(f"✈️ Invio {label} (target: {target})...")

    if not TELEGRAM_TOKEN or not target:
        print(f"⚠️ {label}: credenziali o target mancanti, skip")
        return ""

    testo = caption[:1024] + BRANDING if len(caption) < 1000 else caption[:990] + BRANDING
    try:
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
        
        # Tentativo 1: Invio con formattazione HTML
        print(f"✈️ {label}: provo con parse_mode='HTML'...")
        with open(video_file, "rb") as f:
            r = requests.post(
                tg_url,
                data={"chat_id": target, "caption": testo, "parse_mode": "HTML"},
                files={"video": f},
                timeout=120
            )
        
        if r.status_code == 200:
            print(f"✅ {label}: inviato con successo!")
            return "ok"
        else:
            # Se fallisce per errore di parsing HTML
            print(f"⚠️ {label} primo tentativo fallito ({r.status_code}): {r.text[:150]}. Riprovo senza parse_mode...")
            with open(video_file, "rb") as f:
                r2 = requests.post(
                    tg_url,
                    data={"chat_id": target, "caption": testo},
                    files={"video": f},
                    timeout=120
                )
            if r2.status_code == 200:
                print(f"✅ {label}: inviato con successo (testo semplice, secondo tentativo)!")
                return "ok"
            else:
                print(f"❌ {label} definitivo fallito ({r2.status_code}): {r2.text[:150]}")
                return ""
    except Exception as e:
        print(f"❌ Errore invio {label}: {e}")
        return ""


# ═══════════════════════════════════════════
# INTEGRAZIONI AGGIUNTIVE: GOOGLE BUSINESS & SITO (WP)
# ═══════════════════════════════════════════

def get_google_access_token():
    """Genera un access token di Google temporaneo usando il refresh token di YouTube."""
    if not YT2_REFRESH_TOKEN or not YT2_CLIENT_ID or not YT2_CLIENT_SECRET:
        return ""
    try:
        url = "https://oauth2.googleapis.com/token"
        payload = {
            'client_id': YT2_CLIENT_ID,
            'client_secret': YT2_CLIENT_SECRET,
            'refresh_token': YT2_REFRESH_TOKEN,
            'grant_type': 'refresh_token'
        }
        r = requests.post(url, data=payload, timeout=20)
        if r.status_code == 200:
            return r.json().get('access_token', '')
    except Exception as e:
        print(f"⚠️ Errore recupero access token Google: {e}")
    return ""


def upload_google_business(summary, action_url=None):
    """Pubblica un post con novità ed eventuale link su Google Business Profile."""
    print("🏢 Pubblicazione su Google Business Profile...")
    if not GMB_ACCOUNT_ID or not GMB_LOCATION_ID:
        print("⚠️ GMB: credenziali GMB_ACCOUNT_ID o GMB_LOCATION_ID mancanti, skip")
        return "skip"

    access_token = get_google_access_token()
    if not access_token:
        print("⚠️ GMB: impossibile generare l'access token Google, skip")
        return ""

    url = f"https://mybusiness.googleapis.com/v4/accounts/{GMB_ACCOUNT_ID}/locations/{GMB_LOCATION_ID}/localPosts"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    testo_post = (summary + BRANDING)[:1500]

    payload = {
        "languageCode": "it",
        "summary": testo_post,
        "topicType": "STANDARD"
    }

    if action_url:
        payload["callToAction"] = {
            "actionType": "LEARN_MORE",
            "url": action_url
        }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        if r.status_code in (200, 201):
            post_name = r.json().get("name", "")
            print(f"✅ Google Business pubblicato con successo: {post_name}")
            return "ok"
        else:
            print(f"❌ GMB errore ({r.status_code}): {r.text[:200]}")
            return ""
    except Exception as e:
        print(f"❌ Errore GMB: {e}")
        return ""


def upload_wordpress(title, description, video_url=None):
    """Pubblica l'annuncio sul sito internet WordPress tramite REST API."""
    print("🌐 Pubblicazione sul sito WordPress...")
    if not WP_URL or not WP_USER or not WP_PASSWORD:
        print("⚠️ WordPress: credenziali o URL mancanti (WP_URL, WP_USER, WP_PASSWORD), skip")
        return "skip"

    base_url = WP_URL.strip()
    if not base_url.endswith("/"):
        base_url += "/"
    endpoint = f"{base_url}wp-json/wp/v2/posts"

    content_html = f"<p>{description.replace(chr(10), '<br>')}</p>"
    if video_url:
        content_html += f"<br><br><div class='wp-block-embed is-type-video'><a href='{video_url}'>Guarda il video dell'immobile</a></div>"
    content_html += f"<p><strong>✨ Antonio Giancani</strong></p>"

    payload = {
        "title": title,
        "content": content_html,
        "status": "publish"
    }

    try:
        from requests.auth import HTTPBasicAuth
        r = requests.post(
            endpoint,
            auth=HTTPBasicAuth(WP_USER, WP_PASSWORD),
            json=payload,
            timeout=30
        )
        if r.status_code in (200, 201):
            post_link = r.json().get("link", "")
            print(f"✅ WordPress pubblicato con successo: {post_link}")
            return post_link
        else:
            print(f"❌ WordPress errore ({r.status_code}): {r.text[:200]}")
            return ""
    except Exception as e:
        print(f"❌ Errore WordPress: {e}")
        return ""


def send_whatsapp_report(risultati, indirizzo):
    """Invia report strutturato al Boss via WhatsApp Business API."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID or not BOSS_PHONE:
        print("⚠️ WhatsApp: credenziali mancanti, skip report")
        return

    print("🟢 Invio report WhatsApp al Boss...")

    def badge(key, label, emoji):
        val = risultati.get(key, "")
        if val == "skip":
            return f"{emoji} {label}: ⏭️ Già presente"
        elif val and val != "":
            link_part = f" → {val}" if val != "ok" else ""
            return f"{emoji} {label}: ✅ Pubblicato{link_part}"
        else:
            return f"{emoji} {label}: ❌ Errore"

    lines = [
        "📊 *REPORT PUBBLICAZIONE IMMOBILE*",
        "",
        badge("youtube", "YouTube", "📺"),
        badge("facebook", "Facebook", "📘"),
        badge("instagram", "Instagram", "📸"),
        badge("telegram", "Telegram", "✈️"),
        badge("wordpress", "Sito Web", "🌐"),
        badge("gmb", "Google Business", "🏢"),
        "",
        f"📍 *Indirizzo:* {indirizzo or 'N/D'}",
        f"📅 *Data:* {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "",
        "✨ *Antonio Giancani*"
    ]

    testo = "\n".join(lines)

    try:
        url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_ID}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": BOSS_PHONE,
            "type": "text",
            "text": {"body": testo}
        }
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=30
        )
        if r.status_code == 200:
            print("✅ Report WhatsApp inviato al Boss!")
        else:
            print(f"⚠️ WhatsApp report ({r.status_code}): {r.text[:200]}")
    except Exception as e:
        print(f"⚠️ Errore WhatsApp report: {e}")


def callback_daria(url, payload):
    """Invia risultati alla DarIA WebApp via POST callback."""
    if not url:
        print("⚠️ Callback URL vuoto, skip")
        return
    print(f"📡 Callback a DarIA: {url[:60]}...")
    try:
        payload['action'] = 'nuovo_immobile_callback'
        r = requests.post(url, json=payload, timeout=30)
        print(f"✅ Callback inviato (status {r.status_code})")
    except Exception as e:
        print(f"⚠️ Errore callback: {e}")


# ═══════════════════════════════════════════
# MODALITÀ 1: RICICLO POST (logica originale)
# ═══════════════════════════════════════════

def modifica_testo_annuncio(testo_originale):
    intro = "🌟 UN GRANDE CLASSICO SEMPRE ATTUALE 🌟\n\n"
    return f"{intro}{testo_originale}\n\n#repost #immobiliaregiancani #favara{BRANDING}"


def ricicla_post():
    """Modalità RICICLO: ripubblica vecchi post dal foglio Google."""
    print("=" * 50)
    print("🔄 MODALITÀ RICICLO — Ripubblicazione post esistenti")
    print("=" * 50)

    gc, youtube = get_google_services()
    sheet = gc.open_by_key(SHEET_ID).worksheet("Foglio1")
    raw = sheet.get_all_values()

    headers = [str(h).strip().replace('\n', '').replace('\r', '') for h in raw[0]]
    col = {n: headers.index(n) for n in headers if n}

    records = []
    for r in raw[1:]:
        r_completa = r + [""] * (len(headers) - len(r))
        records.append(dict(zip(headers, r_completa)))

    print(f"🕵️ DIAGNOSTICA: Trovate {len(records)} righe. Colonne: {headers}")

    post_da_riciclare = None
    riga_foglio_originale = None

    for index, r in enumerate(records):
        link_fb = str(r.get("Link_Facebook", "")).strip()
        link_yt = str(r.get("Link_YouTube", "")).strip()
        pubblicato = str(r.get("Pubblicato", "")).strip().upper()

        if index < 5:
            print(f"🔍 [Riga {index+2}] -> FB: '{link_fb[:20]}...' | YT: '{link_yt[:20]}...' | Pubblicato: '{pubblicato}'")

        if (link_fb or link_yt) and pubblicato == "SI":
            post_da_riciclare = r
            riga_foglio_originale = index + 2
            print(f"🎯 TROVATO! Post da riciclare alla riga {riga_foglio_originale}")
            break

    if not post_da_riciclare:
        print("ℹ️ Nessun vecchio post trovato da riciclare.")
        return

    url_fb_vecchio = post_da_riciclare.get("Link_Facebook", "").strip()
    url_yt_vecchio = post_da_riciclare.get("Link_YouTube", "").strip()
    testo_vecchio = post_da_riciclare.get("Descrizione", "")

    nuovo_testo = modifica_testo_annuncio(testo_vecchio)
    video_temp = None

    if url_yt_vecchio:
        video_temp = download_video(url_yt_vecchio, sorgente="YouTube")
    if not video_temp and url_fb_vecchio:
        print("⚠️ YouTube non disponibile, tento da Facebook...")
        video_temp = download_video(url_fb_vecchio, sorgente="Facebook")

    if not video_temp:
        print("❌ Impossibile scaricare il video. Interruzione.")
        return

    print(f"✅ Video pronto ({video_temp}). Inizio ripubblicazione...")

    nuovo_link_fb = upload_facebook(video_temp, nuovo_testo)
    titolo_yt = f"RIPROPOSTA: {post_da_riciclare.get('Tipologia_Immobile', 'Immobile')} a {post_da_riciclare.get('Citta', 'Favara')}"
    nuovo_link_yt = upload_youtube(youtube, video_temp, titolo_yt, nuovo_testo)
    send_telegram(video_temp, nuovo_testo, channel=False)

    col_pubblicato_idx = headers.index("Pubblicato") + 1
    sheet.update_cell(riga_foglio_originale, col_pubblicato_idx, "RICICLATO")
    print(f"🔄 Riga {riga_foglio_originale} impostata a 'RICICLATO'.")

    nuova_riga = [""] * len(headers)
    if "Tipo" in col: nuova_riga[col["Tipo"]] = "POST"
    if "Data" in col: nuova_riga[col["Data"]] = datetime.now().strftime("%Y-%m-%d")
    if "Tipologia" in col: nuova_riga[col["Tipologia"]] = post_da_riciclare.get("Tipologia", "")
    if "Descrizione" in col: nuova_riga[col["Descrizione"]] = nuovo_testo
    if "Tipologia_Immobile" in col: nuova_riga[col["Tipologia_Immobile"]] = post_da_riciclare.get("Tipologia_Immobile", "")
    if "Citta" in col: nuova_riga[col["Citta"]] = post_da_riciclare.get("Citta", "")
    if "Link_Facebook" in col: nuova_riga[col["Link_Facebook"]] = nuovo_link_fb
    if "Link_YouTube" in col: nuova_riga[col["Link_YouTube"]] = nuovo_link_yt
    if "Pubblicato" in col: nuova_riga[col["Pubblicato"]] = "SI"

    sheet.append_row(nuova_riga)
    print(f"📝 Nuova riga aggiunta per il riciclo futuro.")

    if os.path.exists(video_temp):
        os.remove(video_temp)


# ═══════════════════════════════════════════
# MODALITÀ 2: PIPELINE NUOVO IMMOBILE
# ═══════════════════════════════════════════

def pipeline_nuovo_immobile():
    """Modalità NUOVO IMMOBILE: download → edit → upload multi-piattaforma → callback."""
    print("=" * 50)
    print("🏠 MODALITÀ NUOVO IMMOBILE — Pipeline completa")
    print(f"   Job ID: {INPUT_JOB_ID}")
    print(f"   Video URL: {INPUT_VIDEO_URL[:60]}...")
    print(f"   Indirizzo: {INPUT_INDIRIZZO}")
    print("=" * 50)

    try:
        existing = json.loads(INPUT_EXISTING_LINKS) if INPUT_EXISTING_LINKS else {}
    except json.JSONDecodeError:
        existing = {}

    has_yt = bool(existing.get("yt", "").strip() or existing.get("youtube", "").strip())
    has_fb = bool(existing.get("fb", "").strip() or existing.get("facebook", "").strip())
    has_ig = bool(existing.get("ig", "").strip() or existing.get("instagram", "").strip())
    has_tg = bool(existing.get("tg", "").strip() or existing.get("telegram", "").strip())
    has_wp = bool(existing.get("wp", "").strip() or existing.get("wordpress", "").strip() or existing.get("website", "").strip())
    has_gmb = bool(existing.get("gmb", "").strip() or existing.get("google_business", "").strip() or existing.get("google_business_profile", "").strip())

    print(f"📋 Link esistenti: YT={'⏭️' if has_yt else '📤'} | FB={'⏭️' if has_fb else '📤'} | IG={'⏭️' if has_ig else '📤'} | TG={'⏭️' if has_tg else '📤'} | WP={'⏭️' if has_wp else '📤'} | GMB={'⏭️' if has_gmb else '📤'}")

    _, youtube = get_google_services()

    risultati = {
        "job_id": INPUT_JOB_ID,
        "status": "ok",
        "youtube": "skip" if has_yt else "",
        "facebook": "skip" if has_fb else "",
        "instagram": "skip" if has_ig else "",
        "telegram": "skip" if has_tg else "",
        "wordpress": "skip" if has_wp else "",
        "gmb": "skip" if has_gmb else "",
        "indirizzo": INPUT_INDIRIZZO,
        "seo_description": INPUT_SEO_DESCRIPTION
    }

    video_url = INPUT_VIDEO_URL
    if not video_url:
        for key in ["yt", "youtube", "fb", "facebook", "ig", "instagram"]:
            url = existing.get(key, "").strip()
            if url:
                video_url = url
                break

    if not video_url:
        print("❌ Nessun URL video disponibile!")
        risultati["status"] = "error"
        risultati["error"] = "Nessun URL video"
        send_whatsapp_report(risultati, INPUT_INDIRIZZO)
        callback_daria(INPUT_CALLBACK_URL, risultati)
        return

    video_file = download_video(video_url, sorgente="Social")
    if not video_file:
        print("❌ Download video fallito!")
        risultati["status"] = "error"
        risultati["error"] = "Download fallito"
        send_whatsapp_report(risultati, INPUT_INDIRIZZO)
        callback_daria(INPUT_CALLBACK_URL, risultati)
        return

    video_editato = edit_video(video_file, durata=30)

    if not has_fb:
        risultati["facebook"] = upload_facebook(video_editato, INPUT_SEO_DESCRIPTION)

    if not has_yt:
        risultati["youtube"] = upload_youtube(
            youtube, video_editato,
            INPUT_SEO_TITLE or f"Immobile a {INPUT_INDIRIZZO}",
            INPUT_SEO_DESCRIPTION or "Scopri questa opportunità immobiliare"
        )

    if not has_ig:
        fb_url_for_ig = ""
        global LATEST_FB_VIDEO_DIRECT_URL
        
        if risultati["facebook"] and risultati["facebook"] not in ("", "skip"):
            fb_url_for_ig = LATEST_FB_VIDEO_DIRECT_URL
        elif has_fb:
            existing_fb_url = existing.get("fb", "") or existing.get("facebook", "")
            video_id = extract_facebook_video_id(existing_fb_url)
            if video_id:
                fb_url_for_ig = get_facebook_video_direct_url(video_id)

        if not fb_url_for_ig and INPUT_VIDEO_URL and INPUT_VIDEO_URL.startswith("http"):
            fb_url_for_ig = INPUT_VIDEO_URL

        risultati["instagram"] = upload_instagram_reel(
            video_editato,
            INPUT_SEO_DESCRIPTION or "Nuova opportunità immobiliare",
            fb_video_url=fb_url_for_ig
        )

    if not has_tg:
        tg_result = send_telegram(
            video_editato,
            INPUT_SEO_DESCRIPTION or "Nuova opportunità immobiliare",
            channel=True
        )
        risultati["telegram"] = tg_result

    if not has_wp:
        post_video_link = risultati.get("youtube") or risultati.get("facebook") or video_url
        if post_video_link == "skip":
            post_video_link = existing.get("youtube") or existing.get("facebook") or video_url
        
        risultati["wordpress"] = upload_wordpress(
            title=INPUT_SEO_TITLE or f"Nuova Proposta Immobiliare a {INPUT_INDIRIZZO}",
            description=INPUT_SEO_DESCRIPTION or "Scopri tutti i dettagli di questo immobile.",
            video_url=post_video_link
        )

    if not has_gmb:
        gmb_cta_link = risultati.get("youtube") or risultati.get("facebook") or video_url
        if gmb_cta_link == "skip":
            gmb_cta_link = existing.get("youtube") or existing.get("facebook") or video_url
            
        risultati["gmb"] = upload_google_business(
            summary=INPUT_SEO_DESCRIPTION or "Nuova proposta in agenzia.",
            action_url=gmb_cta_link
        )

    send_whatsapp_report(risultati, INPUT_INDIRIZZO)
    callback_daria(INPUT_CALLBACK_URL, risultati)

    for f in ["video_scaricato.mp4", "video_editato.mp4"]:
        if os.path.exists(f):
            os.remove(f)

    print("\n" + "=" * 50)
    print("🏁 PIPELINE COMPLETATA!")
    print(f"   YouTube:   {risultati['youtube'][:60] if risultati['youtube'] else 'N/A'}")
    print(f"   Facebook:  {risultati['facebook'][:60] if risultati['facebook'] else 'N/A'}")
    print(f"   Instagram: {risultati['instagram'][:60] if risultati['instagram'] else 'N/A'}")
    print(f"   Telegram:  {risultati['telegram']}")
    print(f"   WordPress: {risultati['wordpress'][:60] if risultati['wordpress'] else 'N/A'}")
    print(f"   Google BP: {risultati['gmb']}")
    print("=" * 50)
    print("\n✨ Antonio Giancani")


def main():
    print("🤖 Bot Pubblicazione Immobiliare — Avvio")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if INPUT_VIDEO_URL or INPUT_JOB_ID:
        pipeline_nuovo_immobile()
    else:
        ricicla_post()

    print("\n✨ Antonio Giancani")


if __name__ == "__main__":
    main()
