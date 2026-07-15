import os
import sys
import json
import base64
import subprocess
import requests

# === RECUPERO CONFIGURAZIONI DA VARIABILI D'AMBIENTE (SICUREZZA) ===
WP_URL = os.environ.get("WP_URL", "https://www.immobiliaregiancani.it/wp-json/wp/v2")
WP_TOKEN = os.environ.get("WP_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-70b-versatile")

# Verifiche di sicurezza iniziali
if not WP_TOKEN:
    print("ATTENZIONE: Variabile d'ambiente WP_TOKEN non definita. Il caricamento su WordPress fallirà.")
if not GROQ_API_KEY:
    print("ATTENZIONE: Variabile d'ambiente GROQ_API_KEY non definita. L'ottimizzazione con Groq LLM fallirà.")

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
        # Estrae un singolo frame alla posizione timestamp in risoluzione 1920x1080 con qualità eccellente (-q:v 2)
        cmd = f'ffmpeg -y -ss {timestamp:.2f} -i "{video_path}" -vframes 1 -q:v 2 -s 1920x1080 "{out_filename}"'
        run_command(cmd)
        if os.path.exists(out_filename) and os.path.getsize(out_filename) > 0:
            extracted_files.append(out_filename)
        else:
            print(f"Errore estrazione fotogramma al secondo {timestamp:.2f}")
            
    return extracted_files

def get_video_metadata(video_url):
    """Ottiene descrizione e titolo originali del video da YouTube."""
    print("Estrazione metadata da YouTube...")
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
    """Carica un file immagine su WordPress Media Library via REST API."""
    if not WP_TOKEN:
        print("Salto caricamento foto (Token WP mancante).")
        return None, None
        
    url = f"{WP_URL}/media"
    headers = {
        "Authorization": f"Bearer {WP_TOKEN}",
        "Content-Disposition": f'attachment; filename="{os.path.basename(photo_path)}"',
        "Content-Type": "image/jpeg"
    }
    
    try:
        with open(photo_path, "rb") as f:
            image_data = f.read()
        res = requests.post(url, headers=headers, data=image_data, verify=False)
        if res.status_code in [200, 201]:
            res_json = res.json()
            return res_json['id'], res_json['source_url']
        else:
            print(f"Errore caricamento media WP ({res.status_code}): {res.text}")
            return None, None
    except Exception as e:
        print("Errore upload foto:", str(e))
        return None, None

def create_wp_listing(title, content, featured_media_id, images_urls, video_url):
    """Crea l'annuncio CPT property in WordPress con galleria immagini e video incorporato."""
    if not WP_TOKEN:
        print("Salto creazione annuncio (Token WP mancante).")
        return None
        
    print("Creazione dell'annuncio su WordPress...")
    url = f"{WP_URL}/property"
    headers = {
        "Authorization": f"Bearer {WP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Costruisci galleria HTML in fondo all'annuncio
    gallery_html = "\n\n<h3>📸 Galleria Fotografica Immobile</h3>"
    gallery_html += '<div class="property-gallery-grid" style="display:grid; grid-template-columns:repeat(auto-fill, minmax(220px, 1fr)); gap:12px; margin-top:15px; margin-bottom:25px;">'
    for img_url in images_urls:
        gallery_html += f'<div style="overflow:hidden; border-radius:12px; border:1px solid #e2e8f0;"><img src="{img_url}" style="width:100%; height:150px; object-fit:cover;" /></div>'
    gallery_html += '</div>'
    
    # Estrae video ID se è un link YouTube
    video_id = ""
    if "youtube.com" in video_url or "youtu.be" in video_url:
        if "watch?v=" in video_url:
            video_id = video_url.split("watch?v=")[1].split("&")[0]
        elif "youtu.be/" in video_url:
            video_id = video_url.split("youtu.be/")[1].split("?")[0]
            
    video_html = ""
    if video_id:
        video_html = f'\n\n<h3>🎬 Video Visita Immobile</h3>\n<iframe width="100%" height="450" src="https://www.youtube.com/embed/{video_id}" frameborder="0" allowfullscreen style="border-radius:16px; box-shadow:0 10px 25px rgba(0,0,0,0.08);"></iframe>\n'
    
    full_content = f"{content}\n{video_html}\n{gallery_html}"
    
    payload = {
        "title": title,
        "content": full_content,
        "status": "publish",
        "featured_media": featured_media_id
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload, verify=False)
        if res.status_code in [200, 201]:
            res_json = res.json()
            return res_json['link']
        else:
            print(f"Errore creazione post WP ({res.status_code}): {res.text}")
            return None
    except Exception as e:
        print("Errore creazione annuncio WP:", str(e))
        return None

def main():
    if len(sys.argv) < 2:
        print("Uso: python crea_annuncio_wp.py <URL_VIDEO_YOUTUBE>")
        # Di default per il test di 1 annuncio ne mettiamo uno se non fornito
        video_url = "https://www.youtube.com/watch?v=Cq0wg0_OeGg"
    else:
        video_url = sys.argv[1]
        
    print(f"=== PIPELINE CREAZIONE ANNUNCIO DA VIDEO: {video_url} ===")
    
    # 1. Download Video
    print("Download video temporaneo...")
    video_filename = "video_annuncio_temp.mp4"
    # Scarica in bassa/media qualità per velocizzare l'elaborazione (es. 720p max)
    download_cmd = f'yt-dlp -f "best[height<=720]" -o "{video_filename}" "{video_url}"'
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
        
    # 5. Caricamento immagini su WordPress
    media_ids = []
    media_urls = []
    print(f"Caricamento di {len(photo_files)} immagini su WordPress...")
    for idx, photo in enumerate(photo_files):
        print(f"Caricamento {idx+1}/{len(photo_files)}: {photo}")
        m_id, m_url = upload_photo_to_wp(photo)
        if m_id and m_url:
            media_ids.append(m_id)
            media_urls.append(m_url)
            
    if not media_ids:
        print("Nessuna immagine caricata su WordPress, impossibile continuare.")
        return
        
    # La prima foto estratta sarà la Featured Image
    featured_id = media_ids[0]
    
    # 6. Crea l'annuncio property su WordPress
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
