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
WAHA_URL            = "http://100.121.235.36:3000"
WAHA_API_KEY        = "immobiliare2024"
WHATSAPP_CHANNEL_ID = "120363191994943047@newsletter"

WP_USER     = "Antonio Giancani"
WP_API_URL  = "https://www.immobiliaregiancani.it/wp-json/wp/v2/property"
SHEET_ID    = "19m1cStsqyCvzz3-AYFJKPnrLPNaDuCXEKM8Fka76-Hc"
DRIVE_FOLDER_NAME      = "Video_Da_Ripubblicare"
GIORNI_RIPUBBLICAZIONE = 30

# ---------------------------------------------------------------------------
# NUOVA FUNZIONE: STRATEGIA WHATSAPP (Solo Testo + Tutti i Link)
# ---------------------------------------------------------------------------
def send_whatsapp_video_strategy(tipologia, descrizione, yt_link, fb_link, tg_link=None):
    """
    Invia un messaggio su WhatsApp con la descrizione e tutti i link ai social.
    Essendo solo testo, evita l'errore 422 (Plus version) di WAHA.
    """
    try:
        url = f"{WAHA_URL}/api/sendText"
        headers = {"X-Api-Key": WAHA_API_KEY, "Content-Type": "application/json"}
        
        testo_wa = f"🎬 *NUOVO VIDEO: {tipologia.upper()}*\n\n"
        testo_wa += f"{descrizione[:400]}...\n\n" # Tronca se troppo lunga
        testo_wa += "📺 *Guarda il video completo qui:* \n"
        
        if yt_link: testo_wa += f"🔹 YouTube: {yt_link}\n"
        if fb_link: testo_wa += f"🔹 Facebook: {fb_link}\n"
        if tg_link: testo_wa += f"🔹 Telegram: https://t.me/immobiliaregiancani\n" # Link generico canale
        
        testo_wa += "\n📍 Favara, Corso Vittorio Veneto 151\n"
        testo_wa += "🏠 *Agenzia Giancani*"

        payload = {
            "session": "default",
            "chatId": WHATSAPP_CHANNEL_ID,
            "text": testo_wa
        }
        
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        if r.status_code in [200, 201]:
            print("✅ WhatsApp Strategic OK")
        else:
            print(f"⚠️ WhatsApp Error: {r.text}")
    except Exception as e:
        print(f"⚠️ WhatsApp bypassato (offline o errore): {e}")

# ... [MANTENERE TUTTE LE ALTRE FUNZIONI: pulisci_testo, validate_secrets, get_google_services, ecc.] ...

# ---------------------------------------------------------------------------
# MAIN (MODIFICATO PER INCLUDERE WHATSAPP)
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
        col_pub_idx = headers.index("Pubblicato") + 1
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

        # Controllo data
        try:
            if datetime.strptime(data_post, "%Y-%m-%d").date() > oggi:
                continue
        except ValueError: pass

        print(f"\n🆕 Elaborazione video: {nome_file}")
        titolo_video = f"Immobiliare Giancani - {tipologia} - {data_post}"
        
        # Gestione Video Drive
        drive_file_id = cerca_id_drive_per_nome(drive_service, nome_file)
        if not drive_file_id: continue

        video_locale = f"temp_video_{i}.mp4"
        try:
            request = drive_service.files().get_media(fileId=drive_file_id)
            with open(video_locale, "wb") as f:
                f.write(request.execute())
        except Exception as e:
            print(f"❌ Errore download: {e}")
            continue

        # --- PUBBLICAZIONE MULTI-CANALE ---
        
        # 1. YouTube
        yt_link = posta_su_youtube(youtube_service, video_locale, titolo_video, descrizione)
        
        # 2. WordPress
        wp_link = posta_su_wordpress(titolo_video, descrizione, yt_link) if yt_link else None
        
        # 3. Facebook
        fb_link = posta_su_facebook(f"{titolo_video}\n\n{descrizione}", video_locale)

        # 4. Telegram
        desc_troncata = descrizione[:500] + "..." if len(descrizione) > 500 else descrizione
        testo_tg = f"🏠 <b>{tipologia} - {data_post}</b>\n\n{desc_troncata}\n"
        if yt_link: testo_tg += f"\n📺 <a href='{yt_link}'>Guarda su YouTube</a>"
        if wp_link: testo_tg += f"\n🌐 <a href='{wp_link}'>Vedi sul sito</a>"
        if fb_link: testo_tg += f"\n🟦 <a href='{fb_link}'>Vedi su Facebook</a>"
        posta_su_telegram(testo_tg, video_locale)

        # 5. STRATEGIA WHATSAPP (Solo Testo + Tutti i Link)
        # Qui mandiamo il messaggio a WhatsApp con i link appena generati
        send_whatsapp_video_strategy(tipologia, descrizione, yt_link, fb_link)

        # Aggiornamento Sheet
        data_ora_pub = datetime.now().strftime("%Y-%m-%d %H:%M")
        sheet.update_cell(i, col_pub_idx, "SI")
        sheet.update_cell(i, col_data_pub_idx, data_ora_pub)
        
        if os.path.exists(video_locale):
            os.remove(video_locale)

        print("\n🛑 Un video pubblicato su tutti i canali. Fine per oggi.")
        break

if __name__ == "__main__":
    main()
