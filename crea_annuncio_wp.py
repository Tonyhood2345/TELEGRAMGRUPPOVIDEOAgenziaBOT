import os
import sys
import json
import base64
import subprocess
import requests

# === RECUPERO CONFIGURAZIONI DA VARIABILI D'AMBIENTE ===
WP_URL = os.environ.get("WP_URL", "https://www.immobiliaregiancani.it/wp-json/easy-mcp-ai/v1/mcp")
WP_TOKEN = os.environ.get("WP_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama3-70b-8192")

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
        # Chiamata POST all'endpoint unico dell'MCP
        res = requests.post("https://www.immobiliaregiancani.it/wp-json/easy-mcp-ai/v1/mcp", headers=headers, json=payload, verify=False)
        if res.status_code == 200:
            res_json = res.json()
            if 'result' in res_json and 'content' in res_json['result']:
                text_data = res_json['result']['content'][0]['text']
                # Se è un errore del server MCP
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
    """Estrae num_frames fotogrammi in HD (1920x1080) ad alta qualità a intervalli regolari."""
    duration = get_video_duration(video_path)
    if duration <= 0:
        print("Impossibile determinare la durata del video, estrazione fallita.")
        return []
    
    interval = duration / (num_frames + 1)
    extracted_files = []
    
    print(f"Durata video: {duration} secondi. Estrazione di {num_frames} fotogrammi a intervalli di {interval:.2f}s...")
    
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

