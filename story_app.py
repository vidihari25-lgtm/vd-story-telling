import streamlit as st
import google.generativeai as genai
import json
import requests
import time
import tempfile
import asyncio
import edge_tts
import re
import random
import os
from PIL import Image
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="AI Story Video Pro (Auto-Fill)", page_icon="🎬", layout="wide")

# --- AMBIL API KEY DARI SECRETS ---
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except FileNotFoundError:
    st.error("File `.streamlit/secrets.toml` tidak ditemukan! Harap buat file tersebut dan isi GEMINI_API_KEY.")
    st.stop()
except KeyError:
    st.error("Key `GEMINI_API_KEY` tidak ditemukan di secrets.toml!")
    st.stop()

# --- KONFIGURASI MODEL ---
MODEL_NAME = 'gemini-1.5-flash'
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# --- SESSION STATE ---
if 'generated_scenes' not in st.session_state:
    st.session_state['generated_scenes'] = []
if 'ai_images_data' not in st.session_state:
    st.session_state['ai_images_data'] = {} 

# --- FUNGSI BANTUAN ---
def extract_json(text):
    try:
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*$', '', text)
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match: return json.loads(match.group())
        return json.loads(text)
    except: return None

# --- FUNGSI 1: OTAK AI ---
def generate_scenes_logic(api_key, input_text, input_mode, char_desc, target_scenes):
    genai.configure(api_key=api_key)
    
    mode_instruction = ""
    if input_mode == "Judul Cerita":
        mode_instruction = f"Create a creative story based on title: '{input_text}'."
    elif input_mode == "Sinopsis":
        mode_instruction = f"Expand synopsis: '{input_text}'."
    elif input_mode == "Cerita Jadi":
        mode_instruction = f"Use this story exactly: '{input_text}'."

    prompt = f"""
    Act as Video Director.
    Mode: {input_mode}
    Character: "{char_desc}"
    Task: {mode_instruction}
    
    Create exactly {target_scenes} scenes.
    OUTPUT JSON ARRAY ONLY:
    [
        {{
            "scene_number": 1,
            "narration": "Indonesian narration...",
            "image_prompt": "Cinematic shot of {char_desc}, [action], [lighting], 8k, photorealistic"
        }}
    ]
    """
    try:
        model = genai.GenerativeModel(MODEL_NAME, safety_settings=SAFETY_SETTINGS)
        response = model.generate_content(prompt)
        return extract_json(response.text)
    except Exception as e:
        return None

# --- FUNGSI 2: GAMBAR ---
def generate_image_pollinations(prompt):
    clean_prompt = requests.utils.quote(prompt)
    seed = random.randint(1, 999999)
    url = f"https://image.pollinations.ai/prompt/{clean_prompt}?width=1280&height=720&seed={seed}&nologo=true&model=flux"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=60)
        if response.status_code == 200: return response.content
        return None
    except: return None

# --- FUNGSI 3: AUDIO ---
async def edge_tts_generate(text, voice, output_file):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)

def generate_audio_sync(text, gender):
    voice = "id-ID-ArdiNeural" if gender == "Cowok (Ardi)" else "id-ID-GadisNeural"
    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_file.close()
        asyncio.run(edge_tts_generate(text, voice, temp_file.name))
        return temp_file.name
    except: return None

# --- FUNGSI 4: VIDEO COMPOSITOR ---
def create_final_video(assets):
    clips = []
    for asset in assets:
        try:
            audio = AudioFileClip(asset['audio'])
            duration = audio.duration + 0.5 
            
            img_clip = ImageClip(asset['image']).set_duration(duration)
            # Zoom Out Effect (Smooth)
            img_clip = img_clip.resize(lambda t: 1.1 - (0.005 * t)) 
            img_clip = img_clip.set_position(('center', 'center'))
            img_clip = img_clip.set_fps(24)
            
            final_clip = CompositeVideoClip([img_clip], size=(1280, 720)).set_audio(audio)
            clips.append(final_clip)
        except Exception as e:
            print(f"Error Clip: {e}")

    if not clips: return None
    
    output_path = tempfile.mktemp(suffix=".mp4")
    # Menggunakan method compose tanpa padding agar cepat
    final_video = concatenate_videoclips(clips, method="compose") 
    final_video.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac', preset='ultrafast', threads=4, logger=None)
    return output_path

# ================= UI APLIKASI =================

st.sidebar.title("⚙️ Config")
# API KEY DISINI SUDAH DIHILANGKAN, DIAMBIL DARI SECRETS
voice_gender = st.sidebar.selectbox("Suara", ["Cowok (Ardi)", "Cewek (Gadis)"])
num_scenes = st.sidebar.slider("Jumlah Scene", 1, 100, 5)

if st.sidebar.button("🗑️ Reset Project"):
    st.session_state['generated_scenes'] = []
    st.session_state['ai_images_data'] = {}
    st.rerun()

st.title("🎬 AI Video Creator")
st.markdown("---")

