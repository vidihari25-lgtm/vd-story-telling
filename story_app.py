import streamlit as st

# === FIX BUG ANTIALIAS ===
import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

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

# --- 1. KONFIGURASI HALAMAN (MODERN) ---
st.set_page_config(
    page_title="AI Director Studio", 
    page_icon="🎬", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. CUSTOM CSS (PROFESSIONAL LOOK) ---
st.markdown("""
<style>
    /* Import Google Font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Header Gradient Text */
    .title-text {
        background: linear-gradient(45deg, #FF4B4B, #FF914D);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        font-size: 3rem;
    }
    
    /* Custom Button Style */
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
        border: none;
        transition: all 0.3s ease;
    }
    
    /* Primary Button (Gradient) */
    div[data-testid="stButton"] > button[kind="primary"] {
        background: linear-gradient(90deg, #4F46E5 0%, #7C3AED 100%);
        box-shadow: 0 4px 14px 0 rgba(124, 58, 237, 0.39);
        border: none;
    }
    div[data-testid="stButton"] > button[kind="primary"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px 0 rgba(124, 58, 237, 0.23);
    }

    /* Card/Container Style */
    div[data-testid="stExpander"] {
        border: 1px solid #2e2e2e;
        border-radius: 10px;
        background-color: #ffffff;
    }
    
    /* Sidebar Polish */
    section[data-testid="stSidebar"] {
        background-color: #0e1117;
        border-right: 1px solid #262730;
    }
    
    /* Hide Default Streamlit Menu */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# --- AMBIL API KEY ---
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    st.error("⚠️ System Error: `GEMINI_API_KEY` missing configuration.")
    st.stop()

ELEVENLABS_API_KEY = st.secrets.get("ELEVENLABS_API_KEY", None)
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", None)

# --- SESSION STATE ---
if 'generated_scenes' not in st.session_state: st.session_state['generated_scenes'] = []
if 'ai_images_data' not in st.session_state: st.session_state['ai_images_data'] = {}
if 'final_video_path' not in st.session_state: st.session_state['final_video_path'] = None

# --- FUNGSI LOGIKA (TIDAK BERUBAH) ---
def extract_json(text):
    try:
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*$', '', text)
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match: return json.loads(match.group())
        return json.loads(text)
    except: return None

def analyze_uploaded_char(api_key, image_file):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-flash-latest')
        img = PIL.Image.open(image_file)
        response = model.generate_content(["Describe visual appearance briefly.", img])
        return response.text.strip()
    except: return "Error analyzing image."

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
    [{{"scene_number": 1, "narration": "Indonesian narration...", "image_prompt": "Cinematic shot of [Character Name], [action], 8k, masterpiece"}}]
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return extract_json(response.text)
    except: return None

def generate_image_pollinations(prompt):
    clean = requests.utils.quote(prompt)
    seed = random.randint(1, 99999)
    url = f"https://image.pollinations.ai/prompt/{clean}?width=1280&height=720&seed={seed}&nologo=true&model=flux"
    try:
        resp = requests.get(url, timeout=60)
        return resp.content if resp.status_code == 200 else None
    except: return None

# --- AUDIO HELPERS ---
async def edge_tts_generate(text, voice, output_file):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)

def generate_audio_elevenlabs(text, voice_id, api_key):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    data = {"text": text, "model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 0.5}}
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(response.content)
                return f.name
        return None
    except: return None

def generate_audio_openai(text, voice_name, api_key):
    url = "https://api.openai.com/v1/audio/speech"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {"model": "tts-1", "input": text, "voice": voice_name.lower()}
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(response.content)
                return f.name
        return None
    except: return None

def audio_manager(text, provider, selected_voice):
    if provider == "Edge-TTS (Gratis)":
        voice_id = "id-ID-ArdiNeural" if "Ardi" in selected_voice else "id-ID-GadisNeural"
        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_file.close()
            asyncio.run(edge_tts_generate(text, voice_id, temp_file.name))
            return temp_file.name
        except: return None
    elif provider == "OpenAI (Pro)":
        if not OPENAI_API_KEY: return None
        voice_map = {"Cowok (Echo)": "echo", "Cowok (Onyx)": "onyx", "Cewek (Nova)": "nova", "Cewek (Shimmer)": "shimmer"}
        return generate_audio_openai(text, voice_map.get(selected_voice, "alloy"), OPENAI_API_KEY)
    elif provider == "ElevenLabs (Ultra)":
        if not ELEVENLABS_API_KEY: return None
        voice_id = "pNInz6obpgDQGcFmaJgB" if "Adam" in selected_voice else "21m00Tcm4TlvDq8ikWAM"
        return generate_audio_elevenlabs(text, voice_id, ELEVENLABS_API_KEY)

# --- VIDEO ENGINE ---
def create_final_video(assets):
    clips = []
    log_box = st.empty()
    W, H = 1280, 720 
    
    for i, asset in enumerate(assets):
        try:
            log_box.info(f"⚙️ Processing Scene {i+1}...")
            original_img = PIL.Image.open(asset['image']).convert('RGB')
            clean_img = original_img.resize((W, H), PIL.Image.LANCZOS)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                clean_img.save(f, quality=95)
                clean_path = f.name
            
            audio = AudioFileClip(asset['audio'])
            duration = audio.duration + 0.5
            
            img_clip = ImageClip(clean_path).set_duration(duration)
            img_clip = img_clip.resize(lambda t: 1.1 - (0.005 * t)).set_position('center')
            
            final_clip = CompositeVideoClip([img_clip], size=(W, H)).set_audio(audio).set_fps(24)
            clips.append(final_clip)
        except: continue

    if not clips: return None
    try:
        log_box.info("🎞️ Rendering Final Video...")
        output_path = tempfile.mktemp(suffix=".mp4")
        final_video = concatenate_videoclips(clips, method="compose")
        final_video.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac', preset='ultrafast', threads=1, logger=None)
        log_box.success("✅ Done!")
        return output_path
    except: return None

# ================= UI MODERN START =================

# --- SIDEBAR PROFESIONAL ---
with st.sidebar:
    st.markdown("### 🛠️ Control Panel")
    
    with st.expander("🔊 Audio Settings", expanded=True):
        tts_provider = st.radio("Provider:", ["Edge-TTS (Gratis)", "OpenAI (Pro)", "ElevenLabs (Ultra)"])
        
        voice_option = ""
        if tts_provider == "Edge-TTS (Gratis)":
            voice_option = st.selectbox("Voice Model:", ["Cowok (Ardi)", "Cewek (Gadis)"])
        elif tts_provider == "OpenAI (Pro)":
            if not OPENAI_API_KEY: st.error("❌ API Key Missing")
            voice_option = st.selectbox("Voice Model:", ["Cowok (Echo)", "Cowok (Onyx)", "Cewek (Nova)", "Cewek (Shimmer)"])
        elif tts_provider == "ElevenLabs (Ultra)":
            if not ELEVENLABS_API_KEY: st.error("❌ API Key Missing")
            voice_option = st.selectbox("Voice Model:", ["Cowok (Adam)", "Cewek (Rachel)"])

    with st.expander("⚙️ Configuration", expanded=True):
        num_scenes = st.slider("Total Scenes:", 1, 50, 5)
    
    st.markdown("---")
    if st.button("🗑️ Start New Project", use_container_width=True):
        st.session_state['generated_scenes'] = []
        st.session_state['ai_images_data'] = {}
        st.session_state['final_video_path'] = None
        st.rerun()

    # Status Indicator
    st.markdown("---")
    st.markdown("**System Status:**")
    st.caption("🟢 Gemini AI: Active")
    st.caption(f"{'🟢' if OPENAI_API_KEY else '⚪'} OpenAI: {'Ready' if OPENAI_API_KEY else 'Inactive'}")

# --- MAIN HEADER ---
st.markdown('<h1 class="title-text">AI Director Studio</h1>', unsafe_allow_html=True)
st.markdown("Create professional short videos from text in seconds.")
st.markdown("---")

# --- WORKFLOW LOGIC ---

# 1. INPUT PHASE (TABS LAYOUT)
if not st.session_state['generated_scenes']:
    
    # Menggunakan Tabs untuk layout yang lebih bersih
    tab1, tab2 = st.tabs(["🎭 Characters", "📜 Storyline"])
    
    with tab1:
        st.info("Define your cast. The AI will maintain character consistency.")
        c1, c2 = st.columns(2)
        with c1:
            char1 = st.text_input("Main Character:", placeholder="e.g. Neo, black trench coat")
            char2 = st.text_input("Supporting 1:", placeholder="e.g. Morpheus, sunglasses")
        with c2:
            char3 = st.text_input("Supporting 2:", placeholder="e.g. Trinity, leather suit")
            char_img_upload = st.file_uploader("Visual Reference (Optional):", type=['jpg', 'png'])
    
    with tab2:
        st.info("Input your creative idea.")
        mode = st.radio("Input Mode:", ["Judul Cerita", "Sinopsis", "Cerita Jadi"], horizontal=True)
        story = st.text_area("Content:", height=200, placeholder="Type your story here...")

    # Action Button (Floating Bottom)
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("✨ Generate Screenplay & Prompts", type="primary", use_container_width=True):
        if story:
            with st.status("🤖 AI Director is working...", expanded=True) as status:
                st.write("Analyzing characters...")
                combined_char = f"Main: {char1}. Support: {char2}, {char3}."
                if char_img_upload:
                    desc = analyze_uploaded_char(GEMINI_API_KEY, char_img_upload)
                    combined_char += f" Ref Img: {desc}"
                
                st.write("Drafting storyboard...")
                res = generate_scenes_logic(GEMINI_API_KEY, story, mode, combined_char, num_scenes)
                
                if res:
                    st.session_state['generated_scenes'] = res
                    status.update(label="✅ Screenplay Ready!", state="complete", expanded=False)
                    time.sleep(1)
                    st.rerun()
                else:
                    status.update(label="❌ Generation Failed", state="error")
        else:
            st.warning("Please enter a story content.")

# 2. EDITOR PHASE (CARD LAYOUT)
else:
    st.markdown(f"### 🎬 Scene Editor ({len(st.session_state['generated_scenes'])} Scenes)")
    
    # Loop Scenes dengan Container Border
    for i, scene in enumerate(st.session_state['generated_scenes']):
        with st.container(border=True):
            cols = st.columns([0.1, 2, 1.5])
            
            # Scene Number styling
            with cols[0]:
                st.markdown(f"<h2 style='text-align:center; color:#666;'>{i+1}</h2>", unsafe_allow_html=True)
            
            # Text & Narration
            with cols[1]:
                st.markdown("**Narration (ID):**")
                st.write(f"_{scene['narration']}_")
                with st.expander("👁️ View Image Prompt"):
                    st.code(scene['image_prompt'], language="text")
            
            # Image Controls
            with cols[2]:
                # Tombol Generate AI
                if st.button(f"🎲 Generate AI Art", key=f"gen_{i}", use_container_width=True):
                     with st.spinner("Drawing..."):
                        data = generate_image_pollinations(scene['image_prompt'])
                        if data: st.session_state['ai_images_data'][i] = data
                
                # Manual Upload
                uploaded = st.file_uploader("Or Upload:", type=['jpg','png'], key=f"up_{i}", label_visibility="collapsed")
                
                # Preview Area
                if uploaded: 
                    st.image(uploaded, use_container_width=True)
                elif i in st.session_state['ai_images_data']: 
                    st.image(st.session_state['ai_images_data'][i], use_container_width=True)
                else:
                    st.info("No image yet.")

    # 3. EXPORT PHASE
    st.markdown("---")
    c_btn, c_info = st.columns([1, 2])
    
    with c_btn:
        if st.button("🚀 Render Final Movie", type="primary", use_container_width=True):
            # Check Keys
            if "Pro" in tts_provider and not OPENAI_API_KEY: st.error("Missing OpenAI Key"); st.stop()
            if "Ultra" in tts_provider and not ELEVENLABS_API_KEY: st.error("Missing ElevenLabs Key"); st.stop()

            # Collection Logic
            assets = []
            last_img = None
            bar = st.progress(0)
            
            for idx, sc in enumerate(st.session_state['generated_scenes']):
                # Audio
                aud = audio_manager(sc['narration'], tts_provider, voice_option)
                if not aud: st.error(f"Audio failed at scene {idx+1}"); st.stop()
                
                # Image
                img = None
                if st.session_state.get(f"up_{idx}"):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                        f.write(st.session_state[f"up_{idx}"].getbuffer())
                        img = f.name
                elif idx in st.session_state['ai_images_data']:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                        f.write(st.session_state['ai_images_data'][idx])
                        img = f.name
                
                # Fallback
                if img: last_img = img
                elif last_img: img = last_img
                
                if img and aud: assets.append({'image':img, 'audio':aud})
                bar.progress((idx+1)/len(st.session_state['generated_scenes']))
            
            # Create Video
            if assets:
                vid_path = create_final_video(assets)
                if vid_path:
                    st.session_state['final_video_path'] = vid_path
                    st.balloons()
                else: st.error("Rendering Failed.")
            else: st.warning("No assets to render.")

    # Download Area
    if st.session_state['final_video_path'] and os.path.exists(st.session_state['final_video_path']):
        with st.container(border=True):
            st.success("✅ Production Complete!")
            c_vid, c_dl = st.columns([2, 1])
            with c_vid:
                st.video(st.session_state['final_video_path'])
            with c_dl:
                st.write("### Download")
                with open(st.session_state['final_video_path'], "rb") as f:
                    st.download_button(
                        label="⬇️ Save MP4 File",
                        data=f,
                        file_name="ai_masterpiece.mp4",
                        mime="video/mp4",
                        type="primary",
                        use_container_width=True
                    )

