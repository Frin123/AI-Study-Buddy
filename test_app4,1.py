import streamlit as st
from google import genai
from PIL import Image
import json
from google.genai import types
import pypdf
from io import BytesIO
from pdf2image import convert_from_bytes
from gtts import gTTS
from fpdf import FPDF

st.markdown("""
<style>
    /* Flashcard Styling */
    .flashcard {
        background-color: white;
        border-radius: 15px;
        padding: 20px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        border: 1px solid #e0e0e0;
        margin-bottom: 15px;
        transition: transform 0.2s;
        color: #333;
    }
    .flashcard:hover {
        transform: translateY(-5px);
        box-shadow: 0 6px 12px rgba(0,0,0,0.15);
    }
    .flashcard-term {
        font-weight: bold;
        color: #ff4b4b;
        font-size: 1.1em;
        margin-bottom: 8px;
    }
</style>
""", unsafe_allow_html=True)

def create_pdf(data):
    pdf = FPDF()
    pdf.add_page()
    
    # Title
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "AI Study Buddy: Summary & Notes", ln=True, align='C')
    pdf.ln(10)
    
    # Summary
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Summary:", ln=True)
    pdf.set_font("Arial", '', 11)
    pdf.multi_cell(0, 10, data['summary'])
    pdf.ln(5)
    
    # Key Terms
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Key Terms:", ln=True)
    pdf.set_font("Arial", '', 11)
    for item in data['key_terms']:
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(0, 8, f"- {item['term']}:", ln=True)
        pdf.set_font("Arial", '', 10)
        pdf.multi_cell(0, 8, item['definition'])
        pdf.ln(2)
        
    return bytes(pdf.output()) # Returns as bytes

# --- CONFIGURATION & SESSION STATE ---
if "study_guide" not in st.session_state:
    st.session_state.study_guide = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "last_image_name" not in st.session_state:
    st.session_state.last_image_name = None

# API Setup
if "client" not in st.session_state:
    try:
        st.session_state.client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    except:
        st.error("Missing API Key"); st.stop()

client = st.session_state.client

def get_model_for_task(task_type):
    """
    Centralized model router.
    'auto': used for the structured JSON study guide (needs speed/reliability)
    'chat': used for the conversational Q&A (respects user choice)
    """
    if task_type == "auto":
        # Always use standard Flash for JSON generation
        return "gemini-2.5-flash-lite"
    
    # Otherwise, return the model selected in the sidebar
    return selected_model

st.set_page_config(page_title="AI Study Buddy 2026", layout="wide")

# --- SIDEBAR ---
with st.sidebar:
    st.title("⚙️ Settings")
    model_choice = st.radio("Mode:", ["🧠 Think Mode (Deep Analysis)", "⚡ Fast Mode (Quick Q&A)"])
    selected_model = "gemini-2.5-flash" if "Think" in model_choice else "gemini-2.5-flash-lite"
    language = st.selectbox("Language", ["English", "Bahasa Indonesia"])

    st.divider()
    confirm_reset = st.checkbox("Confirm wipe")
    if st.button("🧹 Clear All", disabled=not confirm_reset, type="primary"):
        st.session_state.study_guide = None
        st.session_state.chat_history = []
        st.rerun()

    st.divider()
    st.header("📜 Chat History")
    for chat in reversed(st.session_state.chat_history):
        with st.expander(f"Q: {chat['question'][:25]}..."):
            st.write(chat['answer'])

# --- MAIN APP ---
st.title("🧠 AI Study Buddy")
sys_instr = f"You are an expert tutor. Always respond in {language}. Use LaTeX for math like $x^2$."

uploaded_file = st.file_uploader("Upload Notes (PDF or Image)", type=["png", "jpg", "jpeg", "pdf"])

# --- 1. CHANGE DETECTION ---
if uploaded_file and uploaded_file.name != st.session_state.last_image_name:
    st.session_state.study_guide = None
    st.session_state.chat_history = []
    st.session_state.last_image_name = uploaded_file.name
    if "quality_warning" in st.session_state: del st.session_state.quality_warning

# --- 2. CONTENT PROCESSING ---
content_to_analyze = []

