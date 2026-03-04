import streamlit as st
from google import genai
from PIL import Image
import json
from google.genai import types

st.markdown("""
<style>
    .stExpander {
        border: 1px solid #e6e9ef;
        border-radius: 10px;
        box-shadow: 0px 2px 5px rgba(0,0,0,0.05);
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# --- SESSION STATE INITIALIZATION ---
if "study_guide" not in st.session_state:
    st.session_state.study_guide = None  # Stores the JSON data

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []  # Stores list of Q&A pairs

# --- CONFIGURATION ---
if "client" not in st.session_state:
    try:
        API_KEY = st.secrets["GEMINI_API_KEY"]
        st.session_state.client = genai.Client(api_key=API_KEY)
    except Exception as e:
        st.error("Missing GEMINI_API_KEY in secrets.toml")
        st.stop()

#Initialize client once
client = st.session_state.client


st.set_page_config(page_title="AI Study Buddy 2026", layout="wide")
st.title("🧠 AI Study Buddy (Day 3)")

# --- SIDEBAR SETTINGS ---
with st.sidebar:
    st.header("⚙️ App Settings")

    # Operation Mode
    model_choice = st.radio(
        "Select Operation Mode:",
        ["🧠 Think Mode (Deep Analysis)", "⚡ Fast Mode (Quick Q&A)"],
        help="Think Mode uses 2.5-Flash for accuracy. Fast Mode uses 2.5-Lite for speed."
    )

    if "Think" in model_choice:
        selected_model = "gemini-2.5-flash"
        st.success("Mode: High Accuracy 🎯")
    else:
        selected_model = "gemini-2.5-flash-lite"
        st.warning("Mode: Ultra Speed 🏎️")

    language = st.selectbox("Teaching Language", ["English", "Bahasa Indonesia"])

    # The Reset Button
    st.divider()
    st.header("⚙️ Session Controls")
    
    # 1. The Guard (Checkbox)
    confirm_reset = st.checkbox("Confirm data wipe")
    
    # 2. The Button (Only works if Guard is checked)
    if st.button("🧹 Clear All Data", disabled=not confirm_reset, type="primary"):
        st.session_state.study_guide = None
        st.session_state.chat_history = []
        st.rerun()

    st.divider()
    st.header("📜 Chat History")
    for chat in reversed(st.session_state.chat_history):
        with st.expander(f"Q: {chat['question'][:30]}..."):
            st.write(f"**A:** {chat['answer']}")

    st.divider()
    st.info(f"Using: {model_choice}")

sys_instr = f"You are an expert tutor. Always respond in {language}. Provide output in clear Markdown."

# 1. UPLOAD SECTION
uploaded_file = st.file_uploader("Upload your study notes here", type=["png", "jpg", "jpeg"])

# --- CHANGE DETECTION LOGIC ---
# --- 1. INITIALIZATION ---
if "last_image_name" not in st.session_state:
    st.session_state.last_image_name = None

# --- 2. THE CHANGE DETECTOR (REPLACE YOUR OLD BLOCK WITH THIS) ---
if uploaded_file is not None:
    # If the filename is different from the last one we saw...
    if uploaded_file.name != st.session_state.last_image_name:
        st.session_state.study_guide = None
        st.session_state.chat_history = []
        # Update the tracker
        st.session_state.last_image_name = uploaded_file.name 
else:
    # IMPORTANT: If the user clicks 'x' to remove the file, reset the tracker
    # This allows them to re-upload the same file later if they want a fresh start
    st.session_state.last_image_name = None
# -----------------------------------

if uploaded_file:
    # 2. IMAGE DISPLAY (Always stays at the top)
    img = Image.open(uploaded_file)
    st.image(img, caption="Current Study Material", width=500)
    st.divider()

    # 3. INTERACTIVE TABS
    tab1, tab2 = st.tabs(["📖 Explaining Mode", "❓ Answering Mode"])

    with tab1:
        st.subheader("Get a Full Study Guide")
        # Trigger Button
        if st.button("Analyze Everything"):
            with st.spinner("Processing..."):
                try:
                    # 1. Config using JSON Schema standard (lowercase)
                    model_config = types.GenerateContentConfig(
                        system_instruction=sys_instr,
                        response_mime_type='application/json',
                        # Only use thinking budget if "Think Mode" is selected
                        thinking_config=types.ThinkingConfig(include_thoughts=True, thinking_budget=2000) if "Think" in model_choice else None,
                        response_schema={
                            'type': 'object',
                            'properties': {
                                'summary': {'type': 'string'},
                                'key_terms': {
                                    'type': 'array',
                                    'items': {
                                        'type': 'object',
                                        'properties': {
                                            'term': {'type': 'string'},
                                            'definition': {'type': 'string'}
                                        }
                                    }
                                },
                                'quiz_questions': {
                                    'type': 'array',
                                    'items': {'type': 'string'}
                                }
                            }
                        }
                    )
                    #Structural Prompt
                    extraction_prompt = "Analyze this image and extract a summary, key terms, and quiz questions into the required JSON format."
                    response = client.models.generate_content(
                        model=selected_model,
                        config=model_config,
                        contents=[extraction_prompt, img]
                    )
                    
                    # After parsing the JSON
                    try:
                        data = json.loads(response.text)
                        st.session_state.study_guide = data
                    except:
                        st.warning("AI returned unexpected format. Try again.")
                    # This ensures it stays on screen even if you click buttons in Tab 2!

                except Exception as e:
                    st.error(f"Error: {e}")

        # PERSISTENT DISPLAY (This shows up if data exists in the Vault)
        if st.session_state.study_guide:
            data = st.session_state.study_guide

            st.divider()
            st.markdown(f"### 📝 Summary\n{data['summary']}")

            # --- EXPORT BUTTON ---
            # We build the text string here
            export_text = f"STUDY NOTES\n\nSUMMARY:\n{data['summary']}\n\nKEY TERMS:\n"
            for item in data['key_terms']:
                export_text += f"- {item['term']}: {item['definition']}\n"
            
            st.download_button(
                label="📥 Download Study Guide",
                data=export_text,
                file_name="study_buddy_notes.txt",
                mime="text/plain"
            )
                    
            st.markdown("### 🎴 Flashcards (Click to reveal)")
            cols = st.columns(2)
            for i, item in enumerate(data['key_terms']):
                with cols[i % 2]:
                    with st.expander(f"🔍 {item['term']}"):
                        st.write(item['definition'])
                                
            st.markdown("### ❓ Practice Quiz")
            for q in data['quiz_questions']:
                st.info(q)

    with tab2:
        st.subheader("Ask a specific question about these notes")
        user_question = st.text_input("Example: 'What is x?'", key="user_qa_input")
        
        if st.button("Ask AI"):
            if user_question:
                with st.spinner("Thinking..."):
                    try:
                        # 1. Simpler Config
                        qa_config = types.GenerateContentConfig(system_instruction=sys_instr)
                        
                        # 2. Dynamic QA Prompt
                        qa_prompt = f"Using the provided image as your source, answer this student's specific question: {user_question}"
                    
                        # 3. Call Model
                        response = client.models.generate_content(
                            model=selected_model,
                            config=qa_config,
                            contents=[qa_prompt, img]
                        )

                        # 4. Save to Session State
                        st.session_state.chat_history.append({
                        "question": user_question,
                        "answer": response.text
                        })

                        # Trigger a rerun so the Vault Display updates instantly
                        st.rerun()

                    except Exception as e:
                        st.error(f"Error: {e}")
            else:
                st.warning("Please enter a question first.")
        #DISPLAY THE VAULT (The Scrolling History)
        if st.session_state.chat_history:
            st.divider()
            st.markdown("### 💬 Conversation History")
            
            # We show the latest question first (reversed)
            for chat in reversed(st.session_state.chat_history):
                with st.container():
                    # We use different colors/styles for User vs. AI
                    st.info(f"**👤 You:** {chat['question']}")
                    st.success(f"**🤖 AI:** {chat['answer']}")
                    st.markdown("---")
else:
    st.info("Please upload an image to begin.")