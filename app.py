import streamlit as st
from google import genai
from PIL import Image
from ai_service import AIService
from file_utils import process_pdf_to_images, generate_study_pdf
from gtts import gTTS
from io import BytesIO
import random
from datetime import datetime
import json
import hashlib
import pandas as pd
from database_manager import SupabaseManager

# --- 1. INITIALIZATION & CONFIG ---
db = SupabaseManager()
st.set_page_config(page_title="AI Study Buddy 2026", layout="wide")

# Custom CSS for Flashcards
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

# --- 2. SESSION STATE MANAGEMENT ---
def init_state():
    defaults = {
        "study_guide": None, "chat_history": [], "last_image_name": None,
        "content_to_analyze": None, "quiz_data": None, "user_answers": {},
        "weak_topics": [], "quiz_submitted": False, "last_score": 0,
        "quiz_history": [], "current_doc_id": None, "pdf_bytes": None
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

init_state()

# This ensures that if the page refreshes, we reload the chat history
if st.session_state.current_doc_id and not st.session_state.chat_history:
    with st.spinner("Syncing chat history..."):
        history = db.get_chat_history(st.session_state.current_doc_id)
        if history:
            # We assume your DB returns messages in 'created_at' order
            st.session_state.chat_history = history

# API Client Setup
if "client" not in st.session_state:
    try:
        st.session_state.client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    except KeyError:
        st.error("Missing API Key in Secrets!"); st.stop()

# --- 3. SIDEBAR NAVIGATION ---
with st.sidebar:
    st.title("🎓 AI Study Coach")
    page = st.radio("Navigation", ["🏠 Dashboard", "📂 Library", "📖 Study Room", "🧠 Quiz Center"])
    
    st.divider()
    st.subheader("⚙️ Settings")
    model_choice = st.radio("Mode:", ["🧠 Think Mode", "⚡ Fast Mode"])
    selected_model = "gemini-3.1-flash-lite-preview" if model_choice == "🧠 Think Mode" else "gemini-2.5-flash-lite"
    language = st.selectbox("Language", ["English", "Bahasa Indonesia"])
    
    # Cache the AI Service
    @st.cache_resource
    def get_ai_service(_client, lang):
        return AIService(_client, language=lang)
    
    ai_service = get_ai_service(st.session_state.client, language)

    st.divider()
    if st.button("🧹 Reset Current Session", use_container_width=True):
        for key in st.session_state.keys():
            if key != "client": del st.session_state[key]
        st.rerun()

# --- 4. PAGE LOGIC ---

# PAGE 1: DASHBOARD
if page == "🏠 Dashboard":
    st.title("🚀 Your Learning Progress")
    
    # Global Metrics
    avg_score = db.get_average_score()
    col1, col2, col3 = st.columns(3)
    col1.metric("Global Accuracy", f"{round(avg_score * 100, 1)}%")
    
    # Fetch total questions from your study_sessions table
    total_q = db.get_total_questions_practiced()
    col2.metric("Questions Practiced", total_q)
    
    # Trend Chart
    st.divider()
    st.subheader("📈 Knowledge Growth")
    trend_data = db.get_score_trend()
    if trend_data:
        df_trend = pd.DataFrame(trend_data, columns=["Date", "Score"])
        df_trend["Score"] = df_trend["Score"] * 100
        st.line_chart(df_trend.set_index("Date"))
    else:
        st.info("Complete your first quiz to see your trend!")

    st.divider()
    st.subheader("📓 Recent Mistakes")
    recent_mistakes = db.get_wrong_questions()
    if recent_mistakes:
        for m in recent_mistakes[-3:]:
            with st.expander(f"Question: {m['question'][:50]}..."):
                st.write(f"**Correct:** {m['correct_answer']}")
                st.error(f"**You said:** {m['user_answer']}")
    else:
        st.success("No mistakes tracked yet. Great job!")

# PAGE 2: LIBRARY (The "Vault" Logic)
elif page == "📂 Library":
    st.title("📂 Document Library")
    uploaded_file = st.file_uploader("Upload Notes (PDF/Image)", type=["pdf", "png", "jpg", "jpeg"])
    
    if uploaded_file:
        file_name = uploaded_file.name
        bytes_data = uploaded_file.getvalue()
        file_hash = hashlib.sha256(bytes_data).hexdigest()
        
        # Check the Vault
        existing_doc = db.get_document_by_hash(file_hash)
        
        if existing_doc:
            st.success(f"✨ Found '{file_name}' in your library.")
            if st.button("Load from Vault"):
                with st.spinner("Retrieving and syncing your study materials..."):
                    st.session_state.last_image_name = file_name
                    st.session_state.study_guide = {
                        "summary": existing_doc[0]['ai_summary'],
                        "key_terms": existing_doc[0]['ai_flashcards']
                    }
                    st.session_state.quiz_data = existing_doc[0]['ai_quiz'] if existing_doc[0]['ai_quiz'] else None
                    st.session_state.current_doc_id = existing_doc[0]['id']
                    # Process images for preview/chat
                    st.session_state.content_to_analyze = process_pdf_to_images(bytes_data) if uploaded_file.type == "application/pdf" else [Image.open(BytesIO(bytes_data))]
                    st.info("Loaded! Go to Study Room.")
        else:
            if st.button("Analyze New Document"):
                with st.spinner("🤖 Gemini is reading your notes..."):
                    # Process images
                    imgs = process_pdf_to_images(bytes_data) if uploaded_file.type == "application/pdf" else [Image.open(BytesIO(bytes_data))]
                    st.session_state.content_to_analyze = imgs
                    
                    # Generate Initial Guide
                    data = ai_service.generate_study_guide(imgs)
                    
                    # Save to DB
                    db.save_document(file_name, file_hash, "", data['summary'], data['key_terms'], None)
                    
                    st.session_state.study_guide = data
                    st.session_state.last_image_name = file_name
                    saved_doc = db.get_document_by_hash(file_hash)

                    if saved_doc and isinstance(saved_doc, list) and len(saved_doc) > 0:
                        st.session_state.current_doc_id = saved_doc[0]['id']
                    else:
                        st.error("Document not found in the database.")

                    st.success("Analysis Complete!")

# PAGE 3: STUDY ROOM (Summary & Chat)
elif page == "📖 Study Room":
    if not st.session_state.study_guide:
        st.info("📂 Please load a document from the **Library** first.")
    else:
        st.header(f"📖 Studying: {st.session_state.last_image_name}")
        tab_guide, tab_chat = st.tabs(["📝 Study Guide", "💬 AI Tutor"])
        
        with tab_guide:
            st.markdown(st.session_state.study_guide['summary'])

            if st.session_state.study_guide:
                now = datetime.now().strftime("%Y-%m-%d_%H-%M")
                # Format the text nicely for the file
                guide_text = f"Study Guide: {st.session_state.last_image_name}\n"
                guide_text += f"Date Generated: {now}\n\n"
                guide_text += "--- SUMMARY ---\n" + st.session_state.study_guide['summary'] + "\n\n"
                guide_text += "--- KEY TERMS ---\n"
                for item in st.session_state.study_guide['key_terms']:
                    guide_text += f"{item['term']}: {item['definition']}\n"
                
                st.download_button(
                    label="📥 Download Full Study Guide",
                    data=guide_text,
                    file_name=f"Study_Guide_{st.session_state.last_image_name}_{now}.txt",
                    mime="text/plain"
                )

            if st.button("🔊 Listen to Summary"):
                tts = gTTS(text=st.session_state.study_guide['summary'], lang='en' if language == "English" else 'id')
                b = BytesIO(); tts.write_to_fp(b)
                st.audio(b)
            
            st.divider()
            st.subheader("🎴 Flashcards")
            cols = st.columns(2)
            for i, item in enumerate(st.session_state.study_guide['key_terms']):
                with cols[i % 2]:
                    if st.toggle(f"Reveal: {item['term']}", key=f"flash_{i}"):
                        st.markdown(f'<div class="flashcard">{item["definition"]}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div class="flashcard"><div class="flashcard-term">🔍 {item["term"]}</div></div>', unsafe_allow_html=True)

        with tab_chat:
            chat_container = st.container(height=400)
            for chat in st.session_state.chat_history:
                with chat_container.chat_message("user"): st.write(chat['question'])
                with chat_container.chat_message("assistant"): st.write(chat['answer'])
            
            user_q = st.chat_input("Ask about your notes...")
            if user_q:
                with chat_container.chat_message("user"): st.write(user_q)
                with chat_container.chat_message("assistant"):
                    full_res = ""
                    placeholder = st.empty()
                    for chunk in ai_service.stream_chat(user_q, st.session_state.content_to_analyze, selected_model):
                        if getattr(chunk, "text", None):
                            full_res += chunk.text
                            placeholder.markdown(full_res)
                    
                    db.save_chat_message(st.session_state.current_doc_id, user_q, full_res)
                    st.session_state.chat_history.append({"question": user_q, "answer": full_res})
            
            now = datetime.now().strftime("%Y-%m-%d_%H-%M")
            chat_text = f"Study Session: {st.session_state.last_image_name}\nDate: {now}\n\n"
    
            for chat in st.session_state.chat_history:
                chat_text += f"Q: {chat['question']}\nA: {chat['answer']}\n{'-'*20}\n"

            st.download_button(
                label="📥 Download Chat History",
                data=chat_text,
                file_name=f"Study_Notes_{now}.txt", # <--- PUT DATETIME BACK HERE
                mime="text/plain"
            )

# PAGE 4: QUIZ CENTER
elif page == "🧠 Quiz Center":
    if not st.session_state.study_guide:
        st.info("📂 Please load a document from the **Library** first.")
    else:
        st.header(f"🧠 Quiz: {st.session_state.last_image_name}")
        
        if st.button("✨ Generate New Quiz", use_container_width=True):
            with st.spinner("Drafting questions..."):
                st.session_state.quiz_data = ai_service.generate_quiz(
                    st.session_state.content_to_analyze,
                    selected_model,
                    _seed=random.randint(1, 10000)
                    )
                st.session_state.quiz_submitted = False
                st.rerun()

        if st.session_state.quiz_data:
            if not st.session_state.quiz_submitted:
                with st.form("quiz_form"):
                    current_answers = {}
                    for i, q in enumerate(st.session_state.quiz_data):
                        st.subheader(f"Q{i+1}: {q['question']}")
                        current_answers[i] = st.radio("Options:", q["options"],index=None, key=f"q_{i}", format_func=lambda x: x)
                    
                    submit_button = st.form_submit_button("Submit Quiz")

                    if submit_button:
                        if None in current_answers.values():
                            st.warning("⚠️ Please answer all questions!")
                        else:
                            # 1. Calculate Score
                            score = sum(1 for i, q in enumerate(st.session_state.quiz_data) 
                                    if str(current_answers[i]).startswith(str(q["answer"])))
                            
                            existing_weaknesses = st.session_state.get("weak_topics", [])
                            new_found_mistakes = []
                            # --- STEP 2: TRACK WEAKNESSES ---
                            for i, q in enumerate(st.session_state.quiz_data):
                                if current_answers[i] != q["answer"]:
                                    # Record the topic for the next "Adaptive" generation
                                    if 'topic' in q:
                                        new_found_mistakes.append(q["topic"])
                                    
                                    # Record the mistake in the DB for the "Mistake Inbox"
                                    db.save_wrong_question(
                                        st.session_state.current_doc_id, 
                                        q['question'], 
                                        q['answer'], 
                                        current_answers[i]
                                    )
                            
                            # Update session state with unique topics
                            st.session_state.weak_topics = list(set(new_found_mistakes))
                            # --------------------------------
                            
                            # 2. Update Session State
                            st.session_state.last_score = score
                            st.session_state.user_answers = current_answers
                            st.session_state.quiz_submitted = True
                            
                            # 3. Save result
                            db.save_quiz_result(st.session_state.current_doc_id, score, len(st.session_state.quiz_data))
                            db.save_study_session(st.session_state.current_doc_id, len(st.session_state.quiz_data), score)
                            
                            st.rerun()
                            st.session_state.weak_topics = list(set(existing_weaknesses + new_found_mistakes))
            else:
                # 1. Show the final score
                st.metric("Final Score", f"{st.session_state.last_score} / {len(st.session_state.quiz_data)}")
                
                st.divider()
                st.subheader("📝 Review Your Answers")
                
                # 2. Iterate through quiz data to show correctness
                for i, q in enumerate(st.session_state.quiz_data):
                    user_ans = st.session_state.user_answers.get(i)
                    correct = str(user_ans).startswith(str(q["answer"]))
                    
                    # Use color to indicate success or failure
                    status = "✅ Correct" if correct else "❌ Incorrect"
                    with st.expander(f"Q{i+1}: {q['question']} - {status}"):
                        st.write(f"**Your Answer:** {user_ans}")
                        st.write(f"**Correct Answer:** {q['answer']}")
                        st.info(f"**Explanation:** {q.get('explanation', 'No explanation provided.')}")
                
                st.divider()
                if st.button("✨ Generate Adaptive Quiz", use_container_width=True):
                    with st.spinner("Analyzing your past mistakes..."):
                    # Pass the weak topics to the AI to prioritize those concepts
                        focus_areas = st.session_state.weak_topics 
                
                        st.session_state.quiz_data = ai_service.generate_adaptive_quiz(
                            st.session_state.content_to_analyze, 
                            selected_model,
                            focus_areas=focus_areas,
                            _seed=random.randint(1, 10000)
                        )
                        st.session_state.quiz_submitted = False
                        st.rerun()