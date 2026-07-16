import os
import sys
import json
import base64
import subprocess
import requests
import re
import urllib.parse

# === RECUPERO CONFIGURAZIONI DA VARIABILI D'AMBIENTE ===
WP_URL = os.environ.get("WP_URL", "https://www.immobiliaregiancani.it/wp-json/easy-mcp-ai/v1/mcp")
WP_TOKEN = os.environ.get("WP_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama3-70b-8192")
PROPERTY_ADDRESS = os.environ.get("INPUT_INDIRIZZO", "")

# Verifiche di sicurezza iniziali
if not WP_TOKEN:
    print("ATTENZIONE: Variabile d'ambiente WP_TOKEN non definita. Il caricamento su WordPress fallirà.")
if not GROQ_API_KEY:
    print("ATTENZIONE: Variabile d'ambiente GROQ_API_KEY non definita. L'ottimizzazione con Groq LLM fallirà.")

def call_mcp_tool(tool_name, arguments):
    """Chiama un tool sul server MCP di WordPress usando JSON-RPC."""
    headers = {
        "Authorization": f"Bearer {WP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        },
        "id": 1
    }
    try:
        res = requests.post("https://www.immobiliaregiancani.it/wp-json/easy-mcp-ai/v1/mcp", headers=headers, json=payload, verify=False)
        if res.status_code == 200:
            res_json = res.json()
            if 'result' in res_json and 'content' in res_json['result']:
                text_data = res_json['result']['content'][0]['text']
                if text_data.startswith("Error:"):
                    print(f"Errore restituito dal tool MCP {tool_name}: {text_data}")
                    return None
                return json.loads(text_data)
            else:
                print(f"Risposta MCP non valida per {tool_name}: {res_json}")
        else:
            print(f"Errore HTTP server MCP {res.status_code} per {tool_name}: {res.text}")
    except Exception as e:
        print(f"Eccezione in call_mcp_tool ({tool_name}): {str(e)}")
    return None

def run_command(cmd):
    """Esegue un comando shell e restituisce l'output."""
    try:
        res = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return res.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Errore comando shell: {e.stderr}")
        return None

def get_video_duration(video_path):
    """Ottiene la durata del video in secondi usando ffprobe."""
    cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{video_path}"'
    out = run_command(cmd)
    try:
        return float(out) if out else 0.0
    except ValueError:
        return 0.0

def extract_frames(video_path, num_frames=18):
    """Estrae fotogrammi in HD ad alta qualità mantenendo l'aspect ratio naturale."""
    duration = get_video_duration(video_path)
    if duration <= 0:
        print("Impossibile determinare la durata del video, estrazione fallita.")
        return []
    
    interval = duration / (num_frames + 1)
    extracted_files = []
    
    print(f"Durata video: {duration:.2f}s. Estrazione di {num_frames} fotogrammi mantenendo l'aspect ratio...")
    
    for i in range(1, num_frames + 1):
        timestamp = i * interval
        out_filename = f"foto_temp_{i:02d}.jpg"
        cmd = f'ffmpeg -y -ss {timestamp:.2f} -i "{video_path}" -vframes 1 -q:v 2 "{out_filename}"'
        run_command(cmd)
        if os.path.exists(out_filename) and os.path.getsize(out_filename) > 0:
            extracted_files.append(out_filename)
        else:
            print(f"Errore estrazione fotogramma al secondo {timestamp:.2f}")
            
    return extracted_files

def get_video_metadata(video_url):
    """Ottiene descrizione e titolo originali del video. Cerca prima in metadata.json."""
    if os.path.exists("metadata.json"):
        try:
            with open("metadata.json", "r", encoding="utf-8") as f:
                meta = json.load(f)
                print("Metadati letti con successo da metadata.json!")
                return meta.get("title", "Nuova Proprietà"), meta.get("description", "")
        except Exception as e:
            print("Errore lettura metadata.json:", str(e))

    print("Estrazione metadata via yt-dlp...")
    desc = run_command(f'yt-dlp --get-description "{video_url}"') or ""
    title = run_command(f'yt-dlp --get-title "{video_url}"') or "Nuova Proprietà Immobiliare"
    return title, desc

def extract_price_from_text(text):
    """Estrae il prezzo dell'immobile dal testo descrittivo."""
    matches = re.findall(r'\b\d{1,3}(?:\.\d{3})*(?:,\d{2})?\s*(?:€|euro)\b', text, re.IGNORECASE)
    if not matches:
        matches_iso = re.findall(r'\b\d{2,3}\.\d{3}\b', text)
        if matches_iso:
            price_str = matches_iso[0].replace('.', '')
            return int(price_str)
        return None
    
    price_str = matches[0]
    price_str = re.sub(r'[^\d]', '', price_str)
    try:
        return int(price_str)
    except ValueError:
        return None

def optimize_description_with_groq(original_title, original_desc):
    """Usa Groq LLM per riscrivere e ottimizzare la descrizione con stile prestigioso e senza date."""
    if not GROQ_API_KEY:
        print("Salto ottimizzazione Groq (Chiave mancante).")
        return f"{original_title}\n\n{original_desc}\n\n✨ Immobiliare Giancani"
        
    print("Ottimizzazione testo con Groq...")
    
    prompt_system = (
        "Sei un broker immobiliare d'élite e copywriter professionista per Immobiliare Giancani. "
        "Il tuo compito è ottimizzare la descrizione dell'annuncio per renderla prestigiosa, elegante, presumibilmente persuasiva e professionale. "
        "Focalizzati sulla SEO e GEO locale per la provincia di Agrigento (specialmente Favara). "
        "Usa parole chiave raffinate come 'prestigiosa residenza', 'investimento sicuro', 'ambienti luminosi e ben distribuiti', 'comfort abitativo'. "
        "Organizza il testo con elenchi puntati ed emoji eleganti per favorire la leggibilità. "
        "IMPORTANTE: Non includere MAI date di pubblicazione, scadenze o indicazioni temporali passate (es. '2026', 'febbraio 2026', 'da due mesi', ecc.) "
        "per evitare di far capire da quanto tempo l'immobile è in vendita sul mercato. "
        "Il testo generato deve sempre terminare con la firma '✨ Immobiliare Giancani' in fondo con spaziatura doppia. "
        "Il nome 'Antonio' NON deve comparire in nessuna parte del testo."
    )
    
    user_content = f"Titolo originale: {original_title}\n\nDescrizione originale:\n{original_desc}"
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.7
    }
    
    try:
        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
        res_json = res.json()
        optimized = res_json['choices'][0]['message']['content']
        return optimized
    except Exception as e:
        print("Errore chiamata Groq:", str(e))
        return f"{original_title}\n\n{original_desc}\n\n✨ Immobiliare Giancani"

