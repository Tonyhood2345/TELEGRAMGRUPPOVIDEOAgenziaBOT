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
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io
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
INPUT_JOB_ID = os.environ.get("INPUT_JOB_ID", "").strip()
INPUT_VIDEO_URL = os.environ.get("INPUT_VIDEO_URL", "").strip()
INPUT_SEO_TITLE = os.environ.get("INPUT_SEO_TITLE", "").strip()
INPUT_SEO_DESCRIPTION = os.environ.get("INPUT_SEO_DESCRIPTION", "").strip()
INPUT_SEO_HASHTAGS = os.environ.get("INPUT_SEO_HASHTAGS", "").strip()
INPUT_INDIRIZZO = os.environ.get("INPUT_INDIRIZZO", "").strip()
INPUT_CALLBACK_URL = os.environ.get("INPUT_CALLBACK_URL", "").strip()
INPUT_EXISTING_LINKS = os.environ.get("INPUT_EXISTING_LINKS", "{}").strip()

# Evento GitHub Actions: 'workflow_dispatch' = avvio manuale, 'schedule' = cron
GITHUB_EVENT_NAME = os.environ.get("GITHUB_EVENT_NAME", "").strip()

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
    """Scarica video da qualsiasi piattaforma social con yt-dlp.
    Strategia multi-tentativo per aggirare blocchi IP di datacenter (GitHub Actions).
    """
    if not url:
        return None

    output_filename = "video_scaricato.mp4"
    print(f"📥 Scaricamento video da {sorgente}: {url[:80]}")

    # ── Tentativo 1: Download HTTP diretto (per URL .mp4 diretti, CDN Facebook ecc.)
    if any(x in url.lower() for x in ['.mp4', 'fbcdn', 'cdninstagram', 'fbsbx']):
        try:
            print("   🔗 Tentativo download HTTP diretto...")
            headers = {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
                'Referer': 'https://www.facebook.com/'
            }
            r = requests.get(url, headers=headers, stream=True, timeout=120)
            if r.status_code == 200:
                with open(output_filename, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                if os.path.exists(output_filename) and os.path.getsize(output_filename) > 50000:
                    size_mb = os.path.getsize(output_filename) / (1024 * 1024)
                    print(f"✅ Download diretto OK: {output_filename} ({size_mb:.1f} MB)")
                    return output_filename
        except Exception as e:
            print(f"   ⚠️ Download diretto fallito: {e}")

    # ── Tentativo 2: yt-dlp con user-agent Chrome e cookies browser
    formati = [
        'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best[ext=mp4]/best',
        'b[ext=mp4]/best[ext=mp4]/best',
        'best',
    ]
    user_agent = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )

    # Definiamo configurazioni diverse per i tentativi di yt-dlp per bypassare i blocchi
    strategie = [
        # Tentativo 1: Client Android (il più efficace per bypassare il login obbligatorio)
        {'fmt': formati[0], 'args': ['--extractor-args', 'youtube:player-client=android']},
        # Tentativo 2: Client iOS
        {'fmt': formati[0], 'args': ['--extractor-args', 'youtube:player-client=ios']},
        # Tentativo 3: Client web/mweb alternativo
        {'fmt': formati[0], 'args': ['--extractor-args', 'youtube:player-client=mweb,web']},
    ]

    for i, strat in enumerate(strategie, 1):
        try:
            print(f"   🔧 yt-dlp tentativo {i}/{len(strategie)} (formato: {strat['fmt'][:25]} | client: {strat['args'][1]})")
            comando = [
                'yt-dlp',
                '--socket-timeout', '90',
                '--retries', '3',
                '--fragment-retries', '3',
                '--user-agent', user_agent,
                '--add-header', 'Accept-Language:it-IT,it;q=0.9,en;q=0.8',
                '--no-check-certificates',
                '-f', strat['fmt'],
                url,
                '-o', output_filename,
                '--force-overwrites',
                '--no-playlist',
                '--merge-output-format', 'mp4',
            ] + strat['args']
            result = subprocess.run(
                comando, check=True, timeout=300,
                capture_output=True, text=True
            )
            if os.path.exists(output_filename) and os.path.getsize(output_filename) > 50000:
                size_mb = os.path.getsize(output_filename) / (1024 * 1024)
                print(f"✅ Video scaricato: {output_filename} ({size_mb:.1f} MB)")
                return output_filename
        except subprocess.TimeoutExpired:
            print(f"   ⏱️ Timeout tentativo {i}")
            continue
        except subprocess.CalledProcessError as e:
            stderr = e.stderr[:300] if e.stderr else ''
            print(f"   ❌ yt-dlp errore tentativo {i}: {stderr}")
            continue
        except Exception as e:
            print(f"   ❌ Errore generico tentativo {i}: {e}")
            continue

    print(f"❌ Tutti i tentativi di download da {sorgente} sono falliti")
    return None


