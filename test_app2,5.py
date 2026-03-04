import streamlit as st
from google import genai
from PIL import Image
import json
from google.genai import types
# --- CONFIGURATION ---
# Replace the string below with your actual API key
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
st.title("🧠 AI Study Buddy (Day 2.5)")

# --- SIDEBAR SETTINGS ---
with st.sidebar:
    st.header("⚙️ App Settings")
    
    # Friendly names for the user
    model_choice = st.radio(
        "Select Operation Mode:",
        ["🧠 Think Mode (Deep Analysis)", "⚡ Fast Mode (Quick Q&A)"],
        help="Think Mode uses 2.5-Flash for accuracy. Fast Mode uses 2.5-Lite for speed."
    )
    
    # Internal Mapping
    if "Think" in model_choice:
        selected_model = "gemini-2.5-flash"
        st.success("Mode: High Accuracy 🎯")
    else:
        selected_model = "gemini-2.5-flash-lite"
        st.warning("Mode: Ultra Speed 🏎️")

    language = st.selectbox("Teaching Language", ["English", "Bahasa Indonesia"])

    st.divider()
    st.info(f"Using: {model_choice}")

sys_instr = f"You are an expert tutor. Always respond in {language}. Provide output in clear Markdown."

# 1. UPLOAD SECTION
uploaded_file = st.file_uploader("Upload your study notes here", type=["png", "jpg", "jpeg"])

if uploaded_file:
    # 2. IMAGE DISPLAY (Always stays at the top)
    img = Image.open(uploaded_file)
    st.image(img, caption="Current Study Material", width=500)
    st.divider()

    # 3. INTERACTIVE TABS
    tab1, tab2 = st.tabs(["📖 Explaining Mode", "❓ Answering Mode"])

    with tab1:
        st.subheader("Get a Full Study Guide")
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
                    
                    data = json.loads(response.text)

                    st.markdown(f"### 📝 Summary\n{data['summary']}")
                    
                    st.markdown("### 🎴 Flashcards (Click to reveal)")
                    cols = st.columns(2)
                    for i, item in enumerate(data['key_terms']):
                        with cols[i % 2]:
                            with st.expander(f"🔍 {item['term']}"):
                                st.write(item['definition'])
                                
                    st.markdown("### ❓ Practice Quiz")
                    for q in data['quiz_questions']:
                        st.info(q)
                except Exception as e:
                    st.error(f"Error in Explaining Mode: {e}")

    with tab2:
        st.subheader("Ask a specific question about these notes")
        user_question = st.text_input("Example: 'What is the value of x in the diagram?'")
        
        if st.button("Ask Question"):
            if user_question:
                with st.spinner("Thinking..."):
                    # 1. Simpler Config
                    qa_config = types.GenerateContentConfig(system_instruction=sys_instr)
                        
                        # 2. Dynamic QA Prompt
                    qa_prompt = f"Using the provided image as your source, answer this student's specific question: {user_question}"
                    
                    response = client.models.generate_content(
                        model=selected_model,
                        config=qa_config,
                        contents=[qa_prompt, img]
                    )
                    st.markdown("---")
                    st.markdown(f"**Question:** {user_question}")
                    st.success(f"**Answer:** {response.text}")
            else:
                st.warning("Please enter a question first.")

else:
    st.info("Please upload an image to begin.")