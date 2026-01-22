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
# Import library video
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
import moviepy.config as mp_config

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="AI Story Video Pro (Stable)", page_icon="🛡️", layout="wide")

# --- AMBIL API KEY DARI SECRETS ---
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except FileNotFoundError:
    st.error("⚠️ File `.streamlit/secrets.toml` belum dibuat!")
    st.stop()
except KeyError:
    st.error("⚠️ Key `GEMINI_API_KEY` tidak ditemukan di secrets!")
    st.stop()

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
    # Memaksa ukuran HD di request
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
        # Gunakan path absolut untuk keamanan di Windows/Linux
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_file.close()
        asyncio.run(edge_tts_generate(text, voice, temp_file.name))
        return temp_file.name
    except: return None

# --- FUNGSI 4: VIDEO ENGINE (VERSI STABIL / ANTI-CRASH) ---
def create_final_video(assets):
    clips = []
    log_box = st.empty() # Kotak status live
    
    # Resolusi Target (Harus Genap!)
    W, H = 1280, 720 
    
    for i, asset in enumerate(assets):
        try:
            log_box.info(f"⚙️ Memproses Clip {i+1} dari {len(assets)}...")
            
            # 1. Load & Sanitasi Gambar (KUNCI PERBAIKAN)
            # Kita buka gambar dengan PIL dulu untuk memastikan ukurannya benar
            # MoviePy sering crash jika ukuran gambar ganjil (misal 1281x720)
            original_img = Image.open(asset['image'])
            if original_img.mode != 'RGB':
                original_img = original_img.convert('RGB')
            
            # Resize paksa ke 1280x720
            clean_img = original_img.resize((W, H), Image.LANCZOS)
            
            # Simpan gambar bersih ke temp file baru
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                clean_img.save(f, quality=95)
                clean_img_path = f.name
            
            # 2. Setup Audio
            audio = AudioFileClip(asset['audio'])
            duration = audio.duration + 0.5
            
            # 3. Buat Clip Video dari Gambar Bersih
            img_clip = ImageClip(clean_img_path).set_duration(duration)
            
            # 4. Efek Zoom Out (Versi Stabil)
            # Kita resize dari 1.1x ke 1.0x
            # Menggunakan center crop otomatis dari CompositeVideoClip
            img_clip = img_clip.resize(lambda t: 1.1 - (0.005 * t))
            img_clip = img_clip.set_position('center')
            
            # 5. Gabung Image + Audio
            # Set ukuran canvas eksplisit agar tidak error codec
            final_clip = CompositeVideoClip([img_clip], size=(W, H))
            final_clip = final_clip.set_audio(audio)
            final_clip = final_clip.set_fps(24) # Paksa FPS
            
            clips.append(final_clip)
            
        except Exception as e:
            st.error(f"❌ Error pada Scene {i+1}: {str(e)}")
            continue # Lanjut ke scene berikutnya jika error

    if not clips:
        st.error("Tidak ada clip yang berhasil dibuat.")
        return None
        
    try:
        log_box.info("🎞️ Menyatukan semua scene (Rendering)...")
        
        output_path = tempfile.mktemp(suffix=".mp4")
        
        # Gabungkan
        final_video = concatenate_videoclips(clips, method="compose")
        
        # Render File
        # threads=1 adalah yang paling stabil (mencegah memory leak)
        final_video.write_videofile(
            output_path, 
            fps=24, 
            codec='libx264', 
            audio_codec='aac', 
            preset='ultrafast',
            threads=1, 
            logger=None
        )
        
        log_box.success("✅ Render Selesai!")
        return output_path
        
    except Exception as e:
        st.error(f"❌ FATAL ERROR saat rendering final: {str(e)}")
        # Coba tampilkan pesan error lebih detail dari FFmpeg jika ada
        return None

# ================= UI APLIKASI =================
if 'generated_scenes' not in st.session_state: st.session_state['generated_scenes'] = []
if 'ai_images_data' not in st.session_state: st.session_state['ai_images_data'] = {}

st.sidebar.title("⚙️ Pengaturan")
voice_gender = st.sidebar.selectbox("Suara", ["Cowok (Ardi)", "Cewek (Gadis)"])
num_scenes = st.sidebar.slider("Jumlah Scene", 1, 100, 5)