def get_video_duration(input_file):
    """Recupera la durata del video usando ffprobe."""
    try:
        comando = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            input_file
        ]
        res = subprocess.run(comando, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception as e:
        print(f"⚠️ Impossibile ottenere durata con ffprobe: {e}")
        return 25.0


def edit_video(input_file, durata=25):
    """Taglia il video a max 25 secondi, aggiunge watermark 'Antonio Giancani',
    sfuma a nero gli ultimi 3 secondi e aggiunge la scritta 'Continua... Link in descrizione'.
    """
    output = "video_editato.mp4"
    print(f"🎬 Editing video: trim max {durata}s + watermark + fade out + testo finale")
    try:
        duration = get_video_duration(input_file)
        target_duration = min(duration, float(durata))
        fade_start = max(0.0, target_duration - 3.0)
        fade_duration = target_duration - fade_start
        
        print(f"   ⏱️ Durata video: {duration:.2f}s | Target: {target_duration:.2f}s | Inizio sfumatura: {fade_start:.2f}s")
        
        vf_filter = (
            "drawtext=text='Antonio Giancani'"
            ":fontsize=24"
            ":fontcolor=white"
            ":x=w-tw-20"
            ":y=h-th-20"
            ":shadowx=2"
            ":shadowy=2"
            ":shadowcolor=black@0.7,"
            "drawtext=text='Continua...\\nLink in descrizione'"
            ":fontsize=32"
            ":fontcolor=white"
            ":x=(w-tw)/2"
            ":y=(h-th)/2"
            ":shadowx=2"
            ":shadowy=2"
            ":shadowcolor=black@0.7"
            f":enable='between(t,{fade_start},{target_duration})',"
            f"fade=t=out:st={fade_start}:d={fade_duration}"
        )
        
        comando = [
            'ffmpeg', '-y',
            '-i', input_file,
            '-t', str(target_duration),
            '-vf', vf_filter,
            '-af', f'afade=t=out:st={fade_start}:d={fade_duration}',
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


def upload_threads(video_file, caption, fb_video_url=""):
    """Upload Threads Post via Threads API (similar to IG Reels)."""
    print("🧵 Upload Threads...")
    threads_token = os.environ.get("THREADS_ACCESS_TOKEN")
    threads_user_id = os.environ.get("THREADS_USER_ID")
    
    if not threads_token or not threads_user_id:
        print("⚠️ Threads: credenziali mancanti (THREADS_ACCESS_TOKEN o THREADS_USER_ID), skip")
        return "skip"

    testo = caption + BRANDING

    # Richiede URL pubblico del video
    video_url_for_threads = ""
    if fb_video_url:
        video_url_for_threads = fb_video_url
    else:
        print("⚠️ Threads: serve un URL pubblico del video. Uso fallback...")
        if INPUT_VIDEO_URL and INPUT_VIDEO_URL.startswith("http"):
            video_url_for_threads = INPUT_VIDEO_URL
        else:
            print("❌ Threads: nessun URL pubblico disponibile, skip")
            return ""

    try:
        # Step 1: Crea container
        create_url = f"https://graph.threads.net/v1.0/{threads_user_id}/threads"
        create_data = {
            'media_type': 'VIDEO',
            'video_url': video_url_for_threads,
            'text': testo[:500], # Threads ha un limite di caratteri di 500
            'access_token': threads_token
        }
        r1 = requests.post(create_url, data=create_data, timeout=60)
        if r1.status_code != 200:
            print(f"❌ Threads container error ({r1.status_code}): {r1.text[:200]}")
            return ""

        container_id = r1.json().get('id')
        print(f"📦 Threads Container creato: {container_id}")

        # Step 2: Poll status
        status_url = f"https://graph.threads.net/v1.0/{container_id}"
        for attempt in range(60):
            time.sleep(5)
            r_status = requests.get(
                status_url,
                params={'fields': 'status_code', 'access_token': threads_token},
                timeout=30
            )
            if r_status.status_code == 200:
                status = r_status.json().get('status_code', '')
                if status == 'FINISHED':
                    print(f"✅ Threads Container pronto (tentativo {attempt + 1})")
                    break
                elif status == 'ERROR':
                    print(f"❌ Threads Container in errore")
                    return ""
                else:
                    if attempt % 6 == 0:
                        print(f"⏳ Threads Container status: {status} (tentativo {attempt + 1})")
        else:
            print("❌ Threads Container timeout dopo 5 minuti")
            return ""

        # Step 3: Pubblica
        publish_url = f"https://graph.threads.net/v1.0/{threads_user_id}/threads_publish"
        r3 = requests.post(
            publish_url,
            data={'creation_id': container_id, 'access_token': threads_token},
            timeout=60
        )
        if r3.status_code == 200:
            media_id = r3.json().get('id', '')
            link = f"https://www.threads.net/post/{media_id}"
            print(f"✅ Threads pubblicato: {link}")
            return link
        else:
            print(f"❌ Threads publish error ({r3.status_code}): {r3.text[:200]}")
            return ""

    except Exception as e:
        print(f"❌ Errore Threads: {e}")
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
        badge("threads", "Threads", "🧵"),
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

    # Invio di sicurezza di backup anche su Telegram personale (solo se non è un gruppo o canale e se differisce dal canale pubblico)
    is_group_or_channel = str(CHAT_ID).startswith("-")
    is_same_as_channel = str(CHAT_ID) == str(TELEGRAM_CHANNEL_ID)
    
    if TELEGRAM_TOKEN and CHAT_ID and not is_group_or_channel and not is_same_as_channel:
        try:
            print("🟢 Invio report Telegram di sicurezza al Boss...")
            tg_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            # Pulizia markdown per evitare errori di parse
            testo_tg = testo.replace("*", "").replace("_", "")
            requests.post(tg_url, data={"chat_id": CHAT_ID, "text": testo_tg}, timeout=15)
            print("✅ Report Telegram inviato con successo!")
        except Exception as etg:
            print(f"⚠️ Errore invio report di sicurezza Telegram: {etg}")
    else:
        print("⏭️ Backup Report Telegram saltato (CHAT_ID coincide con il canale o è un gruppo pubblico)")


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
    
    # Regola di estrazione dati: i testi devono essere prelevati rigorosamente dalla Colonna F (Indice 5)
    testo_vecchio = ""
    try:
        riga_raw = raw[riga_foglio_originale - 1]
        if len(riga_raw) > 5:
            testo_vecchio = str(riga_raw[5]).strip()
    except Exception:
        pass
    if not testo_vecchio:
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

    # Determiniamo il link del video intero originale
    full_video_link = url_yt_vecchio or url_fb_vecchio

    # Costruiamo la descrizione che include il link del video intero per le piattaforme short
    descrizione_short = nuovo_testo
    if full_video_link:
        descrizione_short += f"\n\n🎥 Guarda il video completo: {full_video_link}"

    # Generiamo la versione di 25 secondi con sfumatura
    video_editato = edit_video(video_temp, durata=25)

    # ── FACEBOOK (Video INTERO, descrizione pulita senza link)
    nuovo_link_fb = upload_facebook(video_temp, nuovo_testo)

    # ── YOUTUBE (Video CORTO 25s, descrizione con link)
    titolo_yt = f"RIPROPOSTA: {post_da_riciclare.get('Tipologia_Immobile', 'Immobile')} a {post_da_riciclare.get('Citta', 'Favara')}"
    nuovo_link_yt = upload_youtube(youtube, video_editato, titolo_yt, descrizione_short)
    
    # ── INSTAGRAM REELS (Video CORTO 25s, descrizione con link)
    fb_url_for_ig = LATEST_FB_VIDEO_DIRECT_URL if (nuovo_link_fb and nuovo_link_fb != "skip") else ""
    if not fb_url_for_ig and url_fb_vecchio:
        video_id_ex = extract_facebook_video_id(url_fb_vecchio)
        if video_id_ex:
            fb_url_for_ig = get_facebook_video_direct_url(video_id_ex)
    
    nuovo_link_ig = upload_instagram_reel(video_editato, descrizione_short, fb_video_url=fb_url_for_ig)

    # ── THREADS (Video CORTO 25s, descrizione con link)
    nuovo_link_threads = upload_threads(video_editato, descrizione_short, fb_video_url=fb_url_for_ig)

    # ── TELEGRAM (Video CORTO 25s, descrizione con link)
    testo_tg = descrizione_short
    link_social_tg = []
    if nuovo_link_yt and nuovo_link_yt not in ("skip", ""):
        link_social_tg.append(f"📺 YouTube: {nuovo_link_yt}")
    if nuovo_link_fb and nuovo_link_fb not in ("skip", ""):
        link_social_tg.append(f"📘 Facebook: {nuovo_link_fb}")
    if nuovo_link_ig and nuovo_link_ig not in ("skip", ""):
        link_social_tg.append(f"📸 Instagram: {nuovo_link_ig}")
    if nuovo_link_threads and nuovo_link_threads not in ("skip", ""):
        link_social_tg.append(f"🧵 Threads: {nuovo_link_threads}")
        
    if link_social_tg:
        testo_tg += "\n\n🔗 *Guarda anche su:* \n" + "\n".join(link_social_tg)
        
    send_telegram(video_editato, testo_tg, channel=False)

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

    for f in [video_temp, video_editato]:
        if f and os.path.exists(f):
            os.remove(f)


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
    has_threads = bool(existing.get("threads", "").strip())
    has_wp = bool(existing.get("wp", "").strip() or existing.get("wordpress", "").strip() or existing.get("website", "").strip())
    has_gmb = bool(existing.get("gmb", "").strip() or existing.get("google_business", "").strip() or existing.get("google_business_profile", "").strip())

    print(f"📋 Link esistenti: YT={'⏭️' if has_yt else '📤'} | FB={'⏭️' if has_fb else '📤'} | IG={'⏭️' if has_ig else '📤'} | TG={'⏭️' if has_tg else '📤'} | Threads={'⏭️' if has_threads else '📤'} | WP={'⏭️' if has_wp else '📤'} | GMB={'⏭️' if has_gmb else '📤'}")

    _, youtube = get_google_services()

    risultati = {
        "job_id": INPUT_JOB_ID,
        "status": "ok",
        "youtube": "skip" if has_yt else "",
        "facebook": "skip" if has_fb else "",
        "instagram": "skip" if has_ig else "",
        "telegram": "skip" if has_tg else "",
        "threads": "skip" if has_threads else "",
        "wordpress": "skip" if has_wp else "",
        "gmb": "skip" if has_gmb else "",
        "indirizzo": INPUT_INDIRIZZO,
        "seo_description": INPUT_SEO_DESCRIPTION
    }

    # Raccoglie tutti i link disponibili in ordine di preferenza per tentativi multipli di download
    possibili_url = []
    if INPUT_VIDEO_URL:
        possibili_url.append((INPUT_VIDEO_URL, "Input Video"))
    for key in ["yt", "youtube", "fb", "facebook", "ig", "instagram"]:
        url = existing.get(key, "").strip()
        if url and url not in [u[0] for u in possibili_url]:
            possibili_url.append((url, key.upper()))

    video_file = None
    for url, sorgente in possibili_url:
        video_file = download_video(url, sorgente=sorgente)
        if video_file:
            print(f"✅ Download video completato con successo da {sorgente}!")
            break
        else:
            print(f"⚠️ Tentativo fallito da {sorgente}, provo il prossimo...")

    # Strategia tollerante agli errori di download
    video_editato = None
    if video_file:
        video_editato = edit_video(video_file, durata=25)
    else:
        print("⚠️ Attivazione modalità FALLBACK TESTUALE: Impossibile scaricare il file video, pubblico solo i testi su Telegram, Sito e Google Business.")
        risultati["status"] = "parziale"
        risultati["youtube"] = "skip (video non disponibile)"
        risultati["facebook"] = "skip (video non disponibile)"
        risultati["instagram"] = "skip (video non disponibile)"
        risultati["threads"] = "skip (video non disponibile)"

    # Determina il link del video completo intero
    full_video_link = ""
    if INPUT_VIDEO_URL and "http" in INPUT_VIDEO_URL:
        full_video_link = INPUT_VIDEO_URL
    else:
        yt_ex = existing.get("yt", "") or existing.get("youtube", "")
        fb_ex = existing.get("fb", "") or existing.get("facebook", "")
        full_video_link = yt_ex or fb_ex

    # Costruiamo la descrizione che include il link del video intero per le piattaforme short
    descrizione_short = INPUT_SEO_DESCRIPTION or "Nuova opportunità immobiliare"
    if video_editato and full_video_link:
        descrizione_short += f"\n\n🎥 Guarda il video completo: {full_video_link}"

    # ── FACEBOOK (richiede video) - Riceve il video INTERO (video_file) e la descrizione senza link
    if not has_fb and video_file:
        print("📘 Facebook: pubblico il video INTERO senza link esterni in descrizione...")
        risultati["facebook"] = upload_facebook(video_file, INPUT_SEO_DESCRIPTION or "Nuovo immobile in proposta.")
    elif not has_fb and not video_file:
        risultati["facebook"] = "errore (video non disponibile)"

    # ── YOUTUBE (richiede video) - Shorts riceve il video TAGLIATO (video_editato) e la descrizione con link
    if not has_yt and video_editato:
        risultati["youtube"] = upload_youtube(
            youtube, video_editato,
            INPUT_SEO_TITLE or f"Immobile a {INPUT_INDIRIZZO}",
            descrizione_short
        )
    elif not has_yt and not video_editato:
        risultati["youtube"] = "errore (video non disponibile)"

    # ── INSTAGRAM (richiede video) - Riceve il video TAGLIATO (video_editato) e la descrizione con link
    if not has_ig and video_editato:
        fb_url_for_ig = ""
        if risultati["facebook"] and risultati["facebook"] not in ("", "skip", "errore (video non disponibile)"):
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
            descrizione_short,
            fb_video_url=fb_url_for_ig
        )
    elif not has_ig and not video_editato:
        risultati["instagram"] = "errore (video non disponibile)"

    # ── THREADS (richiede video) - Riceve il video TAGLIATO (video_editato) e la descrizione con link
    if not has_threads and video_editato:
        fb_url_for_threads = ""
        if risultati["facebook"] and risultati["facebook"] not in ("", "skip", "errore (video non disponibile)"):
            fb_url_for_threads = LATEST_FB_VIDEO_DIRECT_URL
        elif has_fb:
            existing_fb_url = existing.get("fb", "") or existing.get("facebook", "")
            video_id = extract_facebook_video_id(existing_fb_url)
            if video_id:
                fb_url_for_threads = get_facebook_video_direct_url(video_id)

        if not fb_url_for_threads and INPUT_VIDEO_URL and INPUT_VIDEO_URL.startswith("http"):
            fb_url_for_threads = INPUT_VIDEO_URL

        risultati["threads"] = upload_threads(
            video_editato,
            descrizione_short,
            fb_video_url=fb_url_for_threads
        )
    elif not has_threads and not video_editato:
        risultati["threads"] = "errore (video non disponibile)"

    # ── TELEGRAM (supporta sia video che testo semplice)
    if not has_tg:
        descrizione_tg = descrizione_short
        
        link_social_tg = []
        yt_link = risultati.get("youtube") or existing.get("yt") or existing.get("youtube")
        if yt_link and "http" in str(yt_link):
            link_social_tg.append(f"📺 YouTube: {yt_link}")
            
        fb_link = risultati.get("facebook") or existing.get("fb") or existing.get("facebook")
        if fb_link and "http" in str(fb_link):
            link_social_tg.append(f"📘 Facebook: {fb_link}")
            
        ig_link = risultati.get("instagram") or existing.get("ig") or existing.get("instagram")
        if ig_link and "http" in str(ig_link):
            link_social_tg.append(f"📸 Instagram: {ig_link}")

        threads_link = risultati.get("threads") or existing.get("threads")
        if threads_link and "http" in str(threads_link):
            link_social_tg.append(f"🧵 Threads: {threads_link}")
            
        if link_social_tg:
            descrizione_tg += "\n\n🔗 *Guarda anche su:* \n" + "\n".join(link_social_tg)

        if video_editato:
            tg_result = send_telegram(video_editato, descrizione_tg, channel=True)
            risultati["telegram"] = tg_result
        else:
            # Fallback a messaggio testuale semplice per Telegram
            print("✈️ Telegram: invio post testuale semplice...")
            target = TELEGRAM_CHANNEL_ID if TELEGRAM_CHANNEL_ID else CHAT_ID
            if TELEGRAM_TOKEN and target:
                try:
                    tg_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                    testo_tg = descrizione_tg[:4000] + BRANDING
                    requests.post(tg_url, data={"chat_id": target, "text": testo_tg}, timeout=15)
                    risultati["telegram"] = "ok (testo)"
                    print("✅ Telegram: post testuale inviato!")
                except Exception as e_tg:
                    print(f"❌ Telegram errore invio testo: {e_tg}")
                    risultati["telegram"] = ""
            else:
                risultati["telegram"] = ""

    # ── WORDPRESS (SITO WEB) (supporta testo semplice)
    if not has_wp:
        post_video_link = risultati.get("youtube") or risultati.get("facebook") or INPUT_VIDEO_URL
        if post_video_link == "skip":
            post_video_link = existing.get("youtube") or existing.get("facebook") or INPUT_VIDEO_URL
        
        # WP funziona sempre, al massimo non embedda il link video se non valido
        video_embed_url = post_video_link if (post_video_link and "http" in str(post_video_link)) else None
        risultati["wordpress"] = upload_wordpress(
            title=INPUT_SEO_TITLE or f"Nuova Proposta Immobiliare a {INPUT_INDIRIZZO}",
            description=INPUT_SEO_DESCRIPTION or "Scopri tutti i dettagli di questo immobile.",
            video_url=video_embed_url
        )

    # ── GOOGLE BUSINESS PROFILE (GMB) (supporta sempre testo semplice)
    if not has_gmb:
        gmb_cta_link = risultati.get("youtube") or risultati.get("facebook") or INPUT_VIDEO_URL
        if gmb_cta_link == "skip":
            gmb_cta_link = existing.get("youtube") or existing.get("facebook") or INPUT_VIDEO_URL
            
        risultati["gmb"] = upload_google_business(
            summary=INPUT_SEO_DESCRIPTION or "Nuova proposta in agenzia.",
            action_url=gmb_cta_link if (gmb_cta_link and "http" in str(gmb_cta_link)) else None
        )

    send_whatsapp_report(risultati, INPUT_INDIRIZZO)
    callback_daria(INPUT_CALLBACK_URL, risultati)

    for f in ["video_scaricato.mp4", "video_editato.mp4"]:
        if f and os.path.exists(f):
            os.remove(f)

    print("\n" + "=" * 50)
    print("🏁 PIPELINE COMPLETATA!")
    print(f"   YouTube:   {risultati['youtube'][:60] if risultati['youtube'] else 'N/A'}")
    print(f"   Facebook:  {risultati['facebook'][:60] if risultati['facebook'] else 'N/A'}")
    print(f"   Instagram: {risultati['instagram'][:60] if risultati['instagram'] else 'N/A'}")
    print(f"   Telegram:  {risultati['telegram']}")
    print(f"   Threads:   {risultati['threads'][:60] if risultati['threads'] else 'N/A'}")
    print(f"   WordPress: {risultati['wordpress'][:60] if risultati['wordpress'] else 'N/A'}")
    print(f"   Google BP: {risultati['gmb']}")
    print("=" * 50)
    print("\n✨ Antonio Giancani")


def aggiorna_catalogo_ia_wordpress():
    """Genera e aggiorna la pagina 'catalogo-immobili-ia' su WordPress leggendo da Piano_Editoriale_2026."""
    print("🤖 Sincronizzazione Catalogo IA WordPress...")
    if not WP_URL or not WP_USER or not WP_PASSWORD:
        print("⚠️ WordPress: credenziali o URL mancanti, skip aggiornamento catalogo IA")
        return
        
    try:
        gc, _ = get_google_services()
        try:
            sh = gc.open_by_key("1s68pw0WEUcV0ZqltiahAqCp_r5rsycSjxKNh0VZQq_g")
        except Exception:
            sh = gc.open_by_key(SHEET_ID)
            
        try:
            ws = sh.worksheet("Piano_Editoriale_2026")
        except Exception:
            try:
                ws = sh.worksheet("ANNUNCI_ATTIVI")
            except Exception:
                print("⚠️ Impossibile trovare la scheda Piano_Editoriale_2026 o ANNUNCI_ATTIVI")
                return
                
        all_values = ws.get_all_values()
        if not all_values or len(all_values) <= 1:
            print("⚠️ Nessun dato presente nel foglio")
            return
            
        headers = [h.strip().upper() for h in all_values[0]]
        
        def get_col_idx(names, default):
            for name in names:
                if name.upper() in headers:
                    return headers.index(name.upper())
            return default
            
        # Regola di estrazione dati: il testo descrittivo dell'immobile viene prelevato rigorosamente dalla Colonna F (Indice 5)
        idx_testo = 5
        idx_tipo = get_col_idx(["TIPO", "TIPOLOGIA"], 3)
        idx_link = get_col_idx(["LINK", "LINK_VIDEO", "LINK_YOUTUBE"], 4)
        idx_stato = get_col_idx(["STATO"], 2)
        idx_data = get_col_idx(["DATA", "DATA_PUBBLICAZIONE"], 1)
        idx_id = get_col_idx(["ID", "ID_ANNUNCIO", "ID_IMMOBILE"], 0)
        
        annunci_attivi = []
        for r_idx, r in enumerate(all_values[1:], start=2):
            r_len = len(r)
            stato = r[idx_stato].strip().upper() if idx_stato < r_len else ""
            testo = r[idx_testo].strip() if idx_testo < r_len else ""
            
            if testo and stato in ("SI", "ATTIVO", "DISPONIBILE", "PUBBLICATO"):
                tipo = r[idx_tipo].strip() if idx_tipo < r_len else "Immobile"
                link = r[idx_link].strip() if idx_link < r_len else ""
                data = r[idx_data].strip() if idx_data < r_len else ""
                ann_id = r[idx_id].strip() if idx_id < r_len else f"ANN-{r_idx}"
                
                zona = "Favara"
                citta_match = re.search(r'\b(favara|aragona|agrigento|porto empedocle|canicatt\u00ec|licata)\b', testo.lower())
                if citta_match:
                    zona = citta_match.group(1).capitalize()
                
                annunci_attivi.append({
                    "id": ann_id,
                    "data": data,
                    "testo": testo,
                    "tipo": tipo.capitalize(),
                    "link": link,
                    "zona": zona
                })
                
        print(f"📊 Trovati {len(annunci_attivi)} annunci attivi per il catalogo IA.")
        if not annunci_attivi:
            print("⚠️ Nessun annuncio attivo da pubblicare, skip")
            return
            
        html_content = (
            "<p>Benvenuto nel catalogo degli immobili attivi gestiti direttamente da <strong>Antonio Giancani</strong>. "
            "Questa pagina raccoglie l'elenco aggiornato in tempo reale delle propriet\u00e0 immobiliari disponibili a Favara, Aragona, Agrigento e dintorni. "
            "Le informazioni in questa pagina sono strutturate per essere facilmente leggibili dai motori di ricerca e assistenti IA.</p>"
            "<hr style='margin: 30px 0;'>"
            "<div class='ia-listings-container'>"
        )
        
        json_ld_list = []
        
        for idx, ann in enumerate(annunci_attivi):
            prezzo = "Su Richiesta"
            prezzo_val = ""
            prezzo_match = re.search(r'(?:\u20ac\s*|euro\s*|a partire da\s*)?(\d{2,3}(?:\.\d{3})+|\d{4,6})(?:\s*(?:\u20ac|euro|k))?', ann["testo"].lower())
            if prezzo_match:
                prezzo_str = prezzo_match.group(1).replace(".", "")
                prezzo_val = prezzo_str
                prezzo = f"\u20ac {int(prezzo_str):,}".replace(",", ".")
            
            desc_cleaned = ann["testo"].replace('"', '\\"').replace('\n', ' ').replace('\r', '')
            if len(desc_cleaned) > 250:
                desc_cleaned = desc_cleaned[:250] + "..."
                
            html_content += f"""
            <div class="ia-listing-item" style="border: 1px solid #e2e8f0; padding: 20px; margin-bottom: 25px; border-radius: 8px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                <h3 style="margin-top: 0; color: #1e293b;">{ann["tipo"]} in Vendita a {ann["zona"]}</h3>
                <p style="margin: 5px 0;"><strong>Data di pubblicazione:</strong> {ann["data"]}</p>
                <p style="margin: 5px 0;"><strong>Prezzo:</strong> <span style="font-size: 1.1em; color: #0f766e; font-weight: bold;">{prezzo}</span></p>
                <p style="margin: 10px 0; color: #475569;">{ann["testo"].replace(chr(10), '<br>')}</p>
            """
            if ann["link"]:
                html_content += f'<p style="margin: 10px 0;">\ud83c\udfa5 <strong>Video Presentazione:</strong> <a href="{ann["link"]}" target="_blank" rel="noopener">Guarda il video dell\'immobile</a></p>'
                
            html_content += f"""
                <p style="margin: 15px 0 0 0; padding-top: 10px; border-top: 1px dashed #e2e8f0;">
                    \ud83d\udcde <strong>Contatto Referente:</strong> Per informazioni e appuntamenti contattare <strong>Antonio Giancani</strong> al numero <a href="tel:+393201667156">+39 320 166 7156</a>.
                </p>
            </div>
            """
            
            item_schema = {
                "@type": "ListItem",
                "position": idx + 1,
                "item": {
                    "@type": "RealEstateListing",
                    "@id": f"https://www.immobiliaregiancani.it/#listing-{ann['id']}",
                    "name": f"{ann['tipo']} in Vendita a {ann['zona']}",
                    "description": desc_cleaned,
                    "datePosted": ann["data"],
                    "url": ann["link"] or "https://www.immobiliaregiancani.it/",
                    "offers": {
                        "@type": "Offer",
                        "priceCurrency": "EUR",
                        "price": prezzo_val or "0",
                        "seller": {
                            "@type": "RealEstateAgent",
                            "name": "Antonio Giancani",
                            "telephone": "+393201667156",
                            "url": "https://www.immobiliaregiancani.it/"
                        }
                    }
                }
            }
            json_ld_list.append(item_schema)
            
        html_content += "</div>"
        
        schema_graph = {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "RealEstateAgent",
                    "@id": "https://www.immobiliaregiancani.it/#agent",
                    "name": "Antonio Giancani",
                    "telephone": "+393201667156",
                    "url": "https://www.immobiliaregiancani.it/",
                    "image": "https://www.immobiliaregiancani.it/wp-content/uploads/logo.png",
                    "address": {
                        "@type": "PostalAddress",
                        "addressLocality": "Favara",
                        "addressRegion": "AG",
                        "postalCode": "92018",
                        "addressCountry": "IT"
                    }
                },
                {
                    "@type": "ItemList",
                    "name": "Catalogo Immobili Attivi - Antonio Giancani",
                    "numberOfItems": len(annunci_attivi),
                    "itemListElement": json_ld_list
                }
            ]
        }
        
        json_ld_script = f"\n\n<script type='application/ld+json'>\n{json.dumps(schema_graph, indent=2)}\n</script>"
        full_page_html = html_content + json_ld_script
        
        base_url = WP_URL.strip()
        if not base_url.endswith("/"):
            base_url += "/"
            
        search_endpoint = f"{base_url}wp-json/wp/v2/pages?slug=catalogo-immobili-ia"
        from requests.auth import HTTPBasicAuth
        auth = HTTPBasicAuth(WP_USER, WP_PASSWORD)
        
        r = requests.get(search_endpoint, auth=auth, timeout=20)
        page_id = None
        if r.status_code == 200:
            pages = r.json()
            if pages and len(pages) > 0:
                page_id = pages[0].get("id")
                
        payload = {
            "title": "Catalogo Immobili Attivi per Motori di Ricerca IA",
            "content": full_page_html,
            "status": "publish"
        }
        
        if page_id:
            print(f"↔ Pagina esistente trovata (ID: {page_id}). Aggiornamento...")
            update_endpoint = f"{base_url}wp-json/wp/v2/pages/{page_id}"
            r_up = requests.post(update_endpoint, auth=auth, json=payload, timeout=30)
            if r_up.status_code in (200, 201):
                print(f"✅ Catalogo IA aggiornato con successo: {r_up.json().get('link')}")
            else:
                print(f"❌ Errore aggiornamento catalogo ({r_up.status_code}): {r_up.text[:200]}")
        else:
            print("🆕 Pagina non trovata. Creazione in corso...")
            payload["slug"] = "catalogo-immobili-ia"
            create_endpoint = f"{base_url}wp-json/wp/v2/pages"
            r_cr = requests.post(create_endpoint, auth=auth, json=payload, timeout=30)
            if r_cr.status_code in (200, 201):
                print(f"✅ Catalogo IA creato con successo: {r_cr.json().get('link')}")
            else:
                print(f"❌ Errore creazione catalogo ({r_cr.status_code}): {r_cr.text[:200]}")
                
    except Exception as e:
        print(f"❌ Eccezione durante la sincronizzazione del catalogo IA: {e}")