def optimize_description_with_groq(original_title, original_desc):
    """Usa Groq LLM per riscrivere e ottimizzare la descrizione per SEO e GEO."""
    if not GROQ_API_KEY:
        print("Salto ottimizzazione Groq (Chiave mancante).")
        return f"{original_title}\n\n{original_desc}\n\n✨ Immobiliare Giancani"
        
    print("Ottimizzazione testo con Groq...")
    
    prompt_system = (
        "Sei un copywriter professionista nel settore immobiliare italiano d'élite. "
        "Lavori per Immobiliare Giancani. Il tuo compito è ottimizzare la descrizione "
        "di un annuncio immobiliare per la ricerca SEO e GEO locale (specializzandoti su Favara, Agrigento e provincia in Sicilia). "
        "Riscrivi il testo in modo irresistibile per i clienti, usa parole chiave come 'appartamento in vendita', 'casa con giardino', "
        "'investimento Favara', inserisci emoticon ed elenchi puntati per facilitare la lettura. "
        "IMPORTANTE: Ogni output generato deve SEMPRE terminare mettendo in risalto la firma '✨ Immobiliare Giancani' "
        "in fondo con spaziatura doppia. Il nome 'Antonio' NON deve comparire da nessuna parte del testo."
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
    """Crea l'annuncio CPT property in WordPress con galleria immagini, video, dettagli GEO, contatti e planimetria via MCP."""
    print("Creazione dell'annuncio su WordPress via MCP...")
    
    # 1. Estrae classe energetica (APE) dal testo se presente, altrimenti default "E"
    ape_class = "E"
    content_lower = content.lower()
    for letter in ["a", "b", "c", "d", "e", "f", "g"]:
        if f"classe {letter}" in content_lower or f"classe energetica {letter}" in content_lower:
            ape_class = letter.upper()
            break
            
    # 2. Costruisci il box delle caratteristiche tecniche (APE, ecc.)
    tech_sheet_html = (
        '\n\n<div class="property-tech-sheet" style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-top:25px; margin-bottom:25px;">\n'
        '  <h3 style="font-family:\'Outfit\', sans-serif; font-size:20px; color:#0f172a; margin-top:0; margin-bottom:15px; border-bottom:2px solid #e2e8f0; padding-bottom:8px;">📋 Scheda Tecnica e Prestazioni</h3>\n'
        '  <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:15px;">\n'
        '    <div><span style="color:#64748b; font-size:13px; display:block;">Classe Energetica (APE)</span>'
        f'         <strong style="font-size:16px; color:#1e293b;">Classe {ape_class}</strong></div>\n'
        '    <div><span style="color:#64748b; font-size:13px; display:block;">Stato Immobile</span>'
        '         <strong style="font-size:16px; color:#1e293b;">Selezionato / Nuova Proposta</strong></div>\n'
        '    <div><span style="color:#64748b; font-size:13px; display:block;">Localizzazione</span>'
        '         <strong style="font-size:16px; color:#1e293b;">Favara (Agrigento)</strong></div>\n'
        '    <div><span style="color:#64748b; font-size:13px; display:block;">Sito Agenzia</span>'
        '         <strong style="font-size:16px; color:#1e293b;">Immobiliare Giancani</strong></div>\n'
        '  </div>\n'
        '</div>\n'
    )
    
    # 3. Costruisci la descrizione GEO di Favara
    geo_desc_html = (
        '\n\n<div class="property-geo-desc" style="background:#f1f5f9; border-radius:16px; padding:20px; margin-bottom:25px;">\n'
        '  <h4 style="font-family:\'Outfit\', sans-serif; font-size:18px; color:#0f172a; margin-top:0; margin-bottom:10px;">📍 Vivere a Favara: Qualità e Collegamenti</h4>\n'
        '  <p style="color:#334155; font-size:14px; line-height:1.6; margin:0;">\n'
        '    Favara si trova in una posizione geografica e logistica di assoluto rilievo, a pochissimi minuti dalla rinomata Valle dei Templi di Agrigento e dalle spettacolari spiagge della costa siciliana. Celebre a livello internazionale per il <strong>Farm Cultural Park</strong>, un centro d\'arte indipendente che ha rigenerato il centro storico, Favara offre oggi un tenore di vita accogliente e un eccezionale dinamismo culturale. È una cittadina ideale per chi cerca una qualità della vita originale, ritmi a misura d\'uomo, una ricca tradizione enogastronomica e la comodità di vivere vicini ai principali snodi commerciali e turistici della Sicilia meridionale.\n'
        '  </p>\n'
        '</div>\n'
    )
    
    # 4. Spazio Planimetria
    planimetry_html = (
        '\n\n<div class="property-planimetry-section" style="margin-bottom:25px; padding:25px; border:2px dashed #cbd5e1; border-radius:16px; background:#f8fafc; text-align:center;">\n'
        '  <span style="font-size:36px; display:block; margin-bottom:8px;">📐</span>\n'
        '  <h4 style="font-family:\'Outfit\', sans-serif; font-size:18px; color:#1e293b; margin-top:0; margin-bottom:5px;">Spazio Planimetria dell\'Immobile</h4>\n'
        '  <p style="color:#64748b; font-size:13px; margin:0 0 15px 0;">La planimetria catastale di questa proprietà è a disposizione dei nostri clienti per la consultazione dei dettagli tecnici e la distribuzione degli spazi.</p>\n'
        '  <span style="display:inline-block; background:#64748b; color:#ffffff; padding:6px 14px; font-size:12px; font-weight:700; border-radius:30px; text-transform:uppercase; letter-spacing:0.5px;">Disponibile su Richiesta</span>\n'
        '</div>\n'
    )
    
    # 5. Box Richiesta Informazioni e Contatti (WhatsApp, Telegram, Call)
    contact_box_html = (
        '\n\n<div class="property-contact-box" style="background:linear-gradient(135deg, #1e293b, #0f172a); border-radius:20px; padding:25px; color:#ffffff; margin-bottom:30px; box-shadow:0 10px 25px rgba(0,0,0,0.15);">\n'
        '  <h3 style="font-family:\'Outfit\', sans-serif; font-size:20px; color:#ffffff; margin-top:0; margin-bottom:8px; text-align:center;">📞 Richiedi Informazioni o Prenota una Visita</h3>\n'
        '  <p style="color:#94a3b8; font-size:14px; text-align:center; margin-top:0; margin-bottom:20px;">I consulenti di Immobiliare Giancani sono a tua completa disposizione per fornirti tutti i dettagli.</p>\n'
        '  <div style="display:flex; flex-wrap:wrap; gap:12px; justify-content:center; margin-bottom:20px;">\n'
        '    <a href="https://wa.me/393505902923" target="_blank" style="background:#25d366; color:#ffffff; text-decoration:none; padding:10px 20px; border-radius:30px; font-weight:700; font-size:14px; display:inline-flex; align-items:center; gap:8px; transition:transform 0.2s;" onmouseover="this.style.transform=\'scale(1.05)\'" onmouseout="this.style.transform=\'scale(1)\'">💬 WhatsApp</a>\n'
        '    <a href="https://t.me/ImmobiliareGiancaniBot" target="_blank" style="background:#0088cc; color:#ffffff; text-decoration:none; padding:10px 20px; border-radius:30px; font-weight:700; font-size:14px; display:inline-flex; align-items:center; gap:8px; transition:transform 0.2s;" onmouseover="this.style.transform=\'scale(1.05)\'" onmouseout="this.style.transform=\'scale(1)\'">✈️ Telegram</a>\n'
        '    <a href="tel:+393201667156" style="background:#3b82f6; color:#ffffff; text-decoration:none; padding:10px 20px; border-radius:30px; font-weight:700; font-size:14px; display:inline-flex; align-items:center; gap:8px; transition:transform 0.2s;" onmouseover="this.style.transform=\'scale(1.05)\'" onmouseout="this.style.transform=\'scale(1)\'">📞 Chiama Ora</a>\n'
        '  </div>\n'
        '  <div style="text-align:center; font-size:13px; color:#cbd5e1; border-top:1px solid rgba(255,255,255,0.1); padding-top:15px;">\n'
        '    📍 <strong>Sede Agenzia:</strong> Corso Vittorio Veneto 151, Favara (AG)\n'
        '  </div>\n'
        '</div>\n'
    )
    
    # 6. Costruisci galleria HTML
    gallery_html = "\n\n<h3>📸 Galleria Fotografica Immobile</h3>"
    gallery_html += '<div class="property-gallery-grid" style="display:grid; grid-template-columns:repeat(auto-fill, minmax(220px, 1fr)); gap:12px; margin-top:15px; margin-bottom:25px;">'
    for img_url in images_urls:
        gallery_html += f'<div style="overflow:hidden; border-radius:12px; border:1px solid #e2e8f0; aspect-ratio:1/1;"><img src="{img_url}" style="width:100%; height:100%; object-fit:cover; display:block;" /></div>'
    gallery_html += '</div>'
    
    # 7. Video YouTube incorporato
    video_id = ""
    if "youtube.com" in video_url or "youtu.be" in video_url:
        if "watch?v=" in video_url:
            video_id = video_url.split("watch?v=")[1].split("&")[0]
        elif "youtu.be/" in video_url:
            video_id = video_url.split("youtu.be/")[1].split("?")[0]
            
    video_html = ""
    if video_id:
        video_html = f'\n\n<h3>🎬 Video Visita Immobile</h3>\n<iframe width="100%" height="450" src="https://www.youtube.com/embed/{video_id}" frameborder="0" allowfullscreen style="border-radius:16px; box-shadow:0 10px 25px rgba(0,0,0,0.08); margin-bottom:25px;"></iframe>\n'
    
    # 8. Logo ufficiale di Immobiliare Giancani in fondo al post
    logo_html = (
        '\n\n<div class="property-footer-logo" style="text-align:center; margin-top:40px; padding-top:20px; border-top:1px solid #e2e8f0;">\n'
        '  <img src="https://www.immobiliaregiancani.it/wp-content/uploads/2025/12/cropped-casetta-330x180.png" alt="Immobiliare Giancani" style="max-width:180px; height:auto; margin:0 auto 10px auto; display:block;" />\n'
        '  <strong style="font-family:\'Outfit\', sans-serif; font-size:16px; color:#1e293b; display:block;">✨ Immobiliare Giancani</strong>\n'
        '</div>\n'
    )
    
    # Assembla contenuto
    full_content = f"{content}\n{tech_sheet_html}\n{geo_desc_html}\n{video_html}\n{gallery_html}\n{planimetry_html}\n{contact_box_html}\n{logo_html}"
    
    args = {
        "rest_base": "property",
        "item_id": 0,  # non necessario per la creazione, ma alcuni tool lo richiedono, passiamo 0
        "title": title,
        "content": full_content,
        "status": "publish",
        "featured_media": featured_media_id
    }
    
    # In CPT creation su wp_create_cpt_item
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
    
    # 1. Download Video (se non è già un link mp4 pre-caricato)
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
    
    # 3. Ottimizza descrizione con Groq
    optimized_text = optimize_description_with_groq(orig_title, orig_desc)
    
    # 4. Estrazione fotogrammi HD
    photo_files = extract_frames(video_filename, num_frames=18)
    
    if not photo_files:
        print("Estrazione fotogrammi fallita.")
        return
        
    # 5. Caricamento immagini su WordPress via MCP
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
    
    # 6. Crea l'annuncio property su WordPress via MCP
    wp_listing_link = create_wp_listing(orig_title, optimized_text, featured_id, media_urls, video_url)
    
    # 7. Pulizia file temporanei
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
