import streamlit as st
from google import genai
from PIL import Image
from ai_service import AIService
from file_utils import process_pdf_to_images, generate_study_pdf
from gtts import gTTS
from io import BytesIO
from datetime import datetime
import random

# Caching
@st.cache_resource
def get_ai_service(_client, language):
    return AIService(_client, language=language)

@st.cache_data
def get_pdf_export_bytes(data):
    # This calls your existing PDF generation logic
    return generate_study_pdf(data)

# --- 1. UI CONFIG & CSS ---
st.set_page_config(page_title="AI Study Buddy 2026", layout="wide")

st.markdown("""
<style>
    .flashcard {
        background-color: white; border-radius: 15px; padding: 20px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1); border: 1px solid #e0e0e0;
        margin-bottom: 15px; color: #333;
    }
    .flashcard-term {
        font-weight: bold; color: #ff4b4b; font-size: 1.1em; margin-bottom: 8px;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. SESSION STATE & CLIENTS ---
if "study_guide" not in st.session_state: st.session_state.study_guide = None
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "last_image_name" not in st.session_state: st.session_state.last_image_name = None

if "client" not in st.session_state:
    try:
        st.session_state.client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    except KeyError:
        st.error("Missing API Key"); st.stop()

if "content_to_analyze" not in st.session_state:
    st.session_state.content_to_analyze = None

if "quiz_data" not in st.session_state:
    st.session_state.quiz_data = None
if "user_answers" not in st.session_state:
    st.session_state.user_answers = {}

if "weak_topics" not in st.session_state:
    st.session_state.weak_topics = []
if "quiz_submitted" not in st.session_state:
    st.session_state.quiz_submitted = False
if "last_score" not in st.session_state:
    st.session_state.last_score = 0
if "quiz_history" not in st.session_state:
    st.session_state.quiz_history = []

# --- 3. SIDEBAR ---
with st.sidebar:
    st.title("⚙️ Settings")
    model_choice = st.radio("Mode:", ["🧠 Think Mode", "⚡ Fast Mode"])
    if model_choice == "🧠 Think Mode":
        selected_model = "gemini-2.5-flash"
    else:
        selected_model = "gemini-2.5-flash-lite"

    language = st.selectbox("Language", ["English", "Bahasa Indonesia"])
    ai_service = get_ai_service(st.session_state.client, language)

    st.divider()
    if st.checkbox("Confirm wipe") and st.button("🧹 Clear All", type="primary"):
        st.session_state.study_guide = None
        st.session_state.chat_history = []
        st.rerun()

    st.divider()
    st.subheader("📜 Recent Chat Questions")
    for chat in st.session_state.chat_history[-5:]: # Show the last 5
        st.caption(f"Q: {chat['question'][:30]}...")

# --- 4. MAIN APP ---
st.title("🧠 AI Study Buddy")
uploaded_file = st.file_uploader("Upload Notes (PDF or Image)", type=["png", "jpg", "jpeg", "pdf"])
is_new_file = uploaded_file and uploaded_file.name != st.session_state.last_image_name

# Change Detection
if is_new_file:
    st.session_state.study_guide = None
    st.session_state.chat_history = []
    st.session_state.quiz_data = None
    st.session_state.pdf_bytes = None

if uploaded_file:

    # Initialize session state for content if it doesn't exist
    if "content_to_analyze" not in st.session_state:
        st.session_state.content_to_analyze = []

    # --- STEP 1: ONLY PROCESS IF IT'S A NEW FILE ---
    if is_new_file:
        with st.spinner("Processing file for the first time..."):
            if uploaded_file.type == "application/pdf":
                # Process PDF to images once and store them
                st.session_state.content_to_analyze = process_pdf_to_images(uploaded_file.read())
            else:
                img = Image.open(BytesIO(uploaded_file))
                st.session_state.content_to_analyze = [img]
            
            # Reset state for the new file
            st.session_state.last_image_name = uploaded_file.name
            st.session_state.study_guide = None
            st.session_state.quiz_data = None
            st.session_state.pdf_bytes = None
            st.session_state.chat_history = []

    # --- STEP 2: DISPLAY PREVIEW (Instant from memory) ---
    if st.session_state.content_to_analyze:
        st.image(st.session_state.content_to_analyze[0], caption="Preview", width=400)

    # --- STEP 3: AUTO-SUMMARIZE ---
    if st.session_state.study_guide is None and st.session_state.content_to_analyze:
        with st.spinner("🤖 Analyzing..."):
            try:
                # Use the stored content
                data = ai_service.generate_study_guide(st.session_state.content_to_analyze)
                st.session_state.study_guide = data
                st.rerun()
            except Exception as e:
                st.error(f"Analysis Error: {e}")

# --- 5. DISPLAY TABS ---
if st.session_state.study_guide:
    tab1, tab2, tab3 = st.tabs(["📖 Study Guide", "💬 Chat", "🧠 Quiz"])
    data = st.session_state.study_guide

    with tab1:
        st.markdown(f"### 📝 Summary\n{data['summary']}")
        
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("🔊 Listen"):
                tts_lang = 'en' if language == "English" else 'id'
                tts = gTTS(text=data['summary'], lang=tts_lang)
                b = BytesIO(); tts.write_to_fp(b)
                st.audio(b, format="audio/mp3")
        with col_b:
            # Use File Utils for Export
            if st.session_state.pdf_bytes is None:
                with st.spinner("Preparing export..."):
                    st.session_state.pdf_bytes = generate_study_pdf(data)

            st.download_button(
                "📄 Download PDF",
                data=st.session_state.pdf_bytes,
                file_name="StudyGuide.pdf",
                mime="application/pdf"
                )

        st.divider()
        st.markdown("### 🎴 Flashcards")
        cols = st.columns(2)
        for i, item in enumerate(data['key_terms']):
            with cols[i % 2]:
                if st.toggle(f"Reveal: {item['term']}", key=f"f_{i}"):
                    st.markdown(f'<div class="flashcard"><b>Def:</b> {item["definition"]}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="flashcard"><div class="flashcard-term">🔍 {item["term"]}</div></div>', unsafe_allow_html=True)

    with tab2:
        st.subheader("💬 Chat")
        # 1. Create a container for the chat history
        # This keeps the history separate from the input box
        chat_container = st.container(height=500) # Fixed height creates a scrollbar

        with chat_container:
            for chat in st.session_state.chat_history:
                with st.chat_message("user"):
                    st.write(chat['question'])
                with st.chat_message("assistant"):
                    st.write(chat['answer'])

        # 2. Gemini-style input (Always stays at the bottom of the tab)
        # Note: We move this OUTSIDE the form for a more modern feel
        user_q = st.chat_input("Ask a question about your notes...")

        if user_q:
            # Display the user's question immediately
            with chat_container:
                with st.chat_message("user"):
                    st.write(user_q)
                
                # Prepare the AI response area
                with st.chat_message("assistant"):
                    placeholder = st.empty()
                    full_res = ""

                    if st.session_state.content_to_analyze:
                        try:
                            responses = ai_service.stream_chat(
                                user_q, 
                                st.session_state.content_to_analyze, 
                                selected_model
                            )
                            
                            for chunk in responses:
                                text = getattr(chunk, "text", None)
                                if text:
                                    full_res += chunk.text
                                    placeholder.markdown(full_res)
                            
                            # Save to history and rerun to lock it in
                            st.session_state.chat_history.append({"question": user_q, "answer": full_res})
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"Chat Error: {e}")
                    else:
                        st.warning("Please upload a document first!")

        if st.session_state.chat_history:
            st.divider()
            
            # 1. Create the text content
            chat_text = f"AI Study Buddy - Chat History\nDate: {datetime.now().strftime('%Y-%m-%d')}\nDocument: {st.session_state.last_image_name}\n"
            chat_text += "="*30 + "\n\n"
            
            for chat in st.session_state.chat_history:
                chat_text += f"USER: {chat['question']}\n"
                chat_text += f"AI: {chat['answer']}\n"
                chat_text += "-"*20 + "\n\n"
            
            # 2. Add the download button
            st.download_button(
                label="📥 Download Chat History",
                data=chat_text,
                file_name=f"Chat_History_{st.session_state.last_image_name}.txt",
                mime="text/plain",
                use_container_width=True
            )
    
    with tab3:
        st.header("🧠 Knowledge Check")

        # 1. GENERATE BUTTON
        if st.button("✨ Generate New Quiz", use_container_width=True):
            if st.session_state.content_to_analyze:
                with st.spinner("Analyzing notes and drafting questions..."):
                    try:
                        st.session_state.quiz_data = ai_service.generate_quiz(
                            st.session_state.content_to_analyze,
                            selected_model,
                            _seed=random.randint(1, 10000)
                        )
                        st.session_state.user_answers = {}
                        st.session_state.weak_topics = []
                        st.session_state.quiz_submitted = False
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to generate quiz: {e}")
            else:
                st.warning("⚠️ Please upload a document in the 'Upload' tab first!")

        # 2. DISPLAY QUIZ
        if st.session_state.quiz_data and not st.session_state.quiz_submitted:
            st.info("💡 Select the best answer for each question and hit 'Check My Answers'.")

            with st.form("quiz_form"):
                current_answers = {} # Temporary dict to hold form selections
                for i, q in enumerate(st.session_state.quiz_data):
                    st.subheader(f"Q{i+1}: {q['question']}")
                    current_val = st.session_state.user_answers.get(i)
                    try:
                        # Find the index of the answer we already picked
                        idx = q["options"].index(current_val) if current_val in q["options"] else None
                    except:
                        idx = None

                    current_answers[i] = st.radio(
                        "Choose an answer:",
                        q["options"],
                        key=f"q_radio_{i}",
                        index=idx  # This keeps the UI from resetting!
                    )
                    st.divider()

                submit_quiz = st.form_submit_button("🏁 Check My Answers", use_container_width=True)

            # 3. GRADING LOGIC (Triggered by Submit)
            if submit_quiz:
                # Check if any answer is None
                if None in current_answers.values():
                    st.warning("⚠️ Please answer all questions before submitting.")
                else:
                    # Move temp answers to session state
                    st.session_state.user_answers = current_answers
                    st.session_state.quiz_submitted = True
                
                    score = 0
                    temp_weak_topics = []
                    for i, q in enumerate(st.session_state.quiz_data):
                        user_ans = st.session_state.user_answers[i]
                        correct_ans = q["answer"]
                        if user_ans.strip().lower() == correct_ans.strip().lower():
                            score += 1
                        else:
                            temp_weak_topics.append({
                                "question": q["question"],
                                "your_answer": user_ans,
                                "correct_answer": q["answer"],
                                "explanation": q["explanation"]
                                })
                            
                    st.write("User Answer:", user_ans)
                    st.write("Correct Answer:", correct_ans)
                    st.session_state.last_score = score
                    st.session_state.weak_topics = temp_weak_topics
                    st.session_state.quiz_history.append({"score": score, "total": len(st.session_state.quiz_data)})
                    st.rerun() # Rerun to show results

        # 4. SHOW RESULTS (Outside the form, stays on screen)
        if st.session_state.quiz_submitted and st.session_state.quiz_data:
            st.metric("Final Score", f"{st.session_state.last_score} / {len(st.session_state.quiz_data)}")
        
            if st.session_state.last_score == len(st.session_state.quiz_data):
                st.success("🎉 Perfect Score!")
                st.balloons()

            for i, q in enumerate(st.session_state.quiz_data):
                user_ans = st.session_state.user_answers.get(i)
                if user_ans == q["answer"]:
                    st.write(f"✅ **Q{i+1}**: Correct!")
                else:
                    st.write(f"❌ **Q{i+1}**: Incorrect")
                    with st.expander(f"View explanation for Q{i+1}"):
                        st.write(f"**Correct Answer:** {q['answer']}")
                        st.write(f"**Explanation:** {q['explanation']}")

            # 5. ADAPTIVE PRACTICE (Appears only if they missed something)
            if st.session_state.weak_topics:
                st.divider()
                st.subheader("📚 Targeted Review")
                if st.button("🚀 Generate Practice Quiz", use_container_width=True):
                    with st.spinner("Creating practice..."):
                        try:
                            followup = ai_service.generate_followup_quiz(
                                st.session_state.weak_topics,
                                st.session_state.content_to_analyze,
                                selected_model
                            )
                            st.session_state.quiz_data = followup
                            st.session_state.user_answers = {}
                            st.session_state.weak_topics = []
                            st.session_state.quiz_submitted = False
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed: {e}")

        # 6. HISTORY (Always at the bottom)
        if st.session_state.quiz_history:
            st.divider()
            st.subheader("📊 Your Progress")
            import pandas as pd
            df = pd.DataFrame(st.session_state.quiz_history)
            df["Accuracy"] = (df["score"] / df["total"].replace(0,1) * 100).round(2)
            st.line_chart(df["Accuracy"])
            st.dataframe(df, use_container_width=True)