# ═══════════════════════════════════════════
# AUTOMAZIONE AUTO-POST AUTO_POST_IMMOBILI
# ═══════════════════════════════════════════

def get_drive_service():
    """Ritorna l'oggetto service di Google Drive autenticato via Service Account."""
    if not GOOGLE_SECRETS:
        print("⚠️ Google Credentials mancanti per Drive Service")
        return None
    try:
        info = json.loads(GOOGLE_SECRETS)
        creds = Credentials.from_service_account_info(info, scopes=['https://www.googleapis.com/auth/drive'])
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"❌ Errore inizializzazione Drive Service: {e}")
        return None


def download_foto_da_drive(drive_service, link_foto_drive):
    """Scarica le prime 5 immagini da una cartella Drive e le rende temporaneamente pubbliche."""
    if not drive_service:
        return [], []
    
    # Estrae l'ID della cartella Drive
    folder_id_match = re.search(r'[-\w]{25,}', link_foto_drive)
    folder_id = folder_id_match.group(0) if folder_id_match else link_foto_drive
    print(f"📁 Analisi cartella Drive ID: {folder_id}")
    
    try:
        # Elenca tutti i file per trovarne le immagini
        query = f"'{folder_id}' in parents and trashed = false"
        results = drive_service.files().list(q=query, fields="files(id, name, mimeType)", pageSize=40).execute()
        files = results.get('files', [])
        
        image_files = []
        for f in files:
            mime = f.get('mimeType', '').lower()
            if 'image' in mime:
                image_files.append(f)
        
        if not image_files:
            print("⚠️ Nessuna immagine trovata nella cartella Drive")
            return [], []
            
        print(f"📸 Trovate {len(image_files)} immagini. Scarico le prime 5...")
        local_paths = []
        drive_urls = []
        
        os.makedirs("temp_foto", exist_ok=True)
        
        for idx, img in enumerate(image_files[:5]):
            file_id = img['id']
            file_name = img['name']
            ext = os.path.splitext(file_name)[1] or ".jpg"
            local_path = f"temp_foto/foto_{idx}{ext}"
            
            # 1. Rendi leggibile per tutti temporaneamente (per Instagram)
            try:
                drive_service.permissions().create(
                    fileId=file_id,
                    body={'role': 'reader', 'type': 'anyone'},
                    fields='id'
                ).execute()
                public_url = f"https://docs.google.com/uc?export=download&id={file_id}"
                drive_urls.append(public_url)
            except Exception as ePerm:
                print(f"⚠️ Impossibile rendere pubblico il file {file_id}: {ePerm}")
                drive_urls.append(f"https://docs.google.com/uc?export=download&id={file_id}")
            
            # 2. Scarica localmente (per FB e Telegram)
            request = drive_service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            
            with open(local_path, "wb") as local_f:
                local_f.write(fh.getvalue())
            
            local_paths.append(local_path)
            print(f"   💾 Scaricata foto {idx+1}: {local_path}")
            
        return local_paths, drive_urls
    except Exception as e:
        print(f"❌ Errore download foto da Drive: {e}")
        return [], []