if st.sidebar.button("🗑️ Reset Baru"):
    st.session_state['generated_scenes'] = []
    st.session_state['ai_images_data'] = {}
    st.rerun()

st.title("🎬 AI Video Maker (Versi Stabil)")
st.markdown("---")

# UI BAGIAN 1: INPUT
if not st.session_state['generated_scenes']:
    c1, c2 = st.columns([1, 2])
    with c1:
        st.info("Karakter")
        char_desc = st.text_area("Deskripsi:", height=150, placeholder="Contoh: Kucing oranye gemuk memakai topi...")
    with c2:
        st.info("Cerita")
        mode = st.radio("Mode:", ["Judul Cerita", "Sinopsis", "Cerita Jadi"], horizontal=True)
        placeholder = "Judul cerita..." if mode == "Judul Cerita" else "Isi cerita..."
        story = st.text_area("Konten:", height=150, placeholder=placeholder)
    
    if st.button("📝 Buat Skenario", type="primary"):
        if story and char_desc:
            with st.spinner("Membuat skenario..."):
                res = generate_scenes_logic(GEMINI_API_KEY, story, mode, char_desc, num_scenes)
                if res:
                    st.session_state['generated_scenes'] = res
                    st.rerun()
        else: st.warning("Data belum lengkap.")

# UI BAGIAN 2: EDITOR
else:
    st.info("ℹ️ Tips: Scene tanpa gambar akan otomatis mengambil gambar dari scene sebelumnya.")
    
    with st.container():
        for i, scene in enumerate(st.session_state['generated_scenes']):
            with st.expander(f"Scene {i+1}: {scene['narration'][:40]}...", expanded=True):
                col_a, col_b, col_c = st.columns([2, 1, 1])
                with col_a:
                    st.write(f"**Narasi:** {scene['narration']}")
                    st.code(scene['image_prompt'], language="text")
                with col_b:
                    st.markdown("**Gambar:**")
                    if st.button(f"🎲 Generate AI (Scene {i+1})", key=f"gen_{i}"):
                        with st.spinner("Generating..."):
                            data = generate_image_pollinations(scene['image_prompt'])
                            if data: st.session_state['ai_images_data'][i] = data
                            else: st.error("Gagal.")
                    
                    uploaded = st.file_uploader(f"Upload {i+1}", type=['jpg','png'], key=f"up_{i}")
                with col_c:
                    if uploaded: st.image(uploaded, use_container_width=True)
                    elif i in st.session_state['ai_images_data']: st.image(st.session_state['ai_images_data'][i], use_container_width=True)
                    else: st.markdown("*Belum ada gambar*")

    st.divider()
    
    # TOMBOL RENDER FINAL
    if st.button("🚀 RENDER VIDEO (Safe Mode)", type="primary", use_container_width=True):
        final_assets = []
        last_valid_img = None
        
        # Persiapan Progress Bar
        progress_bar = st.progress(0)
        total_steps = len(st.session_state['generated_scenes'])
        
        for idx, scene in enumerate(st.session_state['generated_scenes']):
            # 1. Audio
            audio_p = generate_audio_sync(scene['narration'], voice_gender)
            
            # 2. Gambar (Logic Fallback)
            img_p = None
            # Cek Upload
            if st.session_state.get(f"up_{idx}"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                    f.write(st.session_state[f"up_{idx}"].getbuffer())
                    img_p = f.name
            # Cek AI
            elif idx in st.session_state['ai_images_data']:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                    f.write(st.session_state['ai_images_data'][idx])
                    img_p = f.name
            
            # Fallback Logic
            if img_p:
                last_valid_img = img_p
            elif last_valid_img:
                img_p = last_valid_img
            
            # Masukkan ke antrian jika lengkap
            if audio_p and img_p:
                final_assets.append({"image": img_p, "audio": audio_p})
            
            progress_bar.progress((idx+1)/total_steps)
            
        if final_assets:
            result_path = create_final_video(final_assets)
            if result_path:
                st.balloons()
                st.video(result_path)
                with open(result_path, "rb") as f:
                    st.download_button("⬇️ Download MP4", f, "video_final.mp4")
        else:
            st.error("Gagal mengumpulkan aset. Pastikan minimal Scene 1 memiliki gambar.")
