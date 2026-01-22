import streamlit as st

# === FIX BUG ANTIALIAS (WAJIB DI PALING ATAS) ===
import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
# ================================================

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
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="AI Story Video Pro (Download Fix)", page_icon="🛡️", layout="wide")

# --- AMBIL API KEY DARI SECRETS ---
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except FileNotFoundError:
    st.error("⚠️ File `.streamlit/secrets.toml` belum dibuat!")
    st.stop()
except KeyError:
    st.error("⚠️ Key `GEMINI_API_KEY` tidak ditemukan di secrets!")
    st.stop()

# --- SESSION STATE (Memori Agar Data Tidak Hilang) ---
if 'generated_scenes' not in st.session_state: st.session_state['generated_scenes'] = []
if 'ai_images_data' not in st.session_state: st.session_state['ai_images_data'] = {}
# TAMBAHAN BARU: Simpan path video final di sini
if 'final_video_path' not in st.session_state: st.session_state['final_video_path'] = None

# --- FUNGSI BANTUAN ---
def extract_json(text):
    try:
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*$', '', text)
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match: return json.loads(match.group())
        return json.loads(text)
    except: return None

# --- FUNGSI 1: AI SCENARIO ---
def generate_scenes_logic(api_key, input_text, input_mode, char_desc, target_scenes):
    genai.configure(api_key=api_key)
    mode_instruction = ""
    if input_mode == "Judul Cerita": mode_instruction = f"Story from title: '{input_text}'."
    elif input_mode == "Sinopsis": mode_instruction = f"Expand synopsis: '{input_text}'."
    elif input_mode == "Cerita Jadi": mode_instruction = f"Use exactly: '{input_text}'."

    prompt = f"""
    Act as Video Director. Mode: {input_mode}. Character: "{char_desc}". Task: {mode_instruction}.
    Create exactly {target_scenes} scenes.
    OUTPUT JSON ARRAY ONLY:
    [{{"scene_number": 1, "narration": "Indonesian narration...", "image_prompt": "Cinematic shot of {char_desc}, [action], 8k"}}]
    """
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        response = model.generate_content(prompt)
        return extract_json(response.text)
    except: return None

# --- FUNGSI 2: GAMBAR ---
def generate_image_pollinations(prompt):
    clean = requests.utils.quote(prompt)
    seed = random.randint(1, 99999)
    url = f"https://image.pollinations.ai/prompt/{clean}?width=1280&height=720&seed={seed}&nologo=true&model=flux"
    try:
        resp = requests.get(url, timeout=60)
        return resp.content if resp.status_code == 200 else None
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

# --- FUNGSI 4: VIDEO ENGINE (ANTI-CRASH) ---
def create_final_video(assets):
    clips = []
    log_box = st.empty()
    W, H = 1280, 720 
    
    for i, asset in enumerate(assets):
        try:
            log_box.info(f"⚙️ Memproses Clip {i+1} dari {len(assets)}...")
            
            # Load & Sanitasi Gambar
            original_img = PIL.Image.open(asset['image'])
            if original_img.mode != 'RGB':
                original_img = original_img.convert('RGB')
            
            clean_img = original_img.resize((W, H), PIL.Image.LANCZOS)
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                clean_img.save(f, quality=95)
                clean_img_path = f.name
            
            # Setup Audio & Video
            audio = AudioFileClip(asset['audio'])
            duration = audio.duration + 0.5
            
            img_clip = ImageClip(clean_img_path).set_duration(duration)
            img_clip = img_clip.resize(lambda t: 1.1 - (0.005 * t))
            img_clip = img_clip.set_position('center')
            
            final_clip = CompositeVideoClip([img_clip], size=(W, H))
            final_clip = final_clip.set_audio(audio)
            final_clip = final_clip.set_fps(24)
            clips.append(final_clip)
            
        except Exception as e:
            st.error(f"❌ Error Scene {i+1}: {str(e)}")
            continue

    if not clips: return None
        
    try:
        log_box.info("🎞️ Rendering Final...")
        output_path = tempfile.mktemp(suffix=".mp4")
        final_video = concatenate_videoclips(clips, method="compose")
        final_video.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac', preset='ultrafast', threads=1, logger=None)
        log_box.success("✅ Selesai!")
        return output_path
    except Exception as e:
        st.error(f"❌ Error Render: {str(e)}")
        return None

# ================= UI APLIKASI =================

st.sidebar.title("⚙️ Pengaturan")
voice_gender = st.sidebar.selectbox("Suara", ["Cowok (Ardi)", "Cewek (Gadis)"])
num_scenes = st.sidebar.slider("Jumlah Scene", 1, 100, 5)

if st.sidebar.button("🗑️ Reset Baru"):
    # Reset semua session state
    st.session_state['generated_scenes'] = []
    st.session_state['ai_images_data'] = {}
    st.session_state['final_video_path'] = None # Reset video juga
    st.rerun()