def upload_facebook_foto(foto_files, commento):
    """Pubblica un post (singolo o carosello) con foto su Facebook Page."""
    print("📘 Upload Foto Facebook Page...")
    if not FB_PAGE_ID or not FB_PAGE_TOKEN:
        print("⚠️ Facebook Page ID o Token mancanti")
        return ""
    
    testo = commento + BRANDING
    try:
        # Se c'è una sola foto, pubblichiamo in modalità singola
        if len(foto_files) == 1:
            url = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/photos"
            with open(foto_files[0], 'rb') as f:
                r = requests.post(url, data={'access_token': FB_PAGE_TOKEN, 'caption': testo}, files={'source': f}, timeout=120)
            if r.status_code == 200:
                post_id = r.json().get('post_id', r.json().get('id', ''))
                link = f"https://www.facebook.com/{post_id}"
                print(f"✅ Post FB pubblicato con successo: {link}")
                return link
            else:
                print(f"❌ Errore pubblicazione foto FB ({r.status_code}): {r.text}")
                return ""
        
        # Se ci sono più foto, carichiamo le foto non pubblicate (published=false) e poi creiamo il post (feed) allegandole
        media_ids = []
        for file_path in foto_files:
            url = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/photos"
            with open(file_path, 'rb') as f:
                r = requests.post(url, data={'access_token': FB_PAGE_TOKEN, 'published': 'false'}, files={'source': f}, timeout=120)
            if r.status_code == 200:
                media_ids.append(r.json().get('id'))
            else:
                print(f"⚠️ Errore caricamento foto FB temporanea ({r.status_code}): {r.text}")
        
        if not media_ids:
            print("❌ Nessuna foto caricata su FB")
            return ""
            
        # Pubblica il post
        url_feed = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/feed"
        attached_media = [{"media_fbid": m_id} for m_id in media_ids]
        payload = {
            'access_token': FB_PAGE_TOKEN,
            'message': testo,
            'attached_media': json.dumps(attached_media)
        }
        r = requests.post(url_feed, data=payload, timeout=60)
        if r.status_code == 200:
            post_id = r.json().get('id', '')
            link = f"https://www.facebook.com/{post_id}"
            print(f"✅ Carosello FB pubblicato con successo: {link}")
            return link
        else:
            print(f"❌ Errore pubblicazione carosello FB ({r.status_code}): {r.text}")
            return ""
    except Exception as e:
        print(f"❌ Errore Facebook Foto: {e}")
        return ""


