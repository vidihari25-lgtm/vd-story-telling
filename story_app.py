# ==========================================
# 1. SUPER PATCH ANTIALIAS (WAJIB PALING ATAS)
# ==========================================
import os
import sys
import PIL.Image

# Paksa tambahkan ANTIALIAS agar tidak error
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
# ==========================================

import streamlit as st
import google.generativeai as genai
import json
import requests
import tempfile
import asyncio
import edge_tts
import re
import random
import time
import base64
import streamlit.components.v1 as components
from PIL import ImageDraw, ImageFont # Tambahan untuk Subtitle
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip

# --- KONFIGURASI HALAMAN ---
st.set_page_config(
    page_title="AI Director Pro (Auto DL)", 
    page_icon="🎬", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS (TEMA TERANG / LIGHT MODE) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .stApp { background-color: #ffffff !important; color: #1f2937 !important; }
    section[data-testid="stSidebar"] { background-color: #f8fafc !important; border-right: 1px solid #e2e8f0; }
    
    /* Paksa teks Sidebar Hitam */
    section[data-testid="stSidebar"] * { color: #1f2937 !important; }

    /* Input Field Putih */
    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
        background-color: #ffffff !important;
        color: #000000 !important;
        border: 1px solid #cbd5e1 !important;
    }
    
    /* Card Putih */
    div[data-testid="stExpander"], div[data-testid="stContainer"] {
        background-color: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        color: #1f2937;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    
    /* Tombol */
    div[data-testid="stButton"] > button[kind="primary"] {
        background: linear-gradient(90deg, #2563eb 0%, #4f46e5 100%);
        color: white !important;
        border: none;
    }

    .title-text {
        background: linear-gradient(135deg, #2563eb, #9333ea);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        font-size: 2.5rem;
    }
    
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# --- AMBIL API KEY ---
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    st.error("⚠️ EROR: `GEMINI_API_KEY` tidak ditemukan di secrets.toml!")
    st.stop()

ELEVENLABS_API_KEY = st.secrets.get("ELEVENLABS_API_KEY", None)
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", None)

# --- SESSION STATE ---
if 'generated_scenes' not in st.session_state: st.session_state['generated_scenes'] = []
if 'ai_images_data' not in st.session_state: st.session_state['ai_images_data'] = {}
if 'final_video_path' not in st.session_state: st.session_state['final_video_path'] = None

# --- FUNGSI AUTO DOWNLOAD (JS) ---
def trigger_auto_download(file_path):
    with open(file_path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode()
    md = f"""
        <a href="data:video/mp4;base64,{b64}" download="ai_story_video.mp4" id="download_link" style="display:none;">Download</a>
        <script>
            document.getElementById('download_link').click();
        </script>
    """
    components.html(md, height=0)

# --- FUNGSI BANTUAN SUBTITLE ---
def draw_subtitle(pil_img, text):
    draw = ImageDraw.Draw(pil_img)
    W, H = pil_img.size
    
    # Setup Font (Default basic font jika font sistem tidak ketemu)
    try:
        # Coba load font umum, ukuran disesuaikan resolusi
        font_size = int(H * 0.05) # 5% dari tinggi gambar
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
    
    # Wrap Text Sederhana
    margin = 40
    chars_per_line = int(W / (font_size * 0.6)) # Estimasi kasar
    lines = []
    words = text.split()
    current_line = []
    
    for word in words:
        current_line.append(word)
        if len(" ".join(current_line)) > chars_per_line:
            current_line.pop()
            lines.append(" ".join(current_line))
            current_line = [word]
    lines.append(" ".join(current_line))
    
    # Gambar Background & Teks
    text_height = len(lines) * (font_size + 10)
    bg_y1 = H - text_height - margin - 20
    bg_y2 = H - margin + 10
    
    # Semi-transparent black box
    overlay = PIL.Image.new('RGBA', pil_img.size, (0,0,0,0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle([(margin, bg_y1), (W-margin, bg_y2)], fill=(0,0,0,160))
    pil_img = PIL.Image.alpha_composite(pil_img.convert('RGBA'), overlay).convert('RGB')
    
    draw = ImageDraw.Draw(pil_img)
    y_text = bg_y1 + 10
    for line in lines:
        # Menengahkan teks (Metode manual karena getbbox berbeda tiap versi PIL)
        # Kita pakai rata kiri dengan margin saja agar aman
        draw.text((margin + 20, y_text), line, font=font, fill=(255, 255, 255))
        y_text += font_size + 5
        
    return pil_img

# --- FUNGSI LOGIKA ---
def extract_json(text):
    try:
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*$', '', text)
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match: return json.loads(match.group())
        return json.loads(text)
    except: return None

def generate_scenes_logic(api_key, input_text, input_mode, char_desc, target_scenes, language):
    genai.configure(api_key=api_key)
    
    lang_instruction = "Narration MUST be in Indonesian Language." if language == "Indonesia" else "Narration MUST be in English Language."
    
    prompt = f"""
    Role: Professional Movie Director.
    Task: Create a video script.
    Input Mode: {input_mode}.
    Story Context: '{input_text}'
    Characters: {char_desc}
    
    Requirement: 
    1. Create EXACTLY {target_scenes} scenes.
    2. {lang_instruction}
    
    OUTPUT FORMAT (JSON ARRAY ONLY):
    [
        {{
            "scene_number": 1,
            "narration": "Narration text here...",
            "image_prompt": "Cinematic shot of [Character], [Action], detailed background, 8k, photorealistic, bright lighting"
        }}
    ]
    """
    
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        response = model.generate_content(prompt)
        result = extract_json(response.text)
        if not result: return f"JSON Error. Raw: {response.text[:100]}..."
        return result
    except Exception as e:
        return f"API ERROR: {str(e)}"

def generate_image_pollinations(prompt):
    clean = requests.utils.quote(f"{prompt}, bright cinematic lighting, high quality")
    seed = random.randint(1, 99999)
    url = f"https://image.pollinations.ai/prompt/{clean}?width=1280&height=720&seed={seed}&nologo=true&model=flux"
    try:
        resp = requests.get(url, timeout=30)
        return resp.content if resp.status_code == 200 else None
    except: return None

# --- AUDIO HELPERS ---
async def edge_tts_generate(text, voice, output_file):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)

def generate_audio_openai(text, voice_name, api_key):
    url = "https://api.openai.com/v1/audio/speech"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {"model": "tts-1", "input": text, "voice": voice_name.lower()}
    try:
        r = requests.post(url, json=data, headers=headers)
        if r.status_code == 200:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(r.content)
                return f.name
        return None
    except: return None

def generate_audio_elevenlabs(text, voice_id, api_key):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    data = {"text": text, "model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 0.5}}
    try:
        r = requests.post(url, json=data, headers=headers)
        if r.status_code == 200:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(r.content)
                return f.name
        return None
    except: return None

def audio_manager(text, provider, selected_voice):
    if "Gratis" in provider:
        # Mapping suara berdasarkan gender dan bahasa (sederhana)
        if "Indonesia" in text or True: # Default Indonesia mapping
            voice_id = "id-ID-ArdiNeural" if "Ardi" in selected_voice else "id-ID-GadisNeural"
        
        try:
            temp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp.close()
            asyncio.run(edge_tts_generate(text, voice_id, temp.name))
            return temp.name
        except: return None
    elif "OpenAI" in provider:
        if not OPENAI_API_KEY: return None
        v_map = {"Cowok (Echo)": "echo", "Cowok (Onyx)": "onyx", "Cewek (Nova)": "nova", "Cewek (Shimmer)": "shimmer"}
        return generate_audio_openai(text, v_map.get(selected_voice, "alloy"), OPENAI_API_KEY)
    elif "ElevenLabs" in provider:
        if not ELEVENLABS_API_KEY: return None
        vid = "pNInz6obpgDQGcFmaJgB" if "Adam" in selected_voice else "21m00Tcm4TlvDq8ikWAM"
        return generate_audio_elevenlabs(text, vid, ELEVENLABS_API_KEY)

# --- VIDEO ENGINE (MODIFIED FOR SUBTITLES) ---
def create_final_video(assets, use_subtitle=False):
    clips = []
    log_box = st.empty()
    W, H = 1280, 720 
    
    for i, asset in enumerate(assets):
        try:
            log_box.info(f"⚙️ Mengolah Scene {i+1}...")
            
            # 1. Image Processing
            original_img = PIL.Image.open(asset['image'])
            if original_img.mode != 'RGB':
                original_img = original_img.convert('RGB')
            clean_img = original_img.resize((W, H), PIL.Image.LANCZOS)
            
            # === FITUR SUBTITLE OTOMATIS ===
            if use_subtitle and 'text' in asset:
                clean_img = draw_subtitle(clean_img, asset['text'])
            # ===============================
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                clean_img.save(f, quality=95)
                clean_path = f.name
            
            # 2. Audio Processing
            audio = AudioFileClip(asset['audio'])
            duration = audio.duration + 0.5
            
            # 3. Video Clip
            img_clip = ImageClip(clean_path).set_duration(duration)
            img_clip = img_clip.resize(lambda t: 1.1 - (0.005 * t)).set_position('center')
            
            final_clip = CompositeVideoClip([img_clip], size=(W, H)).set_audio(audio).set_fps(24)
            clips.append(final_clip)
        except Exception as e:
            st.warning(f"⚠️ Skip Scene {i+1}: {str(e)}")
            continue

    if not clips: return None
    try:
        log_box.info("🎞️ Rendering Final Video...")
        output_path = tempfile.mktemp(suffix=".mp4")
        final_video = concatenate_videoclips(clips, method="compose")
        final_video.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac', preset='ultrafast', threads=1, logger=None)
        log_box.success("✅ Selesai!")
        return output_path
    except Exception as e:
        st.error(f"❌ Render Error: {str(e)}")
        return None

# ================= UI UTAMA =================

# --- SIDEBAR ---
with st.sidebar:
    st.markdown("### 🎛️ Control Panel")
    
    # 1. BAHASA
    story_lang = st.selectbox("🌐 Bahasa Cerita (Language):", ["Indonesia", "English"])

    # 2. AUDIO
    with st.expander("🔊 Pengaturan Suara", expanded=True):
        tts_provider = st.radio("Provider:", ["Edge-TTS (Gratis)", "OpenAI (Pro)", "ElevenLabs (Ultra)"])
        
        voice_option = ""
        if "Gratis" in tts_provider:
            voice_option = st.selectbox("Model:", ["Cowok (Ardi)", "Cewek (Gadis)"])
        elif "OpenAI" in tts_provider:
            if not OPENAI_API_KEY: st.error("❌ Butuh OPENAI_API_KEY")
            voice_option = st.selectbox("Model:", ["Cowok (Echo)", "Cowok (Onyx)", "Cewek (Nova)", "Cewek (Shimmer)"])
        elif "ElevenLabs" in tts_provider:
            if not ELEVENLABS_API_KEY: st.error("❌ Butuh ELEVENLABS_API_KEY")
            voice_option = st.selectbox("Model:", ["Cowok (Adam)", "Cewek (Rachel)"])

    # 3. CONFIG SCENE & DOWNLOAD
    num_scenes = st.slider("Jumlah Scene:", 1, 30, 5)
    
    st.markdown("---")
    st.markdown("**Opsi Rendering:**")
    enable_subtitle = st.checkbox("📝 Tampilkan Subtitle Otomatis", value=True)
    auto_dl = st.checkbox("⬇️ Otomatis Download saat selesai", value=False)
    
    st.markdown("---")
    if st.button("🗑️ Reset Project", use_container_width=True):
        st.session_state['generated_scenes'] = []
        st.session_state['ai_images_data'] = {}
        st.session_state['final_video_path'] = None
        st.rerun()

# --- HEADER ---
st.markdown('<h1 class="title-text">AI Director Pro</h1>', unsafe_allow_html=True)

# --- HALAMAN 1: INPUT ---
if not st.session_state['generated_scenes']:
    
    tab1, tab2 = st.tabs(["🎭 Karakter", "📜 Cerita"])
    
    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            char1 = st.text_input("Tokoh Utama:", placeholder="Contoh: Budi, kemeja batik")
            char2 = st.text_input("Tokoh Pendukung:", placeholder="Contoh: Siti, kebaya merah")
        with c2:
            char_img = st.file_uploader("Upload Foto Tokoh (Opsional):", type=['jpg', 'png'])
            
    with tab2:
        mode = st.radio("Mode Cerita:", ["Judul Cerita", "Sinopsis", "Cerita Jadi"], horizontal=True)
        story = st.text_area("Isi Cerita:", height=200, placeholder="Tulis idemu disini...")

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("✨ Buat Skenario", type="primary", use_container_width=True):
        if story:
            with st.status("🤖 Sedang berpikir...", expanded=True) as status:
                st.write("Analisis karakter...")
                chars = f"Main: {char1}. Support: {char2}."
                
                st.write(f"Menulis naskah ({story_lang})...")
                res = generate_scenes_logic(GEMINI_API_KEY, story, mode, chars, num_scenes, story_lang)
                
                if isinstance(res, list):
                    st.session_state['generated_scenes'] = res
                    status.update(label="✅ Berhasil!", state="complete", expanded=False)
                    time.sleep(1)
                    st.rerun()
                else:
                    status.update(label="❌ Gagal!", state="error")
                    st.error(f"Error AI: {res}")
        else:
            st.warning("Cerita tidak boleh kosong.")

# --- HALAMAN 2: EDITOR ---
else:
    st.markdown(f"### 🎬 Editor ({len(st.session_state['generated_scenes'])} Scene)")
    
    for i, scene in enumerate(st.session_state['generated_scenes']):
        with st.container():
            cols = st.columns([0.2, 2, 1.5])
            with cols[0]:
                st.markdown(f"### {i+1}")
            with cols[1]:
                st.write(f"**Narasi:** {scene['narration']}")
                with st.expander("Prompt Gambar"):
                    st.code(scene['image_prompt'])
            with cols[2]:
                if st.button(f"🎲 Generate Gambar", key=f"gen_{i}", use_container_width=True):
                    with st.spinner("Menggambar..."):
                        data = generate_image_pollinations(scene['image_prompt'])
                        if data: st.session_state['ai_images_data'][i] = data
                
                uploaded = st.file_uploader("Atau Upload:", key=f"up_{i}", label_visibility="collapsed")
                
                if uploaded: 
                    # TAMPILAN GAMBAR LEBIH KECIL (HEMAT RUANG)
                    st.image(uploaded, width=250) 
                elif i in st.session_state['ai_images_data']: 
                    # TAMPILAN GAMBAR LEBIH KECIL (HEMAT RUANG)
                    st.image(st.session_state['ai_images_data'][i], width=250)
                else:
                    st.info("Belum ada gambar")
            st.divider()

    # RENDER SECTION
    if st.button("🚀 RENDER VIDEO FINAL", type="primary", use_container_width=True):
        if "Pro" in tts_provider and not OPENAI_API_KEY: st.error("Key OpenAI Kosong!"); st.stop()
        if "Ultra" in tts_provider and not ELEVENLABS_API_KEY: st.error("Key ElevenLabs Kosong!"); st.stop()

        assets = []
        last_img = None
        bar = st.progress(0)
        
        for idx, sc in enumerate(st.session_state['generated_scenes']):
            aud = audio_manager(sc['narration'], tts_provider, voice_option)
            if not aud: 
                st.error(f"Gagal membuat suara di Scene {idx+1}")
                st.stop()
            
            img = None
            if st.session_state.get(f"up_{idx}"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                    f.write(st.session_state[f"up_{idx}"].getbuffer())
                    img = f.name
            elif idx in st.session_state['ai_images_data']:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                    f.write(st.session_state['ai_images_data'][idx])
                    img = f.name
            
            if img: last_img = img
            elif last_img: img = last_img
            
            # Masukkan juga teks untuk subtitle
            if img and aud: 
                assets.append({
                    'image': img, 
                    'audio': aud, 
                    'text': sc['narration'] # Teks untuk subtitle
                })
            bar.progress((idx+1)/len(st.session_state['generated_scenes']))
        
        if assets:
            # Panggil fungsi video dengan opsi Subtitle
            vid_path = create_final_video(assets, use_subtitle=enable_subtitle)
            if vid_path:
                st.session_state['final_video_path'] = vid_path
                st.balloons()
                
                # JIKA AUTO DOWNLOAD DICENTANG
                if auto_dl:
                    trigger_auto_download(vid_path)
            else: st.error("Render Gagal.")
        else: st.warning("Tidak ada aset untuk dirender.")

    # DOWNLOAD MANUAL (SELALU ADA)
    if st.session_state['final_video_path'] and os.path.exists(st.session_state['final_video_path']):
        with st.container():
            st.success("✅ Video Siap!")
            st.video(st.session_state['final_video_path'])
            with open(st.session_state['final_video_path'], "rb") as f:
                st.download_button("⬇️ Download MP4 Manual", data=f, file_name="video.mp4", mime="video/mp4", type="primary", use_container_width=True)
