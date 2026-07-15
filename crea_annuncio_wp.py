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
    # Cerca cifre seguite da € o euro, es. 120.000€, 120000 euro, 120.000,00 €
    matches = re.findall(r'\b\d{1,3}(?:\.\d{3})*(?:,\d{2})?\s*(?:€|euro)\b', text, re.IGNORECASE)
    if not matches:
        # Cerca cifre isolate sopra 10.000 (es. 120.000)
        matches_iso = re.findall(r'\b\d{2,3}\.\d{3}\b', text)
        if matches_iso:
            price_str = matches_iso[0].replace('.', '')
            return int(price_str)
        return None
    
    # Prende la prima corrispondenza e la ripulisce
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
        "Il tuo compito è ottimizzare la descrizione dell'annuncio per renderla prestigiosa, elegante, persuasiva e professionale. "
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
    """Crea l'annuncio CPT property in WordPress con layout ricco, calcolo mutui, form obbligatori e mappa."""
    print("Creazione dell'annuncio su WordPress via MCP...")
    
    # 1. Estrae classe energetica (APE) dal testo se presente, altrimenti default "E"
    ape_class = "E"
    content_lower = content.lower()
    for letter in ["a", "b", "c", "d", "e", "f", "g"]:
        if f"classe {letter}" in content_lower or f"classe energetica {letter}" in content_lower:
            ape_class = letter.upper()
            break

    # 2. Calcolo Mutuo Consigliato (80% del valore a 25 anni @ 3.5% tasso fisso)
    price = extract_price_from_text(content) or extract_price_from_text(title)
    if price:
        valore_immobile_formatted = f"{price:,}".replace(",", ".")
        importo_mutuo_val = int(price * 0.8)
        importo_mutuo_formatted = f"{importo_mutuo_val:,}".replace(",", ".")
        # Rata approssimata: 5€ al mese per ogni 1.000€ finanziati (circa 3.5% fisso a 25 anni)
        rata_mensile_val = int(importo_mutuo_val * 0.005)
        rata_mensile_formatted = str(rata_mensile_val)
        nota_mutuo = f"Calcolato su importo mutuo di {importo_mutuo_formatted} € (80% del valore dell'immobile di {valore_immobile_formatted} €) per 25 anni a tasso fisso stimato."
    else:
        # Simulazione di base: rata 300€ al mese per 25 anni (capitale finanziato ~60.000€)
        rata_mensile_formatted = "300"
        importo_mutuo_formatted = "60.000"
        nota_mutuo = "Simulazione standard a rata fissa con importo mutuo stimato di 60.000 € per 25 anni."
        valore_immobile_formatted = "75.000"
            
    # 3. Generazione Mappa con raggio di 1 km per la privacy o mappa agenzia
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
        f'\n\n<div class="property-map-section" style="margin-bottom:25px; border-radius:16px; overflow:hidden; border:1px solid #e2e8f0;">\n'
        f'  <div style="background:#f8fafc; padding:12px 20px; border-bottom:1px solid #e2e8f0; font-family:\'Outfit\', sans-serif; font-weight:700; font-size:15px; color:#0f172a;">\n'
        f'    {map_title}\n'
        f'  </div>\n'
        f'  <iframe src="{map_url}" width="100%" height="300" style="border:0; display:block;" allowfullscreen="" loading="lazy"></iframe>\n'
        f'</div>\n'
    )

    # 4. Costruisci il badge APE colorato ed animato
    ape_colors = {
        "A": "#10b981", "B": "#34d399", "C": "#a7f3d0", "D": "#fbbf24", "E": "#f97316", "F": "#ef4444", "G": "#b91c1c"
    }
    ape_color = ape_colors.get(ape_class, "#f97316")
    r = int(ape_color[1:3], 16)
    g = int(ape_color[3:5], 16)
    b = int(ape_color[5:7], 16)
    
    ape_badge_html = (
        f'\n\n<div class="ape-badge-wrapper" style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-top:25px; margin-bottom:25px; font-family:\'Outfit\', sans-serif;">\n'
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
        f'  <div style="font-weight: 700; font-size: 15px; color: #475569; margin-bottom: 12px;">Certificazione Energetica (APE)</div>\n'
        f'  <div style="display: flex; align-items: center; gap: 15px; flex-wrap: wrap;">\n'
        f'    <div class="ape-highlight-badge" style="background:{ape_color}; color:#ffffff; padding:10px 20px; font-size:18px; font-weight:900; border-radius:12px; display:inline-block; text-align:center; min-width:110px; text-shadow:1px 1px 2px rgba(0,0,0,0.2);">\n'
        f'      CLASSE {ape_class}\n'
        f'    </div>\n'
        f'    <div style="flex-grow:1; display:flex; gap:3px; height:28px; background:#e2e8f0; padding:3px; border-radius:10px; align-items:stretch; min-width:240px;">\n'
    )
    for c, color in ape_colors.items():
        is_active = (c == ape_class)
        opacity = "1" if is_active else "0.3"
        border_style = f"border: 2px solid #0f172a; transform: scale(1.05);" if is_active else ""
        ape_badge_html += f'      <div style="flex:1; background:{color}; border-radius:6px; display:flex; align-items:center; justify-content:center; color:#ffffff; font-size:11px; font-weight:900; opacity:{opacity}; {border_style}">{c}</div>\n'
    ape_badge_html += '    </div>\n  </div>\n</div>\n'
            
    # 5. Box delle caratteristiche tecniche
    tech_sheet_html = (
        '\n\n<div class="property-tech-sheet" style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:25px;">\n'
        '  <h3 style="font-family:\'Outfit\', sans-serif; font-size:20px; color:#0f172a; margin-top:0; margin-bottom:15px; border-bottom:2px solid #e2e8f0; padding-bottom:8px;">📋 Scheda Tecnica</h3>\n'
        '  <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:15px;">\n'
        f'    <div><span style="color:#64748b; font-size:13px; display:block;">Classe Energetica (APE)</span><strong style="font-size:16px; color:#1e293b;">Classe {ape_class}</strong></div>\n'
        '    <div><span style="color:#64748b; font-size:13px; display:block;">Stato Immobile</span><strong style="font-size:16px; color:#1e293b;">Selezionato / Nuova Proposta</strong></div>\n'
        '    <div><span style="color:#64748b; font-size:13px; display:block;">Localizzazione</span><strong style="font-size:16px; color:#1e293b;">Favara (Agrigento)</strong></div>\n'
        '    <div><span style="color:#64748b; font-size:13px; display:block;">Sito Agenzia</span><strong style="font-size:16px; color:#1e293b;">Immobiliare Giancani</strong></div>\n'
        '  </div>\n'
        '</div>\n'
    )
    
    # 6. Descrizione GEO di Favara
    geo_desc_html = (
        '\n\n<div class="property-geo-desc" style="background:#f1f5f9; border-radius:16px; padding:20px; margin-bottom:25px;">\n'
        '  <h4 style="font-family:\'Outfit\', sans-serif; font-size:18px; color:#0f172a; margin-top:0; margin-bottom:10px;">📍 Vivere a Favara: Qualità e Collegamenti</h4>\n'
        '  <p style="color:#334155; font-size:14px; line-height:1.6; margin:0;">\n'
        '    Favara si trova in una posizione geografica e logistica di assoluto rilievo, a pochissimi minuti dalla rinomata Valle dei Templi di Agrigento e dalle spettacolari spiagge della costa siciliana. Celebre a livello internazionale per il <strong>Farm Cultural Park</strong>, un centro d\'arte indipendente che ha rigenerato il centro storico, Favara offre oggi un tenore di vita accogliente e un eccezionale dinamismo culturale. È una cittadina ideale per chi cerca una qualità della vita originale, ritmi a misura d\'uomo, una ricca tradizione enogastronomica e la comodità di vivere vicini ai principali snodi commerciali e turistici della Sicilia meridionale.\n'
        '  </p>\n'
        '</div>\n'
    )
    
    # 7. Spazio Planimetria
    planimetry_html = (
        '\n\n<div class="property-planimetry-section" style="margin-bottom:25px; padding:25px; border:2px dashed #cbd5e1; border-radius:16px; background:#f8fafc; text-align:center;">\n'
        '  <span style="font-size:36px; display:block; margin-bottom:8px;">📐</span>\n'
        '  <h4 style="font-family:\'Outfit\', sans-serif; font-size:18px; color:#1e293b; margin-top:0; margin-bottom:5px;">Spazio Planimetria dell\'Immobile</h4>\n'
        '  <p style="color:#64748b; font-size:13px; margin:0 0 15px 0;">La planimetria catastale di questa proprietà è a disposizione dei nostri clienti per la consultazione dei dettagli tecnici e la distribuzione degli spazi.</p>\n'
        '  <span style="display:inline-block; background:#64748b; color:#ffffff; padding:6px 14px; font-size:12px; font-weight:700; border-radius:30px; text-transform:uppercase; letter-spacing:0.5px;">Disponibile su Richiesta</span>\n'
        '</div>\n'
    )

    # 8. SEZIONE MUTUI CON SIMULATORE E FORM OBBLIGATORIO WHATSAPP
    # Pulisce il titolo per passarlo al JS
    js_safe_title = title.replace("'", "\\'").replace('"', '\\"')
    mortgage_calculator_html = (
        f'\n\n<div class="property-mortgage-calculator" style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:25px; margin-bottom:25px; font-family:\'Outfit\', sans-serif; color:#0f172a;">\n'
        f'  <h3 style="font-size:20px; color:#0f172a; margin-top:0; margin-bottom:15px; border-bottom:2px solid #e2e8f0; padding-bottom:8px;">🏦 Simulazione Calcolo Mutuo</h3>\n'
        f'  <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:18px; margin-bottom:20px; text-align:center;">\n'
        f'    <span style="color:#64748b; font-size:13px; display:block; font-weight:600;">RATA MENSILE STIMATA (LTV 80%)</span>\n'
        f'    <strong style="font-size:32px; color:#10b981; display:block; margin:5px 0;">{rata_mensile_formatted} € <span style="font-size:14px; font-weight:normal; color:#64748b;">/ mese</span></strong>\n'
        f'    <span style="font-size:12px; color:#64748b; display:block; line-height:1.4;">{nota_mutuo}</span>\n'
        f'  </div>\n'
        f'  <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:12px; padding:15px; margin-bottom:20px; font-size:13px; line-height:1.5; color:#1e3a8a;">\n'
        f'    💡 <strong>Consulenza Gratuita:</strong> Compila il modulo obbligatorio sottostante per richiedere la fattibilità del mutuo. Verrai ricontattato all\'istante per fissare un appuntamento.\n'
        f'  </div>\n'
        f'  <form id="mortgage-form" onsubmit="sendMortgageRequest(event)" style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">\n'
        f'    <div style="grid-column: span 2;">\n'
        f'      <label style="font-size:12px; color:#475569; display:block; margin-bottom:4px; font-weight:700;">Nome e Cognome *</label>\n'
        f'      <input type="text" id="m-nome" required style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff;" placeholder="Mario Rossi" />\n'
        f'    </div>\n'
        f'    <div>\n'
        f'      <label style="font-size:12px; color:#475569; display:block; margin-bottom:4px; font-weight:700;">Data di Nascita *</label>\n'
        f'      <input type="date" id="m-data-nascita" required style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff;" />\n'
        f'    </div>\n'
        f'    <div>\n'
        f'      <label style="font-size:12px; color:#475569; display:block; margin-bottom:4px; font-weight:700;">Luogo di Nascita *</label>\n'
        f'      <input type="text" id="m-luogo-nascita" required style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff;" placeholder="Es. Favara" />\n'
        f'    </div>\n'
        f'    <div>\n'
        f'      <label style="font-size:12px; color:#475569; display:block; margin-bottom:4px; font-weight:700;">Codice Fiscale *</label>\n'
        f'      <input type="text" id="m-cf" required style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff; text-transform:uppercase;" placeholder="RSSMRA80A01H501U" />\n'
        f'    </div>\n'
        f'    <div>\n'
        f'      <label style="font-size:12px; color:#475569; display:block; margin-bottom:4px; font-weight:700;">Telefono Cellulare *</label>\n'
        f'      <input type="tel" id="m-tel" required style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff;" placeholder="320 1234567" />\n'
        f'    </div>\n'
        f'    <div style="grid-column: span 2;">\n'
        f'      <label style="font-size:12px; color:#475569; display:block; margin-bottom:4px; font-weight:700;">Email *</label>\n'
        f'      <input type="email" id="m-email" required style="width:100%; padding:8px 12px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; background:#ffffff;" placeholder="mario.rossi@example.com" />\n'
        f'    </div>\n'
        f'    <div style="grid-column: span 2; margin-top:5px;">\n'
        f'      <button type="submit" style="width:100%; background:#25d366; color:#ffffff; border:0; padding:12px; border-radius:8px; font-weight:700; font-size:14px; cursor:pointer; display:flex; justify-content:center; align-items:center; gap:8px; box-shadow:0 4px 6px rgba(37,211,102,0.15);">\n'
        f'        💬 Sarebbe interessato a questo mutuo (Invia Dati via WhatsApp)\n'
        f'      </button>\n'
        f'    </div>\n'
        f'  </form>\n'
        f'  <script>\n'
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

    # 9. BOX CONTATTI STANDARD (SOTTO L'IMMOBILE) CON FORM OBBLIGATORIO INFO
    contact_box_html = (
        f'\n\n<div class="property-contact-box" style="background:linear-gradient(135deg, #1e293b, #0f172a); border-radius:20px; padding:25px; color:#ffffff; margin-bottom:25px; box-shadow:0 10px 25px rgba(0,0,0,0.15); font-family:\'Outfit\', sans-serif;">\n'
        f'  <h3 style="font-size:20px; color:#ffffff; margin-top:0; margin-bottom:8px; text-align:center;">📞 Richiedi Informazioni o Prenota una Visita</h3>\n'
        f'  <p style="color:#94a3b8; font-size:14px; text-align:center; margin-top:0; margin-bottom:20px;">Compila i dati richiesti per inoltrare la richiesta di appuntamento.</p>\n'
        f'  <form id="info-form" onsubmit="sendInfoRequest(event)" style="display:grid; grid-template-columns:1fr; gap:12px; color:#0f172a;">\n'
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
        f'    <div style="margin-top:5px;">\n'
        f'      <button type="submit" style="width:100%; background:#25d366; color:#ffffff; border:0; padding:12px; border-radius:8px; font-weight:700; font-size:14px; cursor:pointer; display:flex; justify-content:center; align-items:center; gap:8px; box-shadow:0 4px 6px rgba(37,211,102,0.15);">\n'
        f'        💬 Vorrei avere informazioni per questo immobile (Invia su WhatsApp)\n'
        f'      </button>\n'
        f'    </div>\n'
        f'  </form>\n'
        f'  <script>\n'
        f'    function sendInfoRequest(e) {{\n'
        f'      e.preventDefault();\n'
        f'      const nome = document.getElementById("i-nome").value;\n'
        f'      const tel = document.getElementById("i-tel").value;\n'
        f'      const email = document.getElementById("i-email").value || "Non fornita";\n'
        f'      const immobile = "{js_safe_title}";\n'
        f'      \n'
        f'      const text = `Salve, vorrei avere informazioni per questo immobile: "${{immobile}}".\\n\\nEcco i miei dati di contatto obbligatori:\\n- Nome e Cognome: ${{nome}}\\n- Telefono Cellulare: ${{tel}}\\n- Email: ${{email}}`;\n'
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
    
    # 10. Box Canali Social / Pagine Video
    social_channels_html = (
        '\n\n<div class="property-social-channels" style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:25px; text-align:center; font-family:\'Outfit\', sans-serif;">\n'
        '  <h4 style="font-size:16px; color:#0f172a; margin-top:0; margin-bottom:12px; font-weight:700;">📺 Segui i Nostri Canali Social e Video</h4>\n'
        '  <div style="display:flex; flex-wrap:wrap; gap:10px; justify-content:center;">\n'
        '    <a href="https://www.youtube.com/@immobiliaregiancani" target="_blank" style="background:#ff0000; color:#ffffff; text-decoration:none; padding:8px 16px; border-radius:20px; font-size:12px; font-weight:700; display:inline-flex; align-items:center; gap:6px;">📺 YouTube</a>\n'
        '    <a href="https://www.facebook.com/234931856561526" target="_blank" style="background:#1877f2; color:#ffffff; text-decoration:none; padding:8px 16px; border-radius:20px; font-size:12px; font-weight:700; display:inline-flex; align-items:center; gap:6px;">📘 Facebook</a>\n'
        '    <a href="https://www.instagram.com/immobiliaregiancani/" target="_blank" style="background:#e1306c; color:#ffffff; text-decoration:none; padding:8px 16px; border-radius:20px; font-size:12px; font-weight:700; display:inline-flex; align-items:center; gap:6px;">📸 Instagram</a>\n'
        '    <a href="https://www.threads.net/@immobiliaregiancani" target="_blank" style="background:#000000; color:#ffffff; text-decoration:none; padding:8px 16px; border-radius:20px; font-size:12px; font-weight:700; display:inline-flex; align-items:center; gap:6px;">🧵 Threads</a>\n'
        '    <a href="https://www.tiktok.com/@immobiliaregiancani" target="_blank" style="background:#010101; color:#ffffff; text-decoration:none; padding:8px 16px; border-radius:20px; font-size:12px; font-weight:700; display:inline-flex; align-items:center; gap:6px;">🎵 TikTok</a>\n'
        '  </div>\n'
        '</div>\n'
    )
    
    # 11. Costruisci galleria HTML
    gallery_html = "\n\n<h3>📸 Galleria Fotografica Immobile</h3>"
    gallery_html += '<div class="property-gallery-grid" style="display:grid; grid-template-columns:repeat(auto-fill, minmax(220px, 1fr)); gap:12px; margin-top:15px; margin-bottom:25px;">'
    for img_url in images_urls:
        gallery_html += f'<div style="overflow:hidden; border-radius:12px; border:1px solid #e2e8f0; aspect-ratio:1/1;"><img src="{img_url}" style="width:100%; height:100%; object-fit:cover; display:block;" /></div>'
    gallery_html += '</div>'
    
    # 12. Video YouTube incorporato
    video_id = ""
    if "youtube.com" in video_url or "youtu.be" in video_url:
        if "watch?v=" in video_url:
            video_id = video_url.split("watch?v=")[1].split("&")[0]
        elif "youtu.be/" in video_url:
            video_id = video_url.split("youtu.be/")[1].split("?")[0]
            
    video_html = ""
    if video_id:
        video_html = f'\n\n<h3>🎬 Video Visita Immobile</h3>\n<iframe width="100%" height="450" src="https://www.youtube.com/embed/{video_id}" frameborder="0" allowfullscreen style="border-radius:16px; box-shadow:0 10px 25px rgba(0,0,0,0.08); margin-bottom:25px;"></iframe>\n'
    
    # 13. Logo ufficiale di Immobiliare Giancani in fondo al post
    logo_html = (
        '\n\n<div class="property-footer-logo" style="text-align:center; margin-top:40px; padding-top:20px; border-top:1px solid #e2e8f0;">\n'
        '  <img src="https://www.immobiliaregiancani.it/wp-content/uploads/2025/12/cropped-casetta-330x180.png" alt="Immobiliare Giancani" style="max-width:180px; height:auto; margin:0 auto 10px auto; display:block;" />\n'
        '  <strong style="font-family:\'Outfit\', sans-serif; font-size:16px; color:#1e293b; display:block;">✨ Immobiliare Giancani</strong>\n'
        '</div>\n'
    )
    
    # Assembla contenuto finale in sequenza logica elegante
    full_content = f"{content}\n{ape_badge_html}\n{tech_sheet_html}\n{geo_desc_html}\n{map_html}\n{video_html}\n{gallery_html}\n{planimetry_html}\n{mortgage_calculator_html}\n{contact_box_html}\n{social_channels_html}\n{logo_html}"
    
    args = {
        "rest_base": "property",
        "item_id": 0,
        "title": title,
        "content": full_content,
        "status": "publish",
        "featured_media": featured_media_id
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