def upload_instagram_foto(foto_urls, caption):
    """Pubblica un post (singolo o carosello) con foto su Instagram Page."""
    print("📸 Upload Foto Instagram...")
    if not IG_USER_ID or not FB_PAGE_TOKEN:
        print("⚠️ Instagram: IG_USER_ID o Token mancanti")
        return ""
        
    testo = caption + BRANDING
    try:
        # Se c'è una sola foto, pubblichiamo come foto singola
        if len(foto_urls) == 1:
            url = f"https://graph.facebook.com/v21.0/{IG_USER_ID}/media"
            payload = {
                'image_url': foto_urls[0],
                'caption': testo,
                'access_token': FB_PAGE_TOKEN
            }
            r = requests.post(url, data=payload, timeout=60)
            if r.status_code != 200:
                print(f"❌ Errore creazione container IG ({r.status_code}): {r.text}")
                return ""
            container_id = r.json().get('id')
            
            # Pubblica
            return pubblica_container_instagram(container_id)
            
        # Se ci sono più foto, creiamo gli elementi del carosello
        children_ids = []
        for img_url in foto_urls:
            url = f"https://graph.facebook.com/v21.0/{IG_USER_ID}/media"
            payload = {
                'image_url': img_url,
                'is_carousel_item': 'true',
                'access_token': FB_PAGE_TOKEN
            }
            r = requests.post(url, data=payload, timeout=60)
            if r.status_code == 200:
                children_ids.append(r.json().get('id'))
            else:
                print(f"⚠️ Errore creazione item carosello IG ({r.status_code}): {r.text}")
                
        if not children_ids:
            print("❌ Nessun item carosello creato su IG")
            return ""
            
        # Crea container carosello padre
        url_parent = f"https://graph.facebook.com/v21.0/{IG_USER_ID}/media"
        payload_parent = {
            'media_type': 'CAROUSEL',
            'children': json.dumps(children_ids),
            'caption': testo,
            'access_token': FB_PAGE_TOKEN
        }
        r = requests.post(url_parent, data=payload_parent, timeout=60)
        if r.status_code != 200:
            print(f"❌ Errore creazione container carosello IG ({r.status_code}): {r.text}")
            return ""
        parent_container_id = r.json().get('id')
        
        # Pubblica carosello
        return pubblica_container_instagram(parent_container_id)
    except Exception as e:
        print(f"❌ Errore Instagram Foto: {e}")
        return ""


