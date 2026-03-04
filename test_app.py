import streamlit as st
from google import genai
from PIL import Image
import json

st.set_page_config(page_title="AI Study Buddy v2", layout="wide")
st.title("🧠 Smart Study Buddy (Day 2)")

# Sidebar for Settings
with st.sidebar:
    api_key = st.text_input("Gemini API Key", type="password")
    # LANGUAGE PICKER
    language = st.selectbox("Teaching Language", ["English", "Bahasa Indonesia"])

if api_key:
    # Initialize Client
    client = genai.Client(api_key=api_key.strip())
    
    # SYSTEM INSTRUCTION: Setting the persona and language
    sys_instr = f"You are an expert tutor. Always respond in {language}. Provide output in clear Markdown with bold headers."

    uploaded_file = st.file_uploader("Upload Notes", type=["png", "jpg", "jpeg"])
    
    if uploaded_file:
        img = Image.open(uploaded_file)
        col1, col2 = st.columns(2)
        
        with col1:
            st.image(img, caption="Your Notes", use_container_width=True)
            
        with col2:
            if st.button("Generate Study Guide"):
                with st.spinner("Analyzing..."):
                # 1. Define the 'Shape' of the data we want
                # This tells the AI exactly what keys to use
                    response = client.models.generate_content(
                        model="gemini-2.5-flash-lite",
                        config={
                            'system_instruction': sys_instr,
                            'response_mime_type': 'application/json',
                            'response_schema': {
                                'type': 'OBJECT',
                                'properties': {
                                    'summary': {'type': 'STRING'},
                                    'key_terms': {
                                        'type': 'ARRAY',
                                        'items': {
                                            'type': 'OBJECT',
                                            'properties': {
                                             'term': {'type': 'STRING'},
                                             'definition': {'type': 'STRING'}
                                         }
                                     }
                                 },
                                    'quiz_questions': {
                                        'type': 'ARRAY',
                                        'items': {'type': 'STRING'}
                                 }
                             }
                         }
                     },
                        contents=["Analyze these notes and extract the data into the requested JSON format.", img]
                    )
                
                    # 2. Convert the string response into a Python Dictionary
                    data = json.loads(response.text)
                
                    # 3. Create the UI from that data
                    st.subheader("📝 Summary")
                    st.write(data['summary'])
                
                    st.subheader("🎴 Key Term Flashcards")
                    # Display terms as nice "tiles"
                    cols = st.columns(2)
                    for i, item in enumerate(data['key_terms']):
                        with cols[i % 2]:
                            with st.expander(f"🔍 {item['term']}"):
                                st.write(item['definition'])

                    st.subheader("❓ Practice Quiz")
                    for q in data['quiz_questions']:
                        st.info(q)
else:
    st.warning("Please enter your API key to start.")