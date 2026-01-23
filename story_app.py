import streamlit as st

# === FIX BUG ANTIALIAS (WAJIB DI PALING ATAS) ===
import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
# ================================================

import google.generativeai as genai
import json
import requests
import tempfile
import asyncio
import edge_tts
import re
import random
import os
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="AI Story Video (Triple Voice)", page_icon="🎬", layout="wide")

# --- AMBIL API KEY DARI SECRETS ---
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    st.error("⚠️ Key `GEMINI_API_KEY` hilang di secrets.toml!")
    st.stop()

# Ambil Key Tambahan (Boleh None jika tidak dipakai)
ELEVENLABS_API_KEY = st.secrets.get("ELEVENLABS_API_KEY", None)
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", None)

# --- SESSION STATE ---
if 'generated_scenes' not in st.session_state: st.session_state['generated_scenes'] = []
if 'ai_images_data' not in st.session_state: st.session_state['ai_images_data'] = {}
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

# --- FUNGSI ANALISIS GAMBAR ---
def analyze_uploaded_char(api_key, image_file):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-flash-latest')
        img = PIL.Image.open(image_file)
        prompt = "Describe the visual appearance of this character in detail (face, hair, clothes, style) in one paragraph."
        response = model.generate_content([prompt, img])
        return response.text.strip()
    except Exception as e:
        return f"Error analyzing image: {e}"

# --- FUNGSI 1: AI SCENARIO ---
def generate_scenes_logic(api_key, input_text, input_mode, char_desc, target_scenes):
    genai.configure(api_key=api_key)
    mode_instruction = ""
    if input_mode == "Judul Cerita": mode_instruction = f"Story from title: '{input_text}'."
    elif input_mode == "Sinopsis": mode_instruction = f"Expand synopsis: '{input_text}'."
    elif input_mode == "Cerita Jadi": mode_instruction = f"Use exactly: '{input_text}'."

    prompt = f"""
    Act as Video Director. Mode: {input_mode}. 
    CHARACTERS: {char_desc}
    Task: {mode_instruction}.
    Create exactly {target_scenes} scenes.
    OUTPUT JSON ARRAY ONLY:
    [{{"scene_number": 1, "narration": "Indonesian narration...", "image_prompt": "Cinematic shot of [Character Name], [action], 8k"}}]
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
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

# --- FUNGSI 3: AUDIO MANAGER (TRIPLE MODE) ---

# 3a. Helper: Edge-TTS
async def edge_tts_generate(text, voice, output_file):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)

# 3b. Helper: ElevenLabs
def generate_audio_elevenlabs(text, voice_id, api_key):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    data = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(response.content)
                return f.name
        return None
    except: return None

# 3c. Helper: OpenAI TTS (BARU)
def generate_audio_openai(text, voice_name, api_key):
    url = "https://api.openai.com/v1/audio/speech"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {
        "model": "tts-1", # Model standar (cepat & murah)
        "input": text,
        "voice": voice_name.lower() # alloy, echo, fable, onyx, nova, shimmer
    }
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(response.content)
                return f.name
        else:
            print(f"OpenAI Error: {response.text}")
            return None
    except: return None

# 3d. ROUTER UTAMA
def audio_manager(text, provider, selected_voice):
    # OPSI 1: EDGE TTS (GRATIS)
    if provider == "Edge-TTS (Gratis)":
        voice_id = "id-ID-ArdiNeural" if selected_voice == "Cowok (Ardi)" else "id-ID-GadisNeural"
        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_file.close()
            asyncio.run(edge_tts_generate(text, voice_id, temp_file.name))
            return temp_file.name
        except: return None
    
    # OPSI 2: OPENAI (TERBAIK/MURAH)
    elif provider == "OpenAI (Pro)":
        if not OPENAI_API_KEY: return None
        # Mapping nama ke ID suara OpenAI
        # Cowok: Echo, Onyx | Cewek: Nova, Shimmer, Alloy
        voice_map = {
            "Cowok (Echo)": "echo",
            "Cowok (Onyx)": "onyx",
            "Cewek (Nova)": "nova",
            "Cewek (Shimmer)": "shimmer"
        }
        voice_id = voice_map.get(selected_voice, "alloy")
        return generate_audio_openai(text, voice_id, OPENAI_API_KEY)

    # OPSI 3: ELEVENLABS (ULTRA)
    elif provider == "ElevenLabs (Ultra)":
        if not ELEVENLABS_API_KEY: return None
        voice_id = "pNInz6obpgDQGcFmaJgB" if selected_voice == "Cowok (Adam)" else "21m00Tcm4TlvDq8ikWAM"
        return generate_audio_elevenlabs(text, voice_id, ELEVENLABS_API_KEY)

# --- FUNGSI 4: VIDEO ENGINE ---
def create_final_video(assets):
    clips = []
    log_box = st.empty()
    W, H = 1280, 720 
    
    for i, asset in enumerate(assets):
        try:
            log_box.info(f"⚙️ Memproses Clip {i+1} dari {len(assets)}...")
            
            original_img = PIL.Image.open(asset['image'])
            if original_img.mode != 'RGB':
                original_img = original_img.convert('RGB')
            clean_img = original_img.resize((W, H), PIL.Image.LANCZOS)
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                clean_img.save(f, quality=95)
                clean_img_path = f.name
            
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

# --- PILIHAN TRIPLE PROVIDER ---
st.sidebar.subheader("🔊 Pengaturan Suara")
tts_provider = st.sidebar.radio("Pilih Provider:", ["Edge-TTS (Gratis)", "OpenAI (Pro)", "ElevenLabs (Ultra)"])

voice_option = ""
if tts_provider == "Edge-TTS (Gratis)":
    voice_option = st.sidebar.selectbox("Suara:", ["Cowok (Ardi)", "Cewek (Gadis)"])

elif tts_provider == "OpenAI (Pro)":
    if not OPENAI_API_KEY:
        st.sidebar.error("⚠️ Masukkan OPENAI_API_KEY di secrets.toml!")
    voice_option = st.sidebar.selectbox("Suara HD:", ["Cowok (Echo)", "Cowok (Onyx)", "Cewek (Nova)", "Cewek (Shimmer)"])

elif tts_provider == "ElevenLabs (Ultra)":
    if not ELEVENLABS_API_KEY:
        st.sidebar.error("⚠️ Masukkan ELEVENLABS_API_KEY di secrets.toml!")
    voice_option = st.sidebar.selectbox("Suara Ultra:", ["Cowok (Adam)", "Cewek (Rachel)"])

st.sidebar.divider()
num_scenes = st.sidebar.slider("Jumlah Scene", 1, 100, 5)

if st.sidebar.button("🗑️ Reset Baru"):
    st.session_state['generated_scenes'] = []
    st.session_state['ai_images_data'] = {}
    st.session_state['final_video_path'] = None
    st.rerun()

st.title("🎬 AI Video Maker (Triple Voice)")
st.markdown("---")

# INPUT SECTION
if not st.session_state['generated_scenes']:
    c1, c2 = st.columns([1, 2])
    
    with c1:
        st.info("👥 **Input Karakter**")
        char1 = st.text_input("Tokoh 1:", placeholder="Nama & Ciri fisik")
        char2 = st.text_input("Tokoh 2:", placeholder="Nama & Ciri fisik")
        char3 = st.text_input("Tokoh 3:", placeholder="Nama & Ciri fisik")
        st.divider()
        st.write("**Tokoh 4 (Upload Gambar):**")
        char_img_upload = st.file_uploader("Upload foto:", type=['jpg', 'png', 'jpeg'])
        if char_img_upload: st.image(char_img_upload, caption="Preview Tokoh 4", width=150)
            
    with c2:
        st.info("📖 **Cerita**")
        mode = st.radio("Mode:", ["Judul Cerita", "Sinopsis", "Cerita Jadi"], horizontal=True)
        placeholder_text = "Tulis ceritamu di sini..."
        story = st.text_area("Konten Cerita:", height=350, placeholder=placeholder_text)
    
    if st.button("📝 Buat Skenario", type="primary", use_container_width=True):
        if story:
            progress_text = st.empty()
            progress_text.text("🔄 Mengumpulkan data karakter...")
            
            combined_char_desc = "Daftar Karakter Utama:\n"
            if char1: combined_char_desc += f"- Tokoh 1: {char1}\n"
            if char2: combined_char_desc += f"- Tokoh 2: {char2}\n"
            if char3: combined_char_desc += f"- Tokoh 3: {char3}\n"
            
            if char_img_upload:
                progress_text.text("🔄 Menganalisis gambar Tokoh 4...")
                img_desc = analyze_uploaded_char(GEMINI_API_KEY, char_img_upload)
                combined_char_desc += f"- Tokoh 4 (Visual Reference): {img_desc}\n"
            
            if len(combined_char_desc) < 25: combined_char_desc = "General characters fitting the story context."

            progress_text.text("🤖 Membuat Skenario dengan AI...")
            res = generate_scenes_logic(GEMINI_API_KEY, story, mode, combined_char_desc, num_scenes)
            
            if res:
                st.session_state['generated_scenes'] = res
                progress_text.empty()
                st.rerun()
            else:
                progress_text.error("Gagal membuat skenario.")
        else: st.warning("Cerita masih kosong!")

# EDITOR SECTION
else:
    if "Pro" in tts_provider or "Ultra" in tts_provider:
        st.warning(f"⚠️ Mode Berbayar Aktif: {tts_provider}. Pastikan kuota API cukup.")
    
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
    
    if st.button("🚀 RENDER VIDEO", type="primary", use_container_width=True):
        # Validasi Key
        if tts_provider == "OpenAI (Pro)" and not OPENAI_API_KEY:
            st.error("❌ API Key OpenAI kosong!")
            st.stop()
        if tts_provider == "ElevenLabs (Ultra)" and not ELEVENLABS_API_KEY:
            st.error("❌ API Key ElevenLabs kosong!")
            st.stop()

        final_assets = []
        last_valid_img = None
        progress_bar = st.progress(0)
        
        for idx, scene in enumerate(st.session_state['generated_scenes']):
            # GENERATE AUDIO (ROUTER)
            audio_p = audio_manager(scene['narration'], tts_provider, voice_option)
            
            if not audio_p and "Gratis" not in tts_provider:
                st.error(f"Gagal generate suara Pro pada Scene {idx+1}. Cek kuota/Key.")
                st.stop()
            
            img_p = None
            if st.session_state.get(f"up_{idx}"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                    f.write(st.session_state[f"up_{idx}"].getbuffer())
                    img_p = f.name
            elif idx in st.session_state['ai_images_data']:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                    f.write(st.session_state['ai_images_data'][idx])
                    img_p = f.name
            
            if img_p: last_valid_img = img_p
            elif last_valid_img: img_p = last_valid_img
            
            if audio_p and img_p:
                final_assets.append({"image": img_p, "audio": audio_p})
            progress_bar.progress((idx+1)/len(st.session_state['generated_scenes']))
            
        if final_assets:
            result_path = create_final_video(final_assets)
            if result_path:
                st.session_state['final_video_path'] = result_path
                st.balloons()
            else:
                st.error("Gagal render.")
    
    if st.session_state['final_video_path'] and os.path.exists(st.session_state['final_video_path']):
        st.success("✅ Video Siap!")
        st.video(st.session_state['final_video_path'])
        with open(st.session_state['final_video_path'], "rb") as f:
            st.download_button("⬇️ Download Video MP4", data=f, file_name="ai_story_video.mp4", mime="video/mp4")