def pubblica_container_instagram(container_id):
    """Helper per fare il publish di un container IG e attendere la pubblicazione."""
    url_publish = f"https://graph.facebook.com/v21.0/{IG_USER_ID}/media_publish"
    # Attendiamo qualche secondo che IG elabori le foto
    time.sleep(10)
    for _ in range(6):
        r = requests.post(url_publish, data={'creation_id': container_id, 'access_token': FB_PAGE_TOKEN}, timeout=60)
        if r.status_code == 200:
            post_id = r.json().get('id', '')
            link = f"https://www.instagram.com/p/{post_id}"
            print(f"✅ Instagram pubblicato con successo: {link}")
            return link
        else:
            print(f"⏳ IG in elaborazione... riprovo ({r.status_code})")
            time.sleep(10)
    return ""


def invia_telegram_foto(foto_files, caption):
    """Invia le foto su Telegram Channel come gruppo multimediale o foto singola."""
    print("✈️ Inviando foto su Telegram Channel...")
    if not TELEGRAM_TOKEN or not TELEGRAM_CHANNEL_ID:
        print("⚠️ Telegram Token o Channel ID mancanti")
        return False
        
    testo = caption + BRANDING
    try:
        if len(foto_files) == 1:
            url = f"https://api.telegram.com/bot{TELEGRAM_TOKEN}/sendPhoto"
            with open(foto_files[0], 'rb') as f:
                r = requests.post(url, data={'chat_id': TELEGRAM_CHANNEL_ID, 'caption': testo, 'parse_mode': 'Markdown'}, files={'photo': f}, timeout=60)
            return r.status_code == 200
            
        # Invio multiplo (Media Group)
        url = f"https://api.telegram.com/bot{TELEGRAM_TOKEN}/sendMediaGroup"
        files = {}
        media = []
        
        for idx, file_path in enumerate(foto_files):
            key = f"photo_{idx}"
            files[key] = open(file_path, 'rb')
            media_item = {
                'type': 'photo',
                'media': f"attach://{key}"
            }
            if idx == 0:
                media_item['caption'] = testo
                media_item['parse_mode'] = 'Markdown'
            media.append(media_item)
            
        r = requests.post(url, data={'chat_id': TELEGRAM_CHANNEL_ID, 'media': json.dumps(media)}, files=files, timeout=90)
        
        # Chiudi i file
        for f in files.values():
            f.close()
            
        return r.status_code == 200
    except Exception as e:
        print(f"❌ Errore Telegram Foto: {e}")
        return False


