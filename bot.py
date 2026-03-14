import os
import json
import requests
import gspread
import base64
import time
import re
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
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY")

# --- CONFIGURAZIONE WAHA (WHATSAPP) ---
# Usiamo l'IP di Tailscale del tuo Raspberry
WAHA_URL            = os.environ.get("WAHA_URL", "http://100.121.235.36:3000")
WAHA_API_KEY        = os.environ.get("WAHA_API_KEY", "immobiliare2024")
WHATSAPP_CHANNEL_ID = os.environ.get("WHATSAPP_CHANNEL_ID", "120363191994943047@newsletter")

WP_USER     = "Antonio Giancani"
WP_API_URL  = "https://www.immobiliaregiancani.it/wp-json/wp/v2/property"
SHEET_ID    = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"

DRIVE_FOLDER_NAME      = "Video_Da_Ripubblicare"
GIORNI_RIPUBBLICAZIONE = 30

# ---------------------------------------------------------------------------
# NUOVA FUNZIONE: STRATEGIA WHATSAPP (Solo Testo + Tutti i Link)
# ---------------------------------------------------------------------------
def posta_su_whatsapp_strategico(tipologia, descrizione, yt_link, fb_link, wp_link=None):
    """
    Invia un messaggio di solo testo a WhatsApp. 
    Protegge il bot da eventuali blocchi se WAHA è offline.
    """
    try:
        print("🟢 Preparazione messaggio per WhatsApp...")
        url = f"{WAHA_URL}/api/sendText"
        headers = {"X-Api-Key": WAHA_API_KEY, "Content-Type": "application/json"}
        
        # Pulizia descrizione per WhatsApp (massimo 300 caratteri nell'anteprima)
        desc_wa = descrizione[:300] + "..." if len(descrizione) > 300 else descrizione
        
        testo_wa = f"🎬 *NUOVA VIDEO PROPOSTA: {tipologia.upper()}*\n\n"
        testo_wa += f"{desc_wa}\n\n"
        testo_wa += "📺 *Guarda il video completo qui:* \n"
        
        if yt_link: testo_wa += f"🔹 YouTube: {yt_link}\n"
        if fb_link: testo_wa += f"🔹 Facebook: {fb_link}\n"
        if wp_link: testo_wa += f"🔹 Sito Web: {wp_link}\n"
        
        testo_wa += "\n🏠 *Agenzia Giancani - Favara*"

        payload = {
            "session": "default",
            "chatId": WHATSAPP_CHANNEL_ID,
            "text": testo_wa
        }
        
        # Timeout breve: se WAHA non risponde entro 15 secondi, il bot va avanti
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code in [200, 201]:
            print("✅ WhatsApp OK (Strategia Link)")
        else:
            print(f"⚠️ WhatsApp ha risposto con errore: {r.status_code}")
    except Exception as e:
        print(f"⚠️ WhatsApp bypassato per stabilità. Motivo: {e}")

# ... [PULIZIA TESTO AI, VALIDAZIONE SECRETS, AUTENTICAZIONE GOOGLE, ECC. - COPIALI DALLA TUA VERSIONE PRECEDENTE] ...

# [MANTENI QUI LE FUNZIONI: assicura_colonna_data_pubblicazione, normalizza_colonna_pubblicato, 
# cerca_id_drive_per_nome, get_or_create_drive_folder, upload_video_su_drive, 
# riscrivi_descrizione_con_claude, sincronizza_video_da_facebook, 
# posta_su_youtube, posta_su_wordpress, posta_su_facebook, posta_su_telegram]

# ---------------------------------------------------------------------------
# MAIN (MODIFICATO)
# ---------------------------------------------------------------------------
def main():
    validate_secrets()
    gc, drive_service, youtube_service = get_google_services()
    sheet = gc.open_by_key(SHEET_ID).sheet1

    col_data_pub_idx = assicura_colonna_data_pubblicazione(sheet)
    normalizza_colonna_pubblicato(sheet)
    sincronizza_video_da_facebook(sheet, drive_service)

    records = sheet.get_all_records()
    headers = sheet.row_values(1)

    try:
        col_pub_idx      = headers.index("Pubblicato") + 1
        col_data_pub_idx = headers.index("Data Pubblicazione") + 1
    except ValueError as e:
        print(f"❌ Colonna non trovata: {e}")
        return

    oggi = datetime.now().date()

    for i, post in enumerate(records, start=2):
        stato = str(post.get("Pubblicato", "")).strip().upper()
        if stato in ("SI", "SKIP"): continue

        nome_file   = str(post.get("Nome_File_Video", "")).strip()
        descrizione = str(post.get("Descrizione", "")).strip()
        data_post   = str(post.get("Data", str(oggi))).strip()
        tipologia   = str(post.get("Tipologia", "Immobile")).strip()

        if not nome_file: continue

        try:
            if datetime.strptime(data_post, "%Y-%m-%d").date() > oggi:
                continue
        except ValueError: pass

        print(f"\n🆕 Elaborazione: {nome_file}")
        titolo_video = f"Immobiliare Giancani - {tipologia} - {data_post}"

        drive_file_id = cerca_id_drive_per_nome(drive_service, nome_file)
        if not drive_file_id: continue

        video_locale = f"temp_video_{i}.mp4"
        try:
            request = drive_service.files().get_media(fileId=drive_file_id)
            with open(video_locale, "wb") as f:
                f.write(request.execute())
        except Exception as e:
            print(f"❌ Download fallito: {e}")
            continue

        # --- PUBBLICAZIONE ---
        yt_link = posta_su_youtube(youtube_service, video_locale, titolo_video, descrizione)
        wp_link = posta_su_wordpress(titolo_video, descrizione, yt_link) if yt_link else None
        fb_link = posta_su_facebook(f"{titolo_video}\n\n{descrizione}", video_locale)
        
        # Telegram
        posta_su_telegram(f"🏠 {tipologia}\n\n{descrizione}\n\nFB: {fb_link}", video_locale)

        # --- WHATSAPP (CON STRATEGIA LINK) ---
        # Questa parte è protetta: se WAHA fallisce, lo sheet viene aggiornato comunque
        posta_su_whatsapp_strategico(tipologia, descrizione, yt_link, fb_link, wp_link)

        # Segna Pubblicato
        data_ora_pub = datetime.now().strftime("%Y-%m-%d %H:%M")
        sheet.update_cell(i, col_pub_idx, "SI")
        sheet.update_cell(i, col_data_pub_idx, data_ora_pub)
        
        if os.path.exists(video_locale):
            os.remove(video_locale)

        print(f"✅ Riga {i} completata su tutti i canali.")
        break

if __name__ == "__main__":
    main()
