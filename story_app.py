# ==========================================
# 1. SUPER PATCH ANTIALIAS (WAJIB PALING ATAS)
# ==========================================
import os
import sys
import PIL.Image

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
import textwrap
import numpy as np
import streamlit.components.v1 as components
from PIL import ImageDraw, ImageFont 
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip

# --- KONFIGURASI HALAMAN ---
st.set_page_config(
    page_title="AI Director Pro (Fixed Border)", 
    page_icon="🎬", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS (TEMA TERANG MODERN) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background-color: #ffffff !important; color: #1f2937 !important; }
    section[data-testid="stSidebar"] { background-color: #f8fafc !important; border-right: 1px solid #e2e8f0; }
    section[data-testid="stSidebar"] * { color: #1f2937 !important; }
    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
        background-color: #ffffff !important; color: #000000 !important; border: 1px solid #cbd5e1 !important;
    }
    div[data-testid="stExpander"], div[data-testid="stContainer"] {
        background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 10px; color: #1f2937; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    div[data-testid="stButton"] > button[kind="primary"] {
        background: linear-gradient(90deg, #2563eb 0%, #4f46e5 100%); color: white !important; border: none;
    }
    .title-text {
        background: linear-gradient(135deg, #2563eb, #9333ea); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 800; font-size: 2.5rem;
    }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
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

# --- AUTO DOWNLOAD ---
def trigger_auto_download(file_path):
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode()
        md = f"""
            <a href="data:video/mp4;base64,{b64}" download="ai_story_video.mp4" id="download_link" style="display:none;">Download</a>
            <script>document.getElementById('download_link').click();</script>
        """
        components.html(md, height=0)
    except: pass

# --- FUNGSI SUBTITLE (BOX TIPIS & TRANSPARAN) ---
def create_subtitle_layer(text, width, height):
    try:
        subtitle_img = PIL.Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(subtitle_img)
        
        # 1. Cari Font
        font_path = None
        font_candidates = ["arialbd.ttf", "arial.ttf", "Roboto-Bold.ttf", "DejaVuSans-Bold.ttf"]
        for f_name in font_candidates:
            try:
                ImageFont.truetype(f_name, 20)
                font_path = f_name
                break
            except: continue
            
        # 2. LOGIKA AUTO-FIT (90% LEBAR)
        target_width = width * 0.90
        
        # Estimasi ukuran font
        estimated_font_size = int(target_width / (len(text) * 0.5))
        min_font_size = int(height * 0.03)
        max_font_size = int(height * 0.07)
        current_font_size = min(max(estimated_font_size, min_font_size), max_font_size)
        
        if font_path: font = ImageFont.truetype(font_path, current_font_size)
        else: font = ImageFont.load_default()
        
        # 3. WRAPPING
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
        except:
            text_w = len(text) * (current_font_size * 0.5)
            
        lines = []
        if text_w > target_width:
            avg_char_w = text_w / len(text)
            chars_per_line = int(target_width / avg_char_w)
            wrapper = textwrap.TextWrapper(width=chars_per_line, break_long_words=False)
            lines = wrapper.wrap(text)
        else:
            lines = [text]
            
        # 4. GAMBAR (POSISI BAWAH)
        line_spacing = current_font_size * 1.3
        total_text_height = len(lines) * line_spacing
        
        # Margin bawah 8%
        current_y = height - (height * 0.08) - total_text_height
        
        for line in lines:
            try:
                bbox = draw.textbbox((0, 0), line, font=font)
                line_w = bbox[2] - bbox[0]
                # line_h = bbox[3] - bbox[1] # Tidak dipakai agar konsisten
            except:
                line_w = len(line) * (current_font_size * 0.5)
            
            x_pos = (width - line_w) / 2
            
            # === PERBAIKAN BORDER/BOX ===
            padding_x = 10 
            padding_y = 4 # Lebih tipis vertikalnya
            
            # Hitung tinggi kotak background secara manual
            # Agar ekor huruf (g, y, j) tidak kepotong, kita tambah sedikit ruang di bawah
            # 'current_y' adalah bagian atas huruf kapital.
            box_top = current_y - padding_y
            box_bottom = current_y + current_font_size + (padding_y * 1.5) 
            
            draw.rectangle(
                [x_pos - padding_x, box_top, x_pos + line_w + padding_x, box_bottom],
                fill=(0, 0, 0, 85) # TRANSPARANSI: 0 (Bening) - 255 (Pekat). Diset 85 (Tipis).
            )
            
            # Teks Kuning
            draw.text((x_pos, current_y), line, font=font, fill="#FFD700")
            current_y += line_spacing
            
        return subtitle_img
        
    except Exception as e:
        print(f"Sub Error: {e}")
        return None

# --- AI LOGIC ---
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
    Story Context: '{input_text}' (Mode: {input_mode})
    Characters: {char_desc}
    
    Requirement: 
    1. Create EXACTLY {target_scenes} scenes.
    2. {lang_instruction}
    3. Keep narration concise (max 2 short sentences per scene).
    
    OUTPUT JSON ARRAY ONLY:
    [
        {{
            "scene_number": 1,
            "narration": "Narration text...",
            "image_prompt": "Cinematic shot of [Character], [Action], 8k, bright lighting, wide angle"
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
    clean = requests.utils.quote(f"{prompt}, bright cinematic lighting, masterpiece")
    seed = random.randint(1, 99999)
    url = f"https://image.pollinations.ai/prompt/{clean}?width=1280&height=720&seed={seed}&nologo=true&model=flux"
    try:
        resp = requests.get(url, timeout=30)
        return resp.content if resp.status_code == 200 else None
    except: return None

# --- AUDIO ---
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

# --- VIDEO ENGINE ---
def create_final_video(assets, use_subtitle=False):
    clips = []
    log_box = st.empty()
    W, H = 1280, 720 
    
    success_count = 0
    
    for i, asset in enumerate(assets):
        try:
            log_box.info(f"⚙️ Mengolah Scene {i+1}...")
            
            # 1. LAYER 1: Background Zoom
            original_img = PIL.Image.open(asset['image'])
            if original_img.mode != 'RGB':
                original_img = original_img.convert('RGB')
            clean_img = original_img.resize((W, H), PIL.Image.LANCZOS)
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                clean_img.save(f, quality=95)
                bg_path = f.name
            
            audio = AudioFileClip(asset['audio'])
            duration = audio.duration + 0.5
            
            bg_clip = ImageClip(bg_path).set_duration(duration)
            bg_clip = bg_clip.resize(lambda t: 1.0 + (0.005 * t))
            bg_clip = bg_clip.set_position('center')
            
            final_clip_layers = [bg_clip]
            
            # 2. LAYER 2: Subtitle (Static & Fixed Box)
            if use_subtitle and 'text' in asset:
                sub_img = create_subtitle_layer(asset['text'], W, H)
                if sub_img:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
                        sub_img.save(f, format="PNG")
                        sub_path = f.name
                    sub_clip = ImageClip(sub_path).set_duration(duration)
                    sub_clip = sub_clip.set_position('center')
                    final_clip_layers.append(sub_clip)
            
            final_composite = CompositeVideoClip(final_clip_layers, size=(W, H))
            final_composite = final_composite.set_audio(audio).set_fps(24)
            
            clips.append(final_composite)
            success_count += 1
            
        except Exception as e:
            st.error(f"❌ Gagal Scene {i+1}: {e}")
            continue

    if not clips: return None
    try:
        log_box.info(f"🎞️ Rendering Final Video ({success_count} scenes)...")
        output_path = tempfile.mktemp(suffix=".mp4")
        final_video = concatenate_videoclips(clips, method="compose")
        final_video.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac', preset='ultrafast', threads=1, logger=None)
        log_box.success("✅ Selesai!")
        return output_path
    except Exception as e:
        st.error(f"❌ Render Error: {str(e)}")
        return None

# ================= UI UTAMA =================

with st.sidebar:
    st.markdown("### 🎛️ Control Panel")
    story_lang = st.selectbox("🌐 Bahasa:", ["Indonesia", "English"])

    with st.expander("🔊 Audio", expanded=True):
        tts_provider = st.radio("Provider:", ["Edge-TTS (Gratis)", "OpenAI (Pro)", "ElevenLabs (Ultra)"])
        voice_option = ""
        if "Gratis" in tts_provider:
            voice_option = st.selectbox("Model:", ["Cowok (Ardi)", "Cewek (Gadis)"])
        elif "OpenAI" in tts_provider:
            if not OPENAI_API_KEY: st.error("❌ Need API Key")
            voice_option = st.selectbox("Model:", ["Cowok (Echo)", "Cowok (Onyx)", "Cewek (Nova)", "Cewek (Shimmer)"])
        elif "ElevenLabs" in tts_provider:
            if not ELEVENLABS_API_KEY: st.error("❌ Need API Key")
            voice_option = st.selectbox("Model:", ["Cowok (Adam)", "Cewek (Rachel)"])

    num_scenes = st.slider("Jumlah Scene:", 1, 30, 5)
    
    st.markdown("---")
    st.markdown("**Output Options:**")
    enable_subtitle = st.checkbox("📝 Subtitle (Transparan & Rapi)", value=True)
    auto_dl = st.checkbox("⬇️ Auto-Download Selesai Render", value=True)
    
    st.markdown("---")
    if st.button("🗑️ Reset", use_container_width=True):
        st.session_state['generated_scenes'] = []
        st.session_state['ai_images_data'] = {}
        st.session_state['final_video_path'] = None
        st.rerun()

st.markdown('<h1 class="title-text">AI Director Pro</h1>', unsafe_allow_html=True)

# INPUT
if not st.session_state['generated_scenes']:
    tab1, tab2 = st.tabs(["🎭 Karakter", "📜 Cerita"])
    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            char1 = st.text_input("Tokoh 1:", placeholder="Nama & Ciri")
            char2 = st.text_input("Tokoh 2:", placeholder="Nama & Ciri")
        with c2:
            char_img = st.file_uploader("Upload Foto:", type=['jpg', 'png'])
    with tab2:
        mode = st.radio("Mode:", ["Judul Cerita", "Sinopsis", "Cerita Jadi"], horizontal=True)
        story = st.text_area("Konten:", height=200, placeholder="...")

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("✨ Buat Skenario", type="primary", use_container_width=True):
        if story:
            with st.status("🤖 AI Bekerja...", expanded=True) as status:
                st.write("Menulis naskah...")
                chars = f"Main: {char1}. Support: {char2}."
                res = generate_scenes_logic(GEMINI_API_KEY, story, mode, chars, num_scenes, story_lang)
                if isinstance(res, list):
                    st.session_state['generated_scenes'] = res
                    status.update(label="✅ Siap!", state="complete", expanded=False)
                    time.sleep(1)
                    st.rerun()
                else:
                    status.update(label="❌ Gagal", state="error")
                    st.error(res)
        else: st.warning("Isi cerita dulu.")

# EDITOR
else:
    st.markdown(f"### 🎬 Editor ({len(st.session_state['generated_scenes'])})")
    
    for i, scene in enumerate(st.session_state['generated_scenes']):
        with st.container():
            cols = st.columns([0.2, 2, 1.5])
            with cols[0]: st.markdown(f"### {i+1}")
            with cols[1]:
                st.write(f"**Narasi:** {scene['narration']}")
                with st.expander("Prompt"): st.code(scene['image_prompt'])
            with cols[2]:
                if st.button(f"🎲 Generate", key=f"gen_{i}", use_container_width=True):
                    with st.spinner("..."):
                        data = generate_image_pollinations(scene['image_prompt'])
                        if data: st.session_state['ai_images_data'][i] = data
                uploaded = st.file_uploader("Upload", key=f"up_{i}", label_visibility="collapsed")
                
                if uploaded: st.image(uploaded, width=250)
                elif i in st.session_state['ai_images_data']: st.image(st.session_state['ai_images_data'][i], width=250)
                else: st.info("Kosong")
            st.divider()

    if st.button("🚀 RENDER VIDEO", type="primary", use_container_width=True):
        if "Pro" in tts_provider and not OPENAI_API_KEY: st.error("Need OpenAI Key"); st.stop()
        if "Ultra" in tts_provider and not ELEVENLABS_API_KEY: st.error("Need ElevenLabs Key"); st.stop()

        assets = []
        last_img = None
        bar = st.progress(0)
        
        for idx, sc in enumerate(st.session_state['generated_scenes']):
            aud = audio_manager(sc['narration'], tts_provider, voice_option)
            if not aud: st.error(f"Audio Error Scene {idx+1}"); st.stop()
            
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
            
            if img and aud: assets.append({'image':img, 'audio':aud, 'text': sc['narration']})
            bar.progress((idx+1)/len(st.session_state['generated_scenes']))
        
        if assets:
            vid_path = create_final_video(assets, use_subtitle=enable_subtitle)
            if vid_path:
                st.session_state['final_video_path'] = vid_path
                st.balloons()
                if auto_dl: trigger_auto_download(vid_path)
            else: st.error("Render Gagal.")
        else: st.warning("Aset kosong.")

    if st.session_state['final_video_path'] and os.path.exists(st.session_state['final_video_path']):
        with st.container():
            st.success("✅ Video Selesai!")
            st.video(st.session_state['final_video_path'])
            with open(st.session_state['final_video_path'], "rb") as f:
                st.download_button("⬇️ Download Manual", data=f, file_name="video.mp4", mime="video/mp4", type="primary", use_container_width=True)