def pipeline_post_automatico():
    """Esegue la pubblicazione bisettimanale di un annuncio attivo dall'elenco AUTO_POST_IMMOBILI."""
    print("🚀 Avvio della pipeline AUTO-POST BISETTIMANALE...")
    try:
        gc, _ = get_google_services()
        try:
            sh = gc.open_by_key("1s68pw0WEUcV0ZqltiahAqCp_r5rsycSjxKNh0VZQq_g")
        except Exception:
            sh = gc.open_by_key(SHEET_ID)
            
        try:
            ws = sh.worksheet("AUTO_POST_IMMOBILI")
        except Exception:
            print("❌ Scheda AUTO_POST_IMMOBILI non trovata.")
            return
            
        all_values = ws.get_all_values()
        if len(all_values) <= 1:
            print("⚠️ Nessun immobile presente nella scheda AUTO_POST_IMMOBILI")
            return
            
        headers = [h.strip().upper() for h in all_values[0]]
        
        idx_id = headers.index("ID_IMMOBILE") if "ID_IMMOBILE" in headers else 0
        idx_tipo = headers.index("TIPOLOGIA") if "TIPOLOGIA" in headers else 1
        idx_prezzo = headers.index("PREZZO") if "PREZZO" in headers else 2
        idx_indirizzo = headers.index("INDIRIZZO") if "INDIRIZZO" in headers else 3
        idx_foto = headers.index("LINK_FOTO_DRIVE") if "LINK_FOTO_DRIVE" in headers else 4
        idx_testo = 5 # Colonna F, indice 5 RIGOROSAMENTE!
        idx_stato = headers.index("STATO") if "STATO" in headers else 6
        idx_ultimo = headers.index("ULTIMO_POST") if "ULTIMO_POST" in headers else 7
        
        attivi = []
        for r_idx, r in enumerate(all_values[1:], start=2):
            r_len = len(r)
            stato = r[idx_stato].strip().upper() if idx_stato < r_len else ""
            descrizione = r[idx_testo].strip() if idx_testo < r_len else ""
            
            if stato == "ATTIVO" and descrizione:
                ultimo_post = r[idx_ultimo].strip() if idx_ultimo < r_len else ""
                attivi.append({
                    "row_idx": r_idx,
                    "id": r[idx_id].strip() if idx_id < r_len else "",
                    "tipo": r[idx_tipo].strip() if idx_tipo < r_len else "Immobile",
                    "prezzo": r[idx_prezzo].strip() if idx_prezzo < r_len else "",
                    "indirizzo": r[idx_indirizzo].strip() if idx_indirizzo < r_len else "",
                    "link_foto": r[idx_foto].strip() if idx_foto < r_len else "",
                    "testo": descrizione,
                    "ultimo_post": ultimo_post
                })
                
        if not attivi:
            print("⚠️ Nessun immobile attivo da pubblicare in AUTO_POST_IMMOBILI")
            return
            
        # Scegli l'immobile con la data ULTIMO_POST più vecchia o vuota (rotazione)
        def sort_key(x):
            if not x["ultimo_post"]:
                return datetime.min
            try:
                return datetime.strptime(x["ultimo_post"], "%d/%m/%Y %H:%M")
            except Exception:
                return datetime.max
                
        attivi.sort(key=sort_key)
        scelto = attivi[0]
        
        print(f"🎯 Immobile scelto: {scelto['id']} - {scelto['tipo']} a {scelto['indirizzo']} (Ultimo post: {scelto['ultimo_post'] or 'Mai'})")
        
        # 1. Genera commento/caption con Groq
        prompt_sys = (
            "Sei Antonio Giancani, un perito ed esperto agente immobiliare a Favara. "
            "Scrivi un post social (Facebook/Instagram) estremamente accattivante, coinvolgente ed emozionante per questo immobile in vendita. "
            "Usa emoji appropriate per strutturare il testo in modo leggibile e attraente. "
            "Non essere troppo lungo, concentrati sui punti di forza del servizio e dell'immobile. "
            "Non inventare dati tecnici o dettagli non presenti nella descrizione. "
            "IMPORTANTE: Non menzionare nomi di agenzie, fai risaltare solo Antonio Giancani. "
            "Il post deve terminare tassativamente mettendo in forte risalto il nome 'Antonio Giancani' (es. '\\n\\n✨ Antonio Giancani')."
        )
        user_msg = f"Descrizione: {scelto['testo']}\nPrezzo: {scelto['prezzo']}\nIndirizzo: {scelto['indirizzo']}\nTipologia: {scelto['tipo']}"
        
        didascalia = callGroq(prompt_sys, user_msg)
        if not didascalia or len(didascalia) < 10:
            didascalia = f"Splendida opportunità! {scelto['tipo']} a {scelto['indirizzo']} al prezzo di {scelto['prezzo']}. Contattami per una visita!"
            
        if "Antonio Giancani" not in didascalia:
            didascalia += "\n\n✨ Antonio Giancani"
            
        # 2. Scarica foto da Drive
        drive_service = get_drive_service()
        if not drive_service:
            print("❌ Impossibile inizializzare Drive Service, aborto")
            return
            
        foto_locali, foto_urls = download_foto_da_drive(drive_service, scelto["link_foto"])
        if not foto_locali:
            print("❌ Nessuna foto scaricata da Drive, aborto pubblicazione")
            return
            
        # 3. Pubblica Facebook
        link_fb = upload_facebook_foto(foto_locali, didascalia)
        
        # 4. Pubblica Instagram
        link_ig = upload_instagram_foto(foto_urls, didascalia)
        
        # 5. Invia Telegram
        invia_telegram_foto(foto_locali, didascalia)
        
        # 6. Aggiorna ULTIMO_POST sul foglio
        ora_attuale = datetime.now().strftime("%d/%m/%Y %H:%M")
        ws.update_cell(scelto["row_idx"], idx_ultimo + 1, ora_attuale)
        print(f"📝 Cella aggiornata: Riga {scelto['row_idx']} colonna {idx_ultimo + 1} con valore {ora_attuale}")
        
        # 7. Pulisci foto locali
        for fp in foto_locali:
            try:
                os.remove(fp)
            except Exception:
                pass
        try:
            os.rmdir("temp_foto")
        except Exception:
            pass
            
        # 8. Report al Boss
        msg_report = (
            f"📊 *REPORT AUTO-POST BISETTIMANALE DARIA*\n\n"
            f"🎯 *Immobile:* {scelto['id']} ({scelto['tipo']})\n"
            f"📍 *Indirizzo:* {scelto['indirizzo']}\n"
            f"💰 *Prezzo:* {scelto['prezzo']}\n\n"
            f"📘 *Facebook:* {f'✅ Pubblicato → {link_fb}' if link_fb else '❌ Errore'}\n"
            f"📸 *Instagram:* {f'✅ Pubblicato → {link_ig}' if link_ig else '❌ Errore'}\n"
            f"✈️ *Telegram:* ✅ Inviato\n\n"
            f"✨ *Antonio Giancani*"
        )
        send_whatsapp_message_direct(BOSS_PHONE or CHAT_ID, msg_report)
        print("✅ Pipeline auto-post completata con successo!")
        
    except Exception as e:
        print(f"❌ Errore durante la pipeline auto-post: {e}")
        try:
            send_whatsapp_message_direct(BOSS_PHONE or CHAT_ID, f"⚠️ *Errore pipeline auto-post DarIA:* {e}")
        except Exception:
            pass