# --- BAGIAN 1: SETUP ---
if not st.session_state['generated_scenes']:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.info("👤 **Karakter**")
        char_desc = st.text_area(
            "Deskripsi Visual Karakter:", 
            height=150,
            placeholder="Contoh: Seorang astronot wanita muda dengan baju luar angkasa putih berlogo merah, memegang helm kaca, rambut pendek hitam, latar belakang planet Mars."
        )
    with col2:
        st.info("📖 **Cerita**")
        mode = st.radio("Sumber:", ["Judul Cerita", "Sinopsis", "Cerita Jadi"], horizontal=True)
        
        placeholder_txt = ""
        if mode == "Judul Cerita": placeholder_txt = "Contoh: Misteri Hilangnya Kucing Kesayangan Firaun"
        elif mode == "Sinopsis": placeholder_txt = "Contoh: Di sebuah desa terpencil, hujan tidak pernah berhenti turun selama 100 tahun. Seorang anak bernama Budi menemukan payung ajaib..."
        else: placeholder_txt = "Tempelkan seluruh naskah cerita lengkap Anda di sini..."
        
        story = st.text_area("Input Teks:", height=150, placeholder=placeholder_txt)
    
    if st.button("📝 Buat Skenario", type="primary"):
        if GEMINI_API_KEY and story and char_desc:
            with st.spinner("Merancang Skenario..."):
                res = generate_scenes_logic(GEMINI_API_KEY, story, mode, char_desc, num_scenes)
                if res:
                    st.session_state['generated_scenes'] = res
                    st.rerun()
        else:
            st.warning("Mohon lengkapi Deskripsi Karakter dan Input Cerita!")

# --- BAGIAN 2: EDITOR SCENE ---
else:
    st.info("ℹ️ **Tips:** Jika scene tidak ada gambarnya, video akan otomatis menggunakan gambar dari scene sebelumnya.")
    
    with st.container():
        for i, scene in enumerate(st.session_state['generated_scenes']):
            with st.expander(f"Scene {scene['scene_number']}: {scene['narration'][:50]}...", expanded=True):
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1:
                    st.write(f"**Narasi:** {scene['narration']}")
                    st.markdown("**Prompt (Copy):**")
                    st.code(scene['image_prompt'], language="text")
                with c2:
                    st.markdown("**Sumber Gambar:**")
                    uploaded = st.file_uploader(f"Upload Img {i+1}", type=['jpg','png'], key=f"up_{i}")
                    st.write("--- ATAU ---")
                    if st.button(f"🎲 Generate AI Image (Scene {i+1})", key=f"btn_gen_{i}"):
                        with st.spinner("Generating..."):
                            img_data = generate_image_pollinations(scene['image_prompt'])
                            if img_data:
                                st.session_state['ai_images_data'][i] = img_data
                                st.success("Generated!")
                            else:
                                st.error("Gagal generate.")
                with c3:
                    st.markdown("**Preview:**")
                    if uploaded:
                        st.image(uploaded, use_container_width=True)
                    elif i in st.session_state['ai_images_data']:
                        st.image(st.session_state['ai_images_data'][i], use_container_width=True)
                    else:
                        st.warning("Belum ada gambar (Akan pakai scene sebelumnya)")

    st.divider()
    if st.button("🎥 RENDER VIDEO FINAL", type="primary", use_container_width=True):
        final_assets = []
        progress = st.progress(0)
        status = st.empty()
        
        last_valid_image_path = None # Variabel untuk menyimpan gambar terakhir
        
        total_scenes = len(st.session_state['generated_scenes'])
        
        for idx, scene_data in enumerate(st.session_state['generated_scenes']):
            status.text(f"Processing Scene {scene_data['scene_number']}...")
            
            # 1. Generate Audio
            audio_path = generate_audio_sync(scene_data['narration'], voice_gender)
            
            # 2. Tentukan Gambar
            current_img_path = None
            upload_key = f"up_{idx}"
            
            # Cek A: Apakah user upload?
            if st.session_state.get(upload_key):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                    f.write(st.session_state[upload_key].getbuffer())
                    current_img_path = f.name
            
            # Cek B: Apakah ada AI generated?
            elif idx in st.session_state['ai_images_data']:
                img_bytes = st.session_state['ai_images_data'][idx]
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                    f.write(img_bytes)
                    current_img_path = f.name
            
            # 3. LOGIKA FALLBACK (Pakai gambar sebelumnya jika kosong)
            final_img_path_for_scene = None
            
            if current_img_path:
                # Jika scene ini punya gambar, pakai ini dan simpan ke memori
                final_img_path_for_scene = current_img_path
                last_valid_image_path = current_img_path
            elif last_valid_image_path:
                # Jika scene ini kosong, tapi ada memori gambar sebelumnya, pakai itu
                final_img_path_for_scene = last_valid_image_path
            else:
                # Jika scene kosong DAN belum ada gambar sebelumnya (misal scene 1 kosong)
                # Maka terpaksa scene ini diskip (atau bisa pakai gambar hitam default jika mau)
                final_img_path_for_scene = None

            # 4. Masukkan ke aset jika valid
            if audio_path and final_img_path_for_scene:
                final_assets.append({"image": final_img_path_for_scene, "audio": audio_path})
            
            progress.progress((idx + 1) / total_scenes)
        
        if final_assets:
            status.text("Rendering video...")
            vid_path = create_final_video(final_assets)
            if vid_path:
                st.balloons()
                st.video(vid_path)
                with open(vid_path, "rb") as f:
                    st.download_button("⬇️ Download MP4", f, "final_story_full.mp4")
            else:
                st.error("Gagal render.")
        else:
            st.error("Gagal! Mohon setidaknya sediakan satu gambar pada Scene 1 agar bisa digunakan untuk scene berikutnya.")