st.title("🎬 AI Video Maker (Download Ready)")
st.markdown("---")

# INPUT SECTION
if not st.session_state['generated_scenes']:
    c1, c2 = st.columns([1, 2])
    with c1:
        st.info("Karakter")
        char_desc = st.text_area(
            "Deskripsi:", 
            height=200, 
            placeholder="Contoh:\nSeorang astronot muda, wanita, rambut pendek pink, memakai baju luar angkasa putih kotor, wajah penuh debu."
        )
    with c2:
        st.info("Cerita")
        mode = st.radio("Mode:", ["Judul Cerita", "Sinopsis", "Cerita Jadi"], horizontal=True)
        placeholder_text = ""
        if mode == "Judul Cerita": placeholder_text = "Contoh Judul:\n- Misteri Hilangnya Kucing Firaun"
        elif mode == "Sinopsis": placeholder_text = "Contoh Sinopsis:\nDi tahun 2050, hujan tidak pernah berhenti turun..."
        else: placeholder_text = "Paste seluruh naskah ceritamu di sini..."
        story = st.text_area("Konten:", height=200, placeholder=placeholder_text)
    
    if st.button("📝 Buat Skenario", type="primary"):
        if story and char_desc:
            with st.spinner("Membuat skenario..."):
                res = generate_scenes_logic(GEMINI_API_KEY, story, mode, char_desc, num_scenes)
                if res:
                    st.session_state['generated_scenes'] = res
                    st.rerun()
        else: st.warning("Data kurang.")

# EDITOR SECTION
else:
    st.info("ℹ️ Tips: Scene tanpa gambar otomatis pakai gambar sebelumnya.")
    
    with st.container():
        for i, scene in enumerate(st.session_state['generated_scenes']):
            with st.expander(f"Scene {i+1}: {scene['narration'][:40]}...", expanded=True):
                col_a, col_b, col_c = st.columns([2, 1, 1])
                with col_a:
                    st.write(f"Narasi: {scene['narration']}")
                    st.code(scene['image_prompt'], language="text")
                with col_b:
                    if st.button(f"🎲 Generate AI {i+1}", key=f"gen_{i}"):
                        with st.spinner("Gen..."):
                            data = generate_image_pollinations(scene['image_prompt'])
                            if data: st.session_state['ai_images_data'][i] = data
                    uploaded = st.file_uploader(f"Upload {i+1}", type=['jpg','png'], key=f"up_{i}")
                with col_c:
                    if uploaded: st.image(uploaded, use_container_width=True)
                    elif i in st.session_state['ai_images_data']: st.image(st.session_state['ai_images_data'][i], use_container_width=True)

    st.divider()
    
    # === BAGIAN GENERATE VIDEO ===
    if st.button("🚀 RENDER VIDEO", type="primary", use_container_width=True):
        final_assets = []
        last_valid_img = None
        progress_bar = st.progress(0)
        
        # Proses pengumpulan aset
        for idx, scene in enumerate(st.session_state['generated_scenes']):
            audio_p = generate_audio_sync(scene['narration'], voice_gender)
            img_p = None
            
            # Cek upload manual
            if st.session_state.get(f"up_{idx}"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                    f.write(st.session_state[f"up_{idx}"].getbuffer())
                    img_p = f.name
            # Cek AI generated
            elif idx in st.session_state['ai_images_data']:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                    f.write(st.session_state['ai_images_data'][idx])
                    img_p = f.name
            
            # Logika Fallback (pakai gambar sebelumnya jika kosong)
            if img_p: last_valid_img = img_p
            elif last_valid_img: img_p = last_valid_img
            
            if audio_p and img_p:
                final_assets.append({"image": img_p, "audio": audio_p})
            progress_bar.progress((idx+1)/len(st.session_state['generated_scenes']))
            
        # Proses Render Video
        if final_assets:
            result_path = create_final_video(final_assets)
            if result_path:
                st.session_state['final_video_path'] = result_path # SIMPAN KE MEMORI
                st.balloons()
            else:
                st.error("Gagal render.")
    
    # === BAGIAN DOWNLOAD (DILUAR TOMBOL RENDER) ===
    # Ini kuncinya: Tombol download dicek dari session_state, bukan di dalam tombol render
    if st.session_state['final_video_path'] and os.path.exists(st.session_state['final_video_path']):
        st.success("✅ Video Siap Didownload!")
        
        # Tampilkan Video
        st.video(st.session_state['final_video_path'])
        
        # Tombol Download
        with open(st.session_state['final_video_path'], "rb") as f:
            st.download_button(
                label="⬇️ Download Video MP4",
                data=f,
                file_name="ai_story_video.mp4",
                mime="video/mp4"
            )