if uploaded_file:
    if uploaded_file.type == "application/pdf":
        with st.spinner("Converting PDF to Vision format..."):
            try:
                # IMPORTANT: Point exactly to the /bin folder of your Poppler install
                images = convert_from_bytes(
                    uploaded_file.read(),
                    poppler_path=r"C:\Users\USER\poppler-25.12.0\Library\bin"
                    )
                
                content_to_analyze = images[:5] # Analyze first 5 pages
                st.image(content_to_analyze[0], caption="Page 1 of PDF", width=400)

            except Exception as e:
                st.error(f"Poppler Error: {e}. Check your poppler_path!")
    else:
        img = Image.open(uploaded_file)
        content_to_analyze = [img]
        st.image(img, caption="Uploaded Image", width=400)

        # --- Quality Guard (Only trigger for camera/image uploads) ---
    if uploaded_file.type != "application/pdf": 
        if "quality_warning" not in st.session_state:
            with st.spinner("🔍 Checking clarity..."):
                check_prompt = "Is this text clear? Answer ONLY 'PASS' or 'FAIL: [reason]'."
                q_res = client.models.generate_content(model=get_model_for_task("auto"), contents=[check_prompt, img])
                st.session_state.quality_warning = q_res.text
        
        if "FAIL" in st.session_state.quality_warning:
            st.warning(f"⚠️ {st.session_state.quality_warning}")

    # --- AUTO-SUMMARIZE LOGIC ---
    if st.session_state.study_guide is None:
        with st.spinner("🤖 Auto-analyzing your notes..."):
            model_config = types.GenerateContentConfig(
                system_instruction=sys_instr,
                response_mime_type='application/json',
                response_schema={'type': 'object', 'properties': {
                    'summary': {'type': 'string'},
                    'key_terms': {'type': 'array', 'items': {'type': 'object', 'properties': {'term': {'type': 'string'}, 'definition': {'type': 'string'}}}},
                    'quiz_questions': {'type': 'array', 'items': {'type': 'string'}}
                }}
            )
            contents = ["Summarize this."]

            for img in content_to_analyze:
                contents.append(img)

            res = client.models.generate_content(
            model=get_model_for_task("auto"),
            config=model_config,
            contents=contents
            )

            try:
                parsed_data = json.loads(res.text)
                # Validate top-level keys
                required_keys = ["summary", "key_terms", "quiz_questions"]
                if not all(key in parsed_data for key in required_keys):
                    raise ValueError("Missing required keys")

                # Validate summary
                if not isinstance(parsed_data["summary"], str):
                    raise ValueError("Summary must be string")

                # Validate key_terms
                if not isinstance(parsed_data["key_terms"], list):
                    raise ValueError("key_terms must be list")

                for item in parsed_data["key_terms"]:
                    if not isinstance(item, dict):
                        raise ValueError("Each key_term must be object")
                    if "term" not in item or "definition" not in item:
                        raise ValueError("Missing term/definition")
                    if not isinstance(item["term"], str) or not isinstance(item["definition"], str):
                        raise ValueError("Invalid term structure")

                # Validate quiz_questions
                if not isinstance(parsed_data["quiz_questions"], list):
                    raise ValueError("quiz_questions must be list")
                if not all(isinstance(q, str) for q in parsed_data["quiz_questions"]):
                    raise ValueError("Invalid quiz question format")
                
                st.session_state.study_guide = parsed_data

                st.rerun()

            except (json.JSONDecodeError, ValueError):
                st.error("⚠️ The model returned invalid JSON. Please try again.")

# --- 3. TABS & LOGIC ---
if st.session_state.study_guide:
    tab1, tab2 = st.tabs(["📖 Study Guide", "💬 Chat"])
    data = st.session_state.study_guide

    with tab1:
        st.markdown(f"### 📝 Summary\n{data['summary']}")
        
        # Audio & PDF Export Row
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("🔊 Listen"):
                tts = gTTS(text=data['summary'], lang='en' if language=="English" else 'id')
                b = BytesIO(); tts.write_to_fp(b)
                st.audio(b, format="audio/mp3")
        with col_b:
            pdf_data = create_pdf(data)
            st.download_button("📄 Download PDF Guide", data=pdf_data, file_name="StudyGuide.pdf")

        st.divider()
        st.markdown("### 🎴 Flashcards (Click to reveal)")
        cols = st.columns(2)
        for i, item in enumerate(data['key_terms']):
            with cols[i % 2]:
                # Unique key for each toggle
                is_flipped = st.toggle(f"Reveal: {item['term']}", key=f"flip_{i}")
                
                if is_flipped:
                    # The "Back" of the card (Definition)
                    st.markdown(f"""
                    <div class="flashcard" style="border-left: 5px solid #ff4b4b;">
                        <div style="font-size: 0.9em; color: #555;">Definition:</div>
                        <div>{item['definition']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    # The "Front" of the card (Term)
                    st.markdown(f"""
                    <div class="flashcard">
                        <div class="flashcard-term">🔍 {item['term']}</div>
                        <div style="font-size: 0.8em; color: #888;">Click toggle to see definition</div>
                    </div>
                    """, unsafe_allow_html=True)
                                
        st.markdown("### ❓ Practice Quiz")
        for q in data['quiz_questions']:
            st.info(q)

    with tab2:
        st.subheader("💬 Chat with your Notes")

        # Display historical chat below the active session
        if st.session_state.chat_history:
            st.divider()
            for chat in st.session_state.chat_history:
                st.info(f"**👤 You:** {chat['question']}")
                st.success(f"**🤖 AI:** {chat['answer']}")

        user_question = st.text_input("Ask about these notes:", key="user_qa")

        if st.button("Ask AI"):
            if user_question:
                # Show the user's question immediately at the bottom
                st.info(f"**👤 You:** {user_question}")

                with st.spinner("Thinking..."):
                    qa_config = types.GenerateContentConfig(system_instruction=sys_instr)
                    qa_prompt = f"Using these notes, answer: {user_question}"

                    response_stream = client.models.generate_content_stream(
                        model=selected_model,
                        config=qa_config,
                        contents = [qa_prompt] + content_to_analyze
                    )

                    #Stream the response to the UI
                    placeholder = st.empty() # Creates a spot that we can update
                    full_response = ""

                    for chunk in response_stream:
                        if chunk.text:
                            full_response += chunk.text
                            placeholder.success(f"**🤖 AI:** {full_response}")

                    st.session_state.chat_history.append({
                        "question": user_question,
                        "answer": full_response
                    })

            else:
                st.warning("Please enter a question first.")
        
        
else:
    st.info("Please upload an image to begin")