def upload_photo_to_wp(photo_path):
    """Carica un file immagine su WordPress Media Library via server MCP."""
    try:
        with open(photo_path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode("utf-8")
        
        args = {
            "content_base64": content_b64,
            "filename": os.path.basename(photo_path),
            "mime_type": "image/jpeg"
        }
        res_data = call_mcp_tool("wp_upload_media", args)
        if res_data and 'id' in res_data:
            return res_data['id'], res_data.get('source_url', res_data.get('link'))
    except Exception as e:
        print("Errore upload foto:", str(e))
    return None, None

def create_wp_listing(title, content, featured_media_id, images_urls, video_url):
    """Crea l'annuncio CPT property in WordPress con layout composto, mappa, APE, moduli a scomparsa, calendario visite e DarIA fluttuante ad eventi."""
    print("Creazione dell'annuncio su WordPress via MCP...")
    js_safe_title = title.replace("'", "\\'").replace('"', '\\"')
    
    # 1. Estrae classe energetica (APE) dal testo se presente, altrimenti default "E"
    ape_class = "E"
    content_lower = content.lower()
    for letter in ["a", "b", "c", "d", "e", "f", "g"]:
        if f"classe {letter}" in content_lower or f"classe energetica {letter}" in content_lower:
            ape_class = letter.upper()
            break

    # 2. Calcolo Mutuo Consigliato (80% del valore a 25 anni @ 3.5% tasso fisso)
    price = extract_price_from_text(content) or extract_price_from_text(title)
    has_declared_price = price is not None
    
    if has_declared_price:
        valore_immobile_formatted = f"{price:,}".replace(",", ".")
        importo_mutuo_val = int(price * 0.8)
        importo_mutuo_formatted = f"{importo_mutuo_val:,}".replace(",", ".")
        rata_mensile_val = int(importo_mutuo_val * 0.005) # 5€ per 1.000€
        rata_mensile_formatted = str(rata_mensile_val)
        nota_mutuo = f"Calcolato su importo mutuo di {importo_mutuo_formatted} € (80% del valore dell'immobile di {valore_immobile_formatted} €) per 25 anni a tasso fisso stimato."
    else:
        # Valori di esempio per immobile non dichiarato
        valore_immobile_formatted = "Trattativa Riservata"
        importo_mutuo_formatted = "60.000"
        rata_mensile_formatted = "300"
        nota_mutuo = "Simulazione d'esempio a rata fissa con importo mutuo stimato di 60.000 € (LTV 80% su valore stimato di 75.000 €) per 25 anni."

    # === SEZIONE 1: PREZZO IN CIMA (SE ESISTENTE, ALTRIMENTI PRICE ON CALL) ===
    if has_declared_price:
        price_header_html = (
            f'\n<div class="property-price-header" style="margin-bottom:20px; font-family:\'Outfit\', sans-serif;">\n'
            f'  <span style="color:#64748b; font-size:12px; text-transform:uppercase; font-weight:700; letter-spacing:0.5px;">Prezzo Richiesto</span>\n'
            f'  <strong style="font-size:36px; color:#0f172a; display:block;">{valore_immobile_formatted} €</strong>\n'
            f'</div>\n'
        )
    else:
        price_header_html = (
            f'\n<div class="property-price-header" style="margin-bottom:20px; font-family:\'Outfit\', sans-serif;">\n'
            f'  <span style="color:#e11d48; font-size:12px; text-transform:uppercase; font-weight:700; letter-spacing:0.5px;">Informazioni Prezzo</span>\n'
            f'  <strong style="font-size:30px; color:#e11d48; display:block;">Trattativa Riservata (Price on call)</strong>\n'
            f'</div>\n'
        )

    # === SEZIONE 2: IMMAGINI IN PRIMO PIANO (CLICCABILI) ===
    images_html = ""
    if images_urls:
        images_html = (
            f'\n<div class="property-main-image" style="margin-bottom:15px; border-radius:16px; overflow:hidden; border:1px solid #e2e8f0; box-shadow:0 4px 12px rgba(0,0,0,0.05);">\n'
            f'  <a href="{images_urls[0]}" target="_blank" style="display:block;">\n'
            f'    <img src="{images_urls[0]}" style="width:100%; height:auto; max-height:550px; object-fit:cover; display:block;" alt="{title}" />\n'
            f'  </a>\n'
            f'</div>\n'
        )
        if len(images_urls) > 1:
            images_html += '<div class="property-gallery-grid" style="display:grid; grid-template-columns:repeat(auto-fill, minmax(180px, 1fr)); gap:10px; margin-bottom:25px;">'
            for img_url in images_urls[1:]:
                images_html += f'<div style="overflow:hidden; border-radius:10px; border:1px solid #e2e8f0; aspect-ratio:1/1;"><a href="{img_url}" target="_blank" style="display:block; height:100%;"><img src="{img_url}" style="width:100%; height:100%; object-fit:cover; display:block;" /></a></div>'
            images_html += '</div>'

    # === SEZIONE 3: CONTENUTO / DESCRIZIONE ===
    description_html = f'<div class="property-description" style="font-size:15px; line-height:1.7; color:#334155; margin-bottom:30px;">{content}</div>'

    # === SEZIONE 3.2: VIDEO DI YOUTUBE (INSERITO DOPO LA DESCRIZIONE IN UNA FINESTRA CON CLICCA E VEDI) ===
    video_id = ""
    if "youtube.com" in video_url or "youtu.be" in video_url:
        if "watch?v=" in video_url:
            video_id = video_url.split("watch?v=")[1].split("&")[0]
        elif "youtu.be/" in video_url:
            video_id = video_url.split("youtu.be/")[1].split("?")[0]
            
    video_html = ""
    if video_id:
        video_html = (
            f'\n<div class="property-video-container" style="margin-top:20px; margin-bottom:30px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:20px; font-family:\'Outfit\', sans-serif;">\n'
            f'  <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:15px; flex-wrap:wrap; gap:10px;">\n'
            f'    <h3 style="font-size:18px; color:#0f172a; margin:0; font-weight:700; display:flex; align-items:center; gap:8px;">🎬 Video Tour dell\'Immobile</h3>\n'
            f'    <span style="background:#ef4444; color:#ffffff; padding:4px 10px; font-size:11px; font-weight:700; border-radius:12px; text-transform:uppercase; animation: pulse 1.5s infinite;">clicca e vedi</span>\n'
            f'  </div>\n'
            f'  <iframe width="100%" height="450" src="https://www.youtube.com/embed/{video_id}" frameborder="0" allowfullscreen style="border-radius:12px; box-shadow:0 10px 20px rgba(0,0,0,0.05); display:block;"></iframe>\n'
            f'</div>\n'
        )

    # === SEZIONE 3.5: FALLBACK PRICE ON CALL DOPO LA DESCRIZIONE ===
    fallback_price_html = ""
    if not has_declared_price:
        fallback_price_html = (
            f'\n<div class="property-price-fallback" style="background:#fff1f2; border:1px solid #fecdd3; border-radius:12px; padding:15px; margin-bottom:25px; text-align:center; font-family:\'Outfit\', sans-serif;">\n'
            f'  <span style="font-size:22px; display:block; margin-bottom:4px;">💎</span>\n'
            f'  <strong style="font-size:16px; color:#9f1239; display:block; text-transform:uppercase;">Prezzo su Richiesta (Price on call)</strong>\n'
            f'  <p style="color:#be123c; font-size:13px; margin:5px 0 0 0;">Questa proprietà esclusiva è in trattativa riservata. Contattaci direttamente per ricevere la scheda economica completa.</p>\n'
            f'</div>\n'
        )

    # === SEZIONE 4: PREZZO E MUTUO RIASSUNTIVI ===
    if has_declared_price:
        mortgage_summary_html = (
            f'\n<div class="property-mortgage-summary" style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:25px; font-family:\'Outfit\', sans-serif;">\n'
            f'  <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px; text-align:center;">\n'
            f'    <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:10px 15px;">\n'
            f'      <span style="color:#64748b; font-size:10px; font-weight:700; text-transform:uppercase; display:block; margin-bottom:4px;">Valore Immobile</span>\n'
            f'      <strong style="font-size:20px; color:#0f172a; display:block;">{valore_immobile_formatted} €</strong>\n'
            f'    </div>\n'
            f'    <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:10px 15px;">\n'
            f'      <span style="color:#0284c7; font-size:10px; font-weight:700; text-transform:uppercase; display:block; margin-bottom:4px;">Importo Mutuo (80%)</span>\n'
            f'      <strong style="font-size:20px; color:#0284c7; display:block;">{importo_mutuo_formatted} €</strong>\n'
            f'    </div>\n'
            f'    <div style="background:#ffffff; border:2px solid #10b981; border-radius:12px; padding:10px 15px;">\n'
            f'      <span style="color:#10b981; font-size:10px; font-weight:900; text-transform:uppercase; display:block; margin-bottom:4px;">Rata Mutuo Stimata</span>\n'
            f'      <strong style="font-size:20px; color:#10b981; display:block;">~ {rata_mensile_formatted} € <span style="font-size:11px; font-weight:normal; color:#64748b;">/ mese</span></strong>\n'
            f'    </div>\n'
            f'  </div>\n'
            f'  <div style="font-size:11px; color:#64748b; text-align:center; margin-top:10px; line-height:1.3; font-style:italic;">\n'
            f'    ⚠️ Il calcolo della rata è basato su simulazione a 25 anni tasso fisso ed anticipo del 20% (LTV 80%). Non costituisce proposta contrattuale.\n'
            f'  </div>\n'
            f'</div>\n'
        )
    else:
        mortgage_summary_html = (
            f'\n<div class="property-mortgage-summary" style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:25px; font-family:\'Outfit\', sans-serif;">\n'
            f'  <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px; text-align:center;">\n'
            f'    <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:10px 15px;">\n'
            f'      <span style="color:#64748b; font-size:10px; font-weight:700; text-transform:uppercase; display:block; margin-bottom:4px;">Valore Immobile Stima</span>\n'
            f'      <strong style="font-size:20px; color:#0f172a; display:block;">Trattativa Riservata</strong>\n'
            f'    </div>\n'
            f'    <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:10px 15px;">\n'
            f'      <span style="color:#0284c7; font-size:10px; font-weight:700; text-transform:uppercase; display:block; margin-bottom:4px;">Esempio Mutuo (80%)</span>\n'
            f'      <strong style="font-size:20px; color:#0284c7; display:block;">60.000 €</strong>\n'
            f'    </div>\n'
            f'    <div style="background:#ffffff; border:2px solid #10b981; border-radius:12px; padding:10px 15px;">\n'
            f'      <span style="color:#10b981; font-size:10px; font-weight:900; text-transform:uppercase; display:block; margin-bottom:4px;">Esempio Rata</span>\n'
            f'      <strong style="font-size:20px; color:#10b981; display:block;">~ 300 € <span style="font-size:11px; font-weight:normal; color:#64748b;">/ mese</span></strong>\n'
            f'    </div>\n'
            f'  </div>\n'
            f'  <div style="font-size:11px; color:#64748b; text-align:center; margin-top:10px; line-height:1.3; font-style:italic;">\n'
            f'    ⚠️ {nota_mutuo}\n'
            f'  </div>\n'
            f'</div>\n'
        )

    # === SEZIONE 5: APE CLASSE ENERGETICA COLORATA ED ANIMATA ===
    ape_colors = {
        "A": "#10b981", "B": "#34d399", "C": "#a7f3d0", "D": "#fbbf24", "E": "#f97316", "F": "#ef4444", "G": "#b91c1c"
    }
    ape_color = ape_colors.get(ape_class, "#f97316")
    r = int(ape_color[1:3], 16)
    g = int(ape_color[3:5], 16)
    b = int(ape_color[5:7], 16)
    
    ape_badge_html = (
        f'\n<div class="ape-badge-wrapper" style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:25px; font-family:\'Outfit\', sans-serif;">\n'
        f'  <style>\n'
        f'    @keyframes pulse-ape {{\n'
        f'      0% {{ transform: scale(1); box-shadow: 0 0 0 0 rgba({r},{g},{b}, 0.6); }}\n'
        f'      70% {{ transform: scale(1.02); box-shadow: 0 0 0 10px rgba({r},{g},{b}, 0); }}\n'
        f'      100% {{ transform: scale(1); box-shadow: 0 0 0 0 rgba({r},{g},{b}, 0); }}\n'
        f'    }}\n'
        f'    .ape-highlight-badge {{\n'
        f'      animation: pulse-ape 2.5s infinite;\n'
        f'    }}\n'
        f'  </style>\n'
        f'  <div style="font-weight: 700; font-size: 14px; color: #475569; margin-bottom: 10px;">Certificazione Energetica (APE)</div>\n'
        f'  <div style="display: flex; align-items: center; gap: 15px; flex-wrap: wrap;">\n'
        f'    <div class="ape-highlight-badge" style="background:{ape_color}; color:#ffffff; padding:8px 16px; font-size:16px; font-weight:900; border-radius:10px; display:inline-block; text-align:center; min-width:100px; text-shadow:1px 1px 2px rgba(0,0,0,0.2);">\n'
        f'      CLASSE {ape_class}\n'
        f'    </div>\n'
        f'    <div style="flex-grow:1; display:flex; gap:3px; height:26px; background:#e2e8f0; padding:3px; border-radius:8px; align-items:stretch; min-width:200px;">\n'
    )
    for c, color in ape_colors.items():
        is_active = (c == ape_class)
        opacity = "1" if is_active else "0.3"
        border_style = f"border: 2px solid #0f172a; transform: scale(1.03);" if is_active else ""
        ape_badge_html += f'      <div style="flex:1; background:{color}; border-radius:5px; display:flex; align-items:center; justify-content:center; color:#ffffff; font-size:10px; font-weight:900; opacity:{opacity}; {border_style}">{c}</div>\n'
    ape_badge_html += '    </div>\n  </div>\n</div>\n'

    # === SEZIONE 6: MAPPA PRIVACY (1 KM) ===
    if PROPERTY_ADDRESS:
        approx_address = re.sub(r'\b\d+\b', '', PROPERTY_ADDRESS).strip()
        approx_address = re.sub(r'\s*,\s*', ', ', approx_address)
        if "favara" not in approx_address.lower():
            approx_address += ", Favara (AG)"
        
        map_url = f"https://maps.google.com/maps?q={urllib.parse.quote(approx_address)}&t=&z=14&ie=UTF8&iwloc=&output=embed"
        map_title = "📍 Mappa: Zona indicativa dell'immobile (Raggio di 1 km per privacy)"
    else:
        agency_address = "Corso Vittorio Veneto 151, Favara (AG)"
        map_url = f"https://maps.google.com/maps?q={urllib.parse.quote(agency_address)}&t=&z=16&ie=UTF8&iwloc=&output=embed"
        map_title = "📍 La nostra sede - Immobiliare Giancani"
        
    map_html = (
        f'\n<div class="property-map-section" style="margin-bottom:25px; border-radius:16px; overflow:hidden; border:1px solid #e2e8f0;">\n'
        f'  <div style="background:#f8fafc; padding:12px 20px; border-bottom:1px solid #e2e8f0; font-family:\'Outfit\', sans-serif; font-weight:700; font-size:15px; color:#0f172a;">\n'
        f'    {map_title}\n'
        f'  </div>\n'
        f'  <iframe src="{map_url}" width="100%" height="300" style="border:0; display:block;" allowfullscreen="" loading="lazy"></iframe>\n'
        f'</div>\n'
    )

    # === SEZIONE 7: DESCRIZIONE DI FAVARA ===
    geo_desc_html = (
        '\n<div class="property-geo-desc" style="background:#f1f5f9; border-radius:16px; padding:20px; margin-bottom:25px; font-family:\'Outfit\', sans-serif;">\n'
        '  <h4 style="font-size:18px; color:#0f172a; margin-top:0; margin-bottom:10px; font-weight:700;">📍 Vivere a Favara: Qualità e Collegamenti</h4>\n'
        '  <p style="color:#334155; font-size:14px; line-height:1.6; margin:0;">\n'
        '    Favara si trova in una posizione geografica e logistica di absolutissimo rilievo, a pochissimi minuti dalla rinomata Valle dei Templi di Agrigento e dalle spettacolari spiagge della costa siciliana. Celebre a livello internazionale per il <strong>Farm Cultural Park</strong>, un centro d\'arte indipendente che ha rigenerato il centro storico, Favara offre oggi un tenore di vita accogliente e un eccezionale dinamismo culturale. È una cittadina ideale per chi cerca una qualità della vita originale, ritmi a misura d\'uomo, una ricca tradizione enogastronomica e la comodità di vivere vicini ai principali snodi commerciali e turistici della Sicilia meridionale.\n'
        '  </p>\n'
        '</div>\n'
    )

    # === SEZIONE 9: FORM RICHIESTA MUTUO ===
    mortgage_calculator_html = (
        f'\n<div class="property-mortgage-calculator" style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:25px; margin-bottom:25px; font-family:\'Outfit\', sans-serif; color:#0f172a;">\n'
        f'  <h3 style="font-size:20px; color:#0f172a; margin-top:0; margin-bottom:15px; border-bottom:2px solid #e2e8f0; padding-bottom:8px;">🏦 Calcola Mutuo dell\'Immobile</h3>\n'
        f'  \n'
        f'  <!-- Card Rata ed importi trasparente ad accordion -->\n'
        f'  <div id="mortgage-trigger-card" onclick="toggleMortgageForm()" style="background:linear-gradient(135deg, #ffffff, #f1f5f9); border:2px solid #10b981; border-radius:12px; padding:18px; cursor:pointer; transition:all 0.3s ease; box-shadow:0 4px 10px rgba(16,185,129,0.08);">\n'
        f'    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:10px; text-align:center; margin-bottom:12px;">\n'
        f'      <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; padding:8px;">\n'
        f'        <span style="color:#64748b; font-size:9px; font-weight:700; display:block; text-transform:uppercase;">Valore Casa</span>\n'
        f'        <span style="font-size:15px; color:#0f172a; font-weight:800;">{valore_immobile_formatted} €</span>\n'
        f'      </div>\n'
        f'      <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; padding:8px;">\n'
        f'        <span style="color:#0284c7; font-size:9px; font-weight:700; display:block; text-transform:uppercase;">Importo Finanziato</span>\n'
        f'        <span style="font-size:15px; color:#0284c7; font-weight:800;">{importo_mutuo_formatted} €</span>\n'
        f'      </div>\n'
        f'      <div style="background:#ffffff; border:1px solid #10b981; border-radius:8px; padding:8px;">\n'
        f'        <span style="color:#10b981; font-size:9px; font-weight:900; display:block; text-transform:uppercase;">Rata Stimata</span>\n'
        f'        <span style="font-size:15px; color:#10b981; font-weight:800;">~ {rata_mensile_formatted} € <span style="font-size:9px; color:#64748b;">/ mese</span></span>\n'
        f'      </div>\n'
        f'    </div>\n'
        f'    <div style="font-size:11px; color:#64748b; text-align:center; line-height:1.4; margin-bottom:10px;">\n'
        f'      {nota_mutuo}\n'
        f'    </div>\n'
        f'    <div style="text-align:center;">\n'
        f'      <span style="display:inline-block; background:#10b981; color:#ffffff; padding:5px 12px; font-size:11px; font-weight:700; border-radius:20px; text-transform:uppercase;">👇 Clicca qui per richiedere questo mutuo</span>\n'
        f'    </div>\n'
        f'  </div>\n'
        f'  \n'
        f'  <!-- Form nascosto di base con transizione CSS accordion -->\n'
        f'  <div id="mortgage-collapsible-form" style="max-height:0; opacity:0; overflow:hidden; transition:all 0.5s ease-in-out; margin-top:0;">\n'
        f'    <div style="padding-top:20px; border-top:1px solid #e2e8f0; margin-top:20px;">\n'
        f'      <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:10px; padding:12px; margin-bottom:15px; font-size:12px; line-height:1.4; color:#1e3a8a;">\n'
        f'        📋 Compila tutti i campi obbligatori del modulo per verificare la fattibilità del mutuo con i nostri consulenti.\n'
        f'      </div>\n'
        f'      <form id="mortgage-form" onsubmit="sendMortgageRequest(event)" style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">\n'
        f'        <div style="grid-column: span 2;">\n'
        f'          <label style="font-size:11px; color:#475569; display:block; margin-bottom:4px; font-weight:700;">Nome e Cognome *</label>\n'
        f'          <input type="text" id="m-nome" required style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff;" placeholder="Mario Rossi" />\n'
        f'        </div>\n'
        f'        <div>\n'
        f'          <label style="font-size:11px; color:#475569; display:block; margin-bottom:4px; font-weight:700;">Data di Nascita *</label>\n'
        f'          <input type="date" id="m-data-nascita" required style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff;" />\n'
        f'        </div>\n'
        f'        <div>\n'
        f'          <label style="font-size:11px; color:#475569; display:block; margin-bottom:4px; font-weight:700;">Luogo di Nascita *</label>\n'
        f'          \n'
        f'          <input type="text" id="m-luogo-nascita" required style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff;" placeholder="Favara" />\n'
        f'        </div>\n'
        f'        <div>\n'
        f'          <label style="font-size:11px; color:#475569; display:block; margin-bottom:4px; font-weight:700;">Codice Fiscale *</label>\n'
        f'          <input type="text" id="m-cf" required style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff; text-transform:uppercase;" placeholder="RSSMRA80A01H501U" />\n'
        f'        </div>\n'
        f'        <div>\n'
        f'          <label style="font-size:11px; color:#475569; display:block; margin-bottom:4px; font-weight:700;">Telefono Cellulare *</label>\n'
        f'          <input type="tel" id="m-tel" required style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff;" placeholder="320 1234567" />\n'
        f'        </div>\n'
        f'        <div style="grid-column: span 2;">\n'
        f'          <label style="font-size:11px; color:#475569; display:block; margin-bottom:4px; font-weight:700;">Email *</label>\n'
        f'          <input type="email" id="m-email" required style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff;" placeholder="mario.rossi@example.com" />\n'
        f'        </div>\n'
        f'        <div style="grid-column: span 2; margin-top:5px;">\n'
        f'          <button type="submit" style="width:100%; background:#25d366; color:#ffffff; border:0; padding:12px; border-radius:8px; font-weight:700; font-size:14px; cursor:pointer; display:flex; justify-content:center; align-items:center; gap:8px;">\n'
        f'            💬 Invia Richiesta Mutuo via WhatsApp\n'
        f'          </button>\n'
        f'        </div>\n'
        f'      </form>\n'
        f'    </div>\n'
        f'  </div>\n'
        f'  \n'
        f'  <script>\n'
        f'    let isMortgageOpen = false;\n'
        f'    function toggleMortgageForm() {{\n'
        f'      const card = document.getElementById("mortgage-trigger-card");\n'
        f'      const formDiv = document.getElementById("mortgage-collapsible-form");\n'
        f'      isMortgageOpen = !isMortgageOpen;\n'
        f'      if (isMortgageOpen) {{\n'
        f'        formDiv.style.maxHeight = "500px";\n'
        f'        formDiv.style.opacity = "1";\n'
        f'        card.style.background = "#ffffff";\n'
        f'        card.style.border = "2px solid #64748b";\n'
        f'      }} else {{\n'
        f'        formDiv.style.maxHeight = "0";\n'
        f'        formDiv.style.opacity = "0";\n'
        f'        card.style.background = "linear-gradient(135deg, #ffffff, #f1f5f9)";\n'
        f'        card.style.border = "2px solid #10b981";\n'
        f'      }}\n'
        f'    }}\n'
        f'    function sendMortgageRequest(e) {{\n'
        f'      e.preventDefault();\n'
        f'      const nome = document.getElementById("m-nome").value;\n'
        f'      const dataNasc = document.getElementById("m-data-nascita").value;\n'
        f'      const luogoNasc = document.getElementById("m-luogo-nascita").value;\n'
        f'      const cf = document.getElementById("m-cf").value.toUpperCase();\n'
        f'      const tel = document.getElementById("m-tel").value;\n'
        f'      const email = document.getElementById("m-email").value;\n'
        f'      const importoMutuo = "{importo_mutuo_formatted}";\n'
        f'      const immobile = "{js_safe_title}";\n'
        f'      \n'
        f'      const text = `Salve, sono interessato a questo mutuo per l\'immobile: "${{immobile}}".\\n\\nEcco i miei dati obbligatori compilati:\\n- Nome e Cognome: ${{nome}}\\n- Data di Nascita: ${{dataNasc}}\\n- Luogo di Nascita: ${{luogoNasc}}\\n- Codice Fiscale: ${{cf}}\\n- Telefono: ${{tel}}\\n- Email: ${{email}}\\n- Importo Mutuo Stimato (80%): ${{importoMutuo}} €`;\n'
        f'      \n'
        f'      const whatsappUrl = `https://wa.me/393505902923?text=${{encodeURIComponent(text)}}`;\n'
        f'      window.open(whatsappUrl, "_blank");\n'
        f'    }}\n'
        f'  </script>\n'
        f'</div>\n'
    )

    # === SEZIONE 10: FORM PRENOTA UNA VISITA CON CALENDARIO DELLA SETTIMANA CORRENTE ===
    contact_box_html = (
        f'\n<div class="property-contact-box" style="background:linear-gradient(135deg, #1e293b, #0f172a); border-radius:20px; padding:25px; color:#ffffff; margin-bottom:25px; box-shadow:0 10px 25px rgba(0,0,0,0.15); font-family:\'Outfit\', sans-serif;">\n'
        f'  <h3 style="font-size:20px; color:#ffffff; margin-top:0; margin-bottom:8px; text-align:center;">📞 Richiedi Informazioni o Prenota una Visita</h3>\n'
        f'  <p style="color:#94a3b8; font-size:14px; text-align:center; margin-top:0; margin-bottom:20px;">Compila i tuoi dati e seleziona uno slot orario disponibile.</p>\n'
        f'  \n'
        f'  <form id="info-form" onsubmit="sendInfoRequest(event)" style="display:grid; grid-template-columns:1fr; gap:15px; color:#0f172a;">\n'
        f'    <div>\n'
        f'      <label style="font-size:12px; color:#cbd5e1; display:block; margin-bottom:4px; font-weight:700;">Nome e Cognome *</label>\n'
        f'      <input type="text" id="i-nome" required style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff;" placeholder="Es. Mario Rossi" />\n'
        f'    </div>\n'
        f'    <div>\n'
        f'      <label style="font-size:12px; color:#cbd5e1; display:block; margin-bottom:4px; font-weight:700;">Telefono Cellulare *</label>\n'
        f'      <input type="tel" id="i-tel" required style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff;" placeholder="Es. 320 1234567" />\n'
        f'    </div>\n'
        f'    <div>\n'
        f'      <label style="font-size:12px; color:#cbd5e1; display:block; margin-bottom:4px; font-weight:700;">Email (Opzionale)</label>\n'
        f'      <input type="email" id="i-email" style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff;" placeholder="Es. email@example.com" />\n'
        f'    </div>\n'
        f'    \n'
        f'    <!-- Calendario Settimanale Interattivo (FOMO / Urgenza) -->\n'
        f'    <div style="background:rgba(255, 255, 255, 0.05); border:1px solid rgba(255, 255, 255, 0.15); border-radius:12px; padding:15px;">\n'
        f'      <label style="font-size:13px; color:#ffffff; display:block; margin-bottom:10px; font-weight:700; text-align:center;">🗓️ Seleziona Giorno e Orario della Visita (Settimana Corrente)</label>\n'
        f'      <div id="booking-calendar-container" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:10px; max-height:240px; overflow-y:auto; padding:5px; background:#0f172a; border-radius:8px; border:1px solid rgba(255,255,255,0.1);">\n'
        f'        <!-- Generato Dinamicamente via JS -->\n'
        f'      </div>\n'
        f'      <input type="hidden" id="selected-slot" value="" />\n'
        f'      <span id="selected-slot-display" style="font-size:12px; color:#38bdf8; display:block; margin-top:8px; text-align:center; font-weight:700;">Nessun orario selezionato</span>\n'
        f'    </div>\n'
        f'    \n'
        f'    <div style="margin-top:5px;">\n'
        f'      <button type="submit" style="width:100%; background:#25d366; color:#ffffff; border:0; padding:12px; border-radius:8px; font-weight:700; font-size:14px; cursor:pointer; display:flex; justify-content:center; align-items:center; gap:8px;">\n'
        f'        💬 Prenota Visita via WhatsApp\n'
        f'      </button>\n'
        f'    </div>\n'
        f'  </form>\n'
        f'  \n'
        f'  <script>\n'
        f'    document.addEventListener("DOMContentLoaded", function() {{\n'
        f'      const container = document.getElementById("booking-calendar-container");\n'
        f'      const days = ["Domenica", "Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato"];\n'
        f'      const hours = ["09:30", "11:00", "15:30", "17:00", "18:30"];\n'
        f'      \n'
        f'      let html = "";\n'
        f'      let now = new Date();\n'
        f'      \n'
        f'      let count = 0;\n'
        f'      let dayIndex = 0;\n'
        f'      while (count < 6) {{\n'
        f'        let futureDate = new Date();\n'
        f'        futureDate.setDate(now.getDate() + dayIndex);\n'
        f'        dayIndex++;\n'
        f'        \n'
        f'        if (futureDate.getDay() === 0) continue;\n'
        f'        \n'
        f'        let dateStr = futureDate.toLocaleDateString("it-IT", {{ day: "numeric", month: "short" }});\n'
        f'        let dayName = days[futureDate.getDay()];\n'
        f'        \n'
        f'        html += `<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:10px; text-align:center;">`;\n'
        f'        html += `  <div style="font-size:11px; font-weight:700; color:#94a3b8; text-transform:uppercase;">${{dayName}}</div>`;\n'
        f'        html += `  <div style="font-size:13px; font-weight:800; color:#ffffff; margin-bottom:8px;">${{dateStr}}</div>`;\n'
        f'        html += `  <div style="display:flex; flex-direction:column; gap:4px;">`;\n'
        f'        \n'
        f'        hours.forEach((h, idx) => {{\n'
        f'          let seed = (futureDate.getDate() + idx) % 5;\n'
        f'          let isAvailable = (seed === 2);\n'
        f'          \n'
        f'          if (isAvailable) {{\n'
        f'            html += `    <button type="button" onclick="selectSlot(\'${{dayName}} ${{dateStr}} alle ${{h}}\', this)" style="background:#10b981; color:#ffffff; border:0; padding:4px; font-size:10px; font-weight:700; border-radius:4px; cursor:pointer; width:100%;">🟢 ${{h}}</button>`;\n'
        f'          }} else {{\n'
        f'            html += `    <button type="button" disabled style="background:#ef4444; opacity:0.4; color:#ffffff; border:0; padding:4px; font-size:10px; font-weight:500; border-radius:4px; width:100%; cursor:not-allowed;">🔴 ${{h}}</button>`;\n'
        f'          }}\n'
        f'        }});\n'
        f'        \n'
        f'        html += `  </div>`;\n'
        f'        html += `</div>`;\n'
        f'        count++;\n'
        f'      }}\n'
        f'      container.innerHTML = html;\n'
        f'    }});\n'
        f'    \n'
        f'    let lastSelectedBtn = null;\n'
        f'    function selectSlot(slotText, btn) {{\n'
        f'      document.getElementById("selected-slot").value = slotText;\n'
        f'      document.getElementById("selected-slot-display").innerText = "Selezionato: " + slotText;\n'
        f'      \n'
        f'      if (lastSelectedBtn) {{\n'
        f'        lastSelectedBtn.style.background = "#10b981";\n'
        f'        lastSelectedBtn.style.color = "#ffffff";\n'
        f'      }}\n'
        f'      btn.style.background = "#ffffff";\n'
        f'      btn.style.color = "#0f172a";\n'
        f'      lastSelectedBtn = btn;\n'
        f'    }}\n'
        f'    \n'
        f'    function sendInfoRequest(e) {{\n'
        f'      e.preventDefault();\n'
        f'      const nome = document.getElementById("i-nome").value;\n'
        f'      const tel = document.getElementById("i-tel").value;\n'
        f'      const email = document.getElementById("i-email").value || "Non fornita";\n'
        f'      const slot = document.getElementById("selected-slot").value || "Non specificato (Appuntamento da concordare)";\n'
        f'      const immobile = "{js_safe_title}";\n'
        f'      \n'
        f'      const text = `Salve, vorrei avere informazioni per questo immobile: "${{immobile}}".\\n\\nEcco i miei dati di contatto:\\n- Nome e Cognome: ${{nome}}\\n- Telefono Cellulare: ${{tel}}\\n- Email: ${{email}}\\n- Orario Visita Richiesto: ${{slot}}`;\n'
        f'      \n'
        f'      const whatsappUrl = `https://wa.me/393505902923?text=${{encodeURIComponent(text)}}`;\n'
        f'      window.open(whatsappUrl, "_blank");\n'
        f'    }}\n'
        f'  </script>\n'
        f'  <div style="text-align:center; font-size:13px; color:#cbd5e1; border-top:1px solid rgba(255,255,255,0.1); padding-top:15px; margin-top:15px;">\n'
        f'    📍 <strong>Sede Agenzia:</strong> Corso Vittorio Veneto 151, Favara (AG)\n'
        f'  </div>\n'
        f'</div>\n'
    )

    # === SEZIONE 11: SPAZIO PLANIMETRIA & LOGO ===
    planimetry_html = (
        '\n<div class="property-planimetry-section" style="margin-bottom:25px; padding:25px; border:2px dashed #cbd5e1; border-radius:16px; background:#f8fafc; text-align:center; font-family:\'Outfit\', sans-serif;">\n'
        '  <span style="font-size:36px; display:block; margin-bottom:8px;">📐</span>\n'
        '  <h4 style="font-size:18px; color:#1e293b; margin-top:0; margin-bottom:5px;">Spazio Planimetria dell\'Immobile</h4>\n'
        '  <p style="color:#64748b; font-size:13px; margin:0 0 15px 0;">La planimetria catastale di questa proprietà è a disposizione dei nostri clienti per la consultazione dei dettagli tecnici e la distribuzione degli spazi.</p>\n'
        '  <span style="display:inline-block; background:#64748b; color:#ffffff; padding:6px 14px; font-size:12px; font-weight:700; border-radius:30px; text-transform:uppercase; letter-spacing:0.5px;">Disponibile su Richiesta</span>\n'
        '</div>\n'
    )
    
    logo_html = (
        '\n<div class="property-footer-logo" style="text-align:center; margin-top:40px; padding-top:20px; border-top:1px solid #e2e8f0; font-family:\'Outfit\', sans-serif;">\n'
        '  <img src="https://www.immobiliaregiancani.it/wp-content/uploads/2025/12/cropped-casetta-330x180.png" alt="Immobiliare Giancani" style="max-width:180px; height:auto; margin:0 auto 10px auto; display:block;" />\n'
        '  <strong style="font-size:16px; color:#1e293b; display:block;">✨ Immobiliare Giancani</strong>\n'
        '</div>\n'
    )

    # === SEZIONE 12: WIDGET STICKY 'DARIA' CON CHAT INTERATTIVA CON ALGORITMO LOCALE E APPSCRIPT ===
    daria_sticky_widget_html = (
        f'\n<!-- Contenitore del Widget Fluttuante DarIA -->\n'
        f'<div id="daria-root-widget" style="position:fixed; bottom:80px; right:25px; z-index:99999; font-family:\'Outfit\', sans-serif;">\n'
        f'  \n'
        f'  <style>\n'
        f'    @keyframes pulse-ring-daria {{\n'
        f'      0% {{ transform: scale(0.95); opacity: 0.85; }}\n'
        f'      50% {{ transform: scale(1.1); opacity: 0.4; }}\n'
        f'      100% {{ transform: scale(1.25); opacity: 0; }}\n'
        f'    }}\n'
        f'    .daria-round-trigger {{\n'
        f'      width: 66px;\n'
        f'      height: 66px;\n'
        f'      background: #ffffff;\n'
        f'      border-radius: 50%;\n'
        f'      box-shadow: 0 8px 24px rgba(0,0,0,0.18);\n'
        f'      display: flex;\n'
        f'      align-items: center;\n'
        f'      justify-content: center;\n'
        f'      cursor: pointer;\n'
        f'      position: relative;\n'
        f'      transition: all 0.3s ease;\n'
        f'      border: 2px solid #10b981;\n'
        f'    }}\n'
        f'    .daria-round-trigger:hover {{\n'
        f'      transform: scale(1.08) rotate(5deg);\n'
        f'    }}\n'
        f'    .daria-trigger-pulse {{\n'
        f'      position: absolute;\n'
        f'      top: -2px;\n'
        f'      left: -2px;\n'
        f'      width: 66px;\n'
        f'      height: 66px;\n'
        f'      border: 3px solid #10b981;\n'
        f'      border-radius: 50%;\n'
        f'      animation: pulse-ring-daria 2s infinite;\n'
        f'    }}\n'
        f'    .chat-bubble-msg {{\n'
        f'      padding: 10px 14px;\n'
        f'      border-radius: 14px;\n'
        f'      font-size: 13px;\n'
        f'      line-height: 1.4;\n'
        f'      max-width: 80%;\n'
        f'      margin-bottom: 8px;\n'
        f'      display: inline-block;\n'
        f'      word-wrap: break-word;\n'
        f'    }}\n'
        f'    .msg-daria {{\n'
        f'      background: #f1f5f9;\n'
        f'      color: #0f172a;\n'
        f'      border-bottom-left-radius: 3px;\n'
        f'      text-align: left;\n'
        f'      float: left;\n'
        f'      clear: both;\n'
        f'    }}\n'
        f'    .msg-user {{\n'
        f'      background: #0284c7;\n'
        f'      color: #ffffff;\n'
        f'      border-bottom-right-radius: 3px;\n'
        f'      text-align: left;\n'
        f'      float: right;\n'
        f'      clear: both;\n'
        f'    }}\n'
        f'  </style>\n'
        f'  \n'
        f'  <!-- 1. FUMETTO NOTIFICA TEMPORIZZATO (PRECISO: Ciao Sono qui per aiutarti!!) -->\n'
        f'  <div id="daria-bubble" style="display:none; position:absolute; bottom:85px; right:0; width:180px; background:#0f172a; color:#ffffff; padding:12px 16px; border-radius:16px; font-size:13px; line-height:1.4; box-shadow:0 8px 20px rgba(0,0,0,0.2); transition:all 0.4s ease; transform:translateY(10px); opacity:0; z-index:10; font-weight:700; text-align:center;">\n'
        f'    Ciao Sono qui per aiutarti!!\n'
        f'    <div style="position:absolute; bottom:-6px; right:25px; width:12px; height:12px; background:#0f172a; transform:rotate(45deg);"></div>\n'
        f'  </div>\n'
        f'  \n'
        f'  <!-- 2. BOTTONE AVATAR (CON IMMAGINE CASETTA LOGO AGENZIA) -->\n'
        f'  <div id="daria-button-collapsed" class="daria-round-trigger" onclick="openDariaDrawer()">\n'
        f'    <div class="daria-trigger-pulse"></div>\n'
        f'    <img src="https://www.immobiliaregiancani.it/wp-content/uploads/2025/12/cropped-casetta-330x180.png" style="width:50px; height:auto; position:relative; z-index:2; border-radius:0;" />\n'
        f'    <span style="position:absolute; bottom:2px; right:2px; width:14px; height:14px; background:#10b981; border:2px solid #ffffff; border-radius:50%; z-index:3;"></span>\n'
        f'  </div>\n'
        f'  \n'
        f'  <!-- 3. CASSETTO CHAT INTERATTIVA (FINESTRA STRETTA STILE SMARTPHONE) -->\n'
        f'  <div id="daria-drawer-expanded" style="display:none; position:absolute; bottom:0; right:0; width:310px; background:#ffffff; border-radius:20px; box-shadow:0 15px 35px rgba(0,0,0,0.2); transition:all 0.3s ease; transform:scale(0.8); opacity:0; transform-origin:bottom right; overflow:hidden; border:1px solid #cbd5e1;">\n'
        f'    \n'
        f'    <!-- Header Chat -->\n'
        f'    <div style="background:linear-gradient(135deg, #0f172a, #1e293b); padding:15px; display:flex; align-items:center; gap:12px; color:#ffffff; border-bottom:1px solid #334155;">\n'
        f'      <div style="position:relative; width:40px; height:40px; background:#ffffff; border-radius:50%; display:flex; align-items:center; justify-content:center; padding:5px;">\n'
        f'        <img src="https://www.immobiliaregiancani.it/wp-content/uploads/2025/12/cropped-casetta-330x180.png" style="width:100%; height:auto;" />\n'
        f'        <span style="position:absolute; bottom:0; right:0; width:10px; height:10px; background:#10b981; border:2px solid #ffffff; border-radius:50%;"></span>\n'
        f'      </div>\n'
        f'      <div style="flex-grow:1;">\n'
        f'        <h4 style="margin:0; font-size:14px; font-weight:800;">DarIA Chat</h4>\n'
        f'        <span style="font-size:10px; color:#94a3b8;">Attiva ora • Risponde all\'istante</span>\n'
        f'      </div>\n'
        f'      <button onclick="closeDariaDrawer(event)" style="background:none; border:0; color:#ffffff; cursor:pointer; font-size:22px; font-weight:300; padding:0 5px; line-height:1;">&times;</button>\n'
        f'    </div>\n'
        f'    \n'
        f'    <!-- Area Messaggi Chat -->\n'
        f'    <div id="daria-chat-messages" style="height:250px; overflow-y:auto; padding:15px; background:#f8fafc; display:block;">\n'
        f'      <div class="chat-bubble-msg msg-daria">\n'
        f'        Ciao! Sono DarIA 🤖, l\'assistente AI di Immobiliare Giancani. Come posso aiutarti oggi? Chiedimi pure sul mutuo, sul prezzo o sulle visite!\n'
        f'      </div>\n'
        f'    </div>\n'
        f'    \n'
        f'    <!-- Area Digitazione -->\n'
        f'    <form onsubmit="handleSendDariaMessage(event)" style="display:flex; border-top:1px solid #e2e8f0; background:#ffffff; padding:8px;">\n'
        f'      <input type="text" id="daria-chat-input" placeholder="Scrivi una domanda..." required style="flex-grow:1; border:0; padding:8px 12px; font-size:13px; outline:none; background:#ffffff; color:#0f172a;" />\n'
        f'      <button type="submit" style="background:#0284c7; color:#ffffff; border:0; border-radius:8px; padding:6px 12px; font-size:12px; font-weight:700; cursor:pointer;">Invia</button>\n'
        f'    </form>\n'
        f'    \n'
        f'    <!-- Pulsanti di Contatto Rapido -->\n'
        f'    <div style="background:#f1f5f9; padding:10px; border-top:1px solid #e2e8f0; display:flex; gap:8px; justify-content:stretch;">\n'
        f'      <a href="https://wa.me/393505902923?text=Salve%20vorrei%20informazioni%20su%20questo%20immobile%20su%20Immobiliare%20Giancani" target="_blank" style="flex:1; text-decoration:none; background:#25d366; color:#ffffff; padding:8px; border-radius:10px; font-size:11px; font-weight:700; text-align:center; display:flex; align-items:center; justify-content:center; gap:4px;">\n'
        f'        💬 WhatsApp\n'
        f'      </a>\n'
        f'      <a href="tel:+393201667156" style="flex:1; text-decoration:none; background:#0284c7; color:#ffffff; padding:8px; border-radius:10px; font-size:11px; font-weight:700; text-align:center; display:flex; align-items:center; justify-content:center; gap:4px;">\n'
        f'        📞 Chiama\n'
        f'      </a>\n'
        f'    </div>\n'
        f'    \n'
        f'  </div>\n'
        f'  \n'
        f'</div>\n'
        f'\n'
        f'<script>\n'
        f'  // Mostra il fumetto dopo un paio di secondi (2 secondi esatti)\n'
        f'  setTimeout(function() {{\n'
        f'    const bubble = document.getElementById("daria-bubble");\n'
        f'    bubble.style.display = "block";\n'
        f'    setTimeout(function() {{\n'
        f'      bubble.style.opacity = "1";\n'
        f'      bubble.style.transform = "translateY(0)";\n'
        f'    }}, 50);\n'
        f'    \n'
        f'    // Scompare dopo 6 secondi\n'
        f'    setTimeout(function() {{\n'
        f'      closeDariaBubble();\n'
        f'    }}, 6000);\n'
        f'  }}, 2000);\n'
        f'  \n'
        f'  function closeDariaBubble() {{\n'
        f'    const bubble = document.getElementById("daria-bubble");\n'
        f'    if (bubble) {{\n'
        f'      bubble.style.opacity = "0";\n'
        f'      bubble.style.transform = "translateY(10px)";\n'
        f'      setTimeout(function() {{\n'
        f'        bubble.style.display = "none";\n'
        f'      }}, 400);\n'
        f'    }}\n'
        f'  }}\n'
        f'  \n'
        f'  function openDariaDrawer() {{\n'
        f'    closeDariaBubble();\n'
        f'    const btnCollapsed = document.getElementById("daria-button-collapsed");\n'
        f'    const drawerExpanded = document.getElementById("daria-drawer-expanded");\n'
        f'    \n'
        f'    btnCollapsed.style.display = "none";\n'
        f'    drawerExpanded.style.display = "block";\n'
        f'    setTimeout(function() {{\n'
        f'      drawerExpanded.style.opacity = "1";\n'
        f'      drawerExpanded.style.transform = "scale(1)";\n'
        f'    }}, 50);\n'
        f'  }}\n'
        f'  \n'
        f'  function closeDariaDrawer(e) {{\n'
        f'    if(e) e.stopPropagation();\n'
        f'    const btnCollapsed = document.getElementById("daria-button-collapsed");\n'
        f'    const drawerExpanded = document.getElementById("daria-drawer-expanded");\n'
        f'    \n'
        f'    drawerExpanded.style.opacity = "0";\n'
        f'    drawerExpanded.style.transform = "scale(0.8)";\n'
        f'    setTimeout(function() {{\n'
        f'      drawerExpanded.style.display = "none";\n'
        f'      btnCollapsed.style.display = "flex";\n'
        f'    }}, 300);\n'
        f'  }}\n'
        f'  \n'
        f'  // Gestione messaggi chat locale + Apps Script\n'
        f'  function handleSendDariaMessage(e) {{\n'
        f'    e.preventDefault();\n'
        f'    const input = document.getElementById("daria-chat-input");\n'
        f'    const text = input.value.trim();\n'
        f'    if (!text) return;\n'
        f'    \n'
        f'    input.value = "";\n'
        f'    appendChatMessage(text, "msg-user");\n'
        f'    \n'
        f'    // Mostra indicatore di scrittura\n'
        f'    const typingBubble = appendChatMessage("Sto scrivendo...", "msg-daria");\n'
        f'    \n'
        f'    // Richiesta a Google Apps Script per risposta dinamica\n'
        f'    const appsScriptUrl = `https://script.google.com/macros/s/AKfycbzq3gfy5JCZJT1tyF4oECkBFVrckxVzqDuAJgUSvPhU4rv2Bztj7EUT3m4b5ILm4Vdc/exec?action=daria_chat&message=${{encodeURIComponent(text)}}&immobile=${{encodeURIComponent("{js_safe_title}")}}`;\n'
        f'    \n'
        f'    fetch(appsScriptUrl)\n'
        f'      .then(r => r.json())\n'
        f'      .then(data => {{\n'
        f'        typingBubble.remove();\n'
        f'        if (data && data.response) {{\n'
        f'          appendChatMessage(data.response, "msg-daria");\n'
        f'        }} else {{\n'
        f'          handleDariaLocalResponse(text, typingBubble);\n'
        f'        }}\n'
        f'      }})\n'
        f'      .catch(() => {{\n'
        f'        // In caso di errore CORS o rete, rispondi con l\'AI locale del browser\n'
        f'        typingBubble.remove();\n'
        f'        handleDariaLocalResponse(text);\n'
        f'      }});\n'
        f'  }}\n'
        f'  \n'
        f'  function appendChatMessage(text, className) {{\n'
        f'    const messagesContainer = document.getElementById("daria-chat-messages");\n'
        f'    const wrapper = document.createElement("div");\n'
        f'    wrapper.style.width = "100%";\n'
        f'    wrapper.style.display = "block";\n'
        f'    \n'
        f'    const bubble = document.createElement("div");\n'
        f'    bubble.className = "chat-bubble-msg " + className;\n'
        f'    bubble.innerText = text;\n'
        f'    \n'
        f'    wrapper.appendChild(bubble);\n'
        f'    messagesContainer.appendChild(wrapper);\n'
        f'    messagesContainer.scrollTop = messagesContainer.scrollHeight;\n'
        f'    return wrapper;\n'
        f'  }}\n'
        f'  \n'
        f'  function handleDariaLocalResponse(msg) {{\n'
        f'    const text = msg.toLowerCase();\n'
        f'    let reply = "Non ho capito bene la domanda. Puoi contattare Antonio su WhatsApp cliccando il pulsante verde qui sotto per assistenza immediata!";\n'
        f'    \n'
        f'    if (text.includes("prezzo") || text.includes("costo") || text.includes("costa")) {{\n'
        f'      reply = "Il prezzo dell\'immobile è su richiesta (Trattativa Riservata). Clicca su WhatsApp in basso per richiedere la scheda prezzi completa!";\n'
        f'    }} else if (text.includes("mutuo") || text.includes("rata") || text.includes("finanziamento")) {{\n'
        f'      reply = "Per questo immobile offriamo una rata stimata a partire da circa 300 € al mese. Trovi la sezione di calcolo interattiva a metà pagina!";\n'
        f'    }} else if (text.includes("visita") || text.includes("vedere") || text.includes("appuntamento")) {{\n'
        f'      reply = "Puoi prenotare una visita in pochi secondi compilando il calendario interattivo che trovi in fondo alla pagina!";\n'
        f'    }} else if (text.includes("dove") || text.includes("posizione") || text.includes("indirizzo")) {{\n'
        f'      reply = "L\'immobile si trova in zona residenziale ben collegata a Favara (AG). Clicca sul tasto WhatsApp per ricevere la posizione esatta!";\n'
        f'    }}\n'
        f'    \n'
        f'    appendChatMessage(reply, "msg-daria");\n'
        f'  }}\n'
        f'</script>\n'
    )
    
    # === ABBINAMENTO ELEMENTI NEL NUOVO ORDINE RICHIESTO ===
    full_content = (
        f"{price_header_html}\n"
        f"{images_html}\n"
        f"{description_html}\n"
        f"{video_html}\n"
        f"{fallback_price_html}\n"
        f"{mortgage_summary_html}\n"
        f"{ape_badge_html}\n"
        f"{map_html}\n"
        f"{geo_desc_html}\n"
        f"{planimetry_html}\n"
        f"{mortgage_calculator_html}\n"
        f"{contact_box_html}\n"
        f"{social_channels_html}\n"
        f"{logo_html}\n"
        f"{daria_sticky_widget_html}"
    )
    
    # === FORZATURA LARGHEZZA PIENA (RIMOZIONE SIDEBAR ASTRA) VIA META ===
    args = {
        "rest_base": "property",
        "item_id": 0,
        "title": title,
        "content": full_content,
        "status": "publish",
        "featured_media": featured_media_id,
        "meta": {
            "site-sidebar-layout": "no-sidebar",
            "site-content-layout": "plain-layout",
            "_astra_single_layout_sidebar": "no-sidebar",
            "_astra_single_layout_content": "plain-layout"
        }
    }
    
    res_data = call_mcp_tool("wp_create_cpt_item", args)
    if res_data and 'link' in res_data:
        return res_data['link']
    return None

def main():
    if len(sys.argv) < 2:
        print("Uso: python crea_annuncio_wp.py <URL_VIDEO_YOUTUBE>")
        video_url = "https://www.youtube.com/watch?v=Cq0wg0_OeGg"
    else:
        video_url = sys.argv[1]
        
    print(f"=== PIPELINE CREAZIONE ANNUNCIO DA VIDEO: {video_url} ===")
    
    # 1. Download Video
    video_filename = "video_annuncio_temp.mp4"
    if video_url.startswith("http") and ".mp4" in video_url:
        print("Download video diretto da URL .mp4...")
        try:
            res = requests.get(video_url, verify=False)
            with open(video_filename, "wb") as f:
                f.write(res.content)
        except Exception as e:
            print("Errore download diretto video:", str(e))
            return
    else:
        print("Download video via yt-dlp...")
        download_cmd = f'yt-dlp -f "best" -o "{video_filename}" "{video_url}"'
        run_command(download_cmd)
    
    if not os.path.exists(video_filename) or os.path.getsize(video_filename) == 0:
        print("Download del video fallito.")
        return
        
    # 2. Estrai metadata originali
    orig_title, orig_desc = get_video_metadata(video_url)
    
    # 3. Pulisce date e trattini dal titolo per non rivelare da quanto tempo è online l'annuncio
    clean_title = re.sub(r'\b\d{4}[-/]\d{2}[-/]\d{2}\b', '', orig_title)
    clean_title = re.sub(r'\b\d{2}[-/]\d{2}[-/]\d{4}\b', '', clean_title)
    clean_title = re.sub(r'\s*-\s*$', '', clean_title.strip())
    clean_title = re.sub(r'^\s*-\s*', '', clean_title)
    clean_title = re.sub(r'\s*-\s*-\s*', ' - ', clean_title)
    clean_title = clean_title.strip()
    
    # 4. Ottimizza descrizione con Groq (stile professionale, senza date)
    optimized_text = optimize_description_with_groq(clean_title, orig_desc)
    
    # 5. Estrazione fotogrammi HD mantenendo l'aspect ratio
    photo_files = extract_frames(video_filename, num_frames=18)
    
    if not photo_files:
        print("Estrazione fotogrammi fallita.")
        return
        
    # 6. Caricamento immagini su WordPress via MCP
    media_ids = []
    media_urls = []
    print(f"Caricamento di {len(photo_files)} immagini su WordPress via MCP...")
    for idx, photo in enumerate(photo_files):
        print(f"Caricamento {idx+1}/{len(photo_files)}: {photo}")
        m_id, m_url = upload_photo_to_wp(photo)
        if m_id and m_url:
            media_ids.append(m_id)
            media_urls.append(m_url)
            
    if not media_ids:
        print("Nessuna immagine caricata su WordPress, impossibile continuare.")
        return
        
    featured_id = media_ids[0]
    
    # 7. Crea l'annuncio property su WordPress via MCP
    wp_listing_link = create_wp_listing(clean_title, optimized_text, featured_id, media_urls, video_url)
    
    # 8. Pulizia file temporanei
    print("Pulizia file temporanei in corso...")
    try:
        os.remove(video_filename)
        for photo in photo_files:
            os.remove(photo)
    except Exception as e:
        print("Errore pulizia file:", str(e))
        
    if wp_listing_link:
        print("\n🎉 PROCEDURA COMPLETATA CON SUCCESSO!")
        print(f"👉 Annuncio pubblicato: {wp_listing_link}")
    else:
        print("\n❌ Errore durante la pubblicazione dell'annuncio.")

if __name__ == "__main__":
    main()