def send_whatsapp_message_direct(chat_id, text):
    """Metodo diretto per inviare un messaggio WhatsApp di testo usando le API Meta in bot.py."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        print("⚠️ WhatsApp: credenziali mancanti")
        return False
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": chat_id,
        "type": "text",
        "text": {"body": text}
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    return r.status_code == 200


def main():
    print("🤖 Bot Pubblicazione Immobiliare — Avvio")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🔔 Evento GitHub: {GITHUB_EVENT_NAME or 'non rilevato (test locale)'}")
    print(f"📋 INPUT_VIDEO_URL: '{INPUT_VIDEO_URL[:60] if INPUT_VIDEO_URL else ''}'")
    print(f"📋 INPUT_JOB_ID: '{INPUT_JOB_ID}'")

    # Modalità NUOVO IMMOBILE se:
    # 1. È un workflow_dispatch (avvio manuale), OPPURE
    # 2. Ha INPUT_VIDEO_URL o INPUT_JOB_ID valorizzati (chiamata da DarIA)
    e_dispatch = GITHUB_EVENT_NAME == "workflow_dispatch"
    ha_parametri = bool(INPUT_VIDEO_URL or INPUT_JOB_ID)

    if e_dispatch or ha_parametri:
        if e_dispatch and not ha_parametri:
            print("ℹ️  workflow_dispatch senza parametri → modalità NUOVO IMMOBILE (attendi parametri da DarIA)")
        pipeline_nuovo_immobile()
    else:
        print("⏰ Avvio da CRON")
        # Controlla il giorno della settimana (1 = Martedì, 4 = Venerdì)
        giorno = datetime.now().weekday()
        if giorno in (1, 4):
            print("🗓️ Giorno di AUTO-POST (Martedì/Venerdì) → Avvio pipeline_post_automatico()")
            pipeline_post_automatico()
        else:
            print("🗓️ Giorno ordinario → Avvio riciclo_post()")
            ricicla_post()

    # Sincronizza sempre il catalogo WordPress per l'ottimizzazione IA al termine
    aggiorna_catalogo_ia_wordpress()

    print("\n✨ Antonio Giancani")


if __name__ == "__main__":
    main()
