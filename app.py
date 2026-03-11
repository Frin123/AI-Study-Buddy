import streamlit as st
from google import genai
from PIL import Image
from ai_service import AIService
from file_utils import process_pdf_to_images, generate_study_pdf
from gtts import gTTS
from io import BytesIO
import random
from datetime import datetime
import hashlib
import pandas as pd
from database_manager import SupabaseManager
import time
from ai_service import get_ai_service

# --- 1. INITIALIZATION & CONFIG ---
db = SupabaseManager()
st.set_page_config(page_title="AI Study Buddy 2026", layout="wide")

@st.cache_data
def cached_pdf_processing(bytes_data):
    return process_pdf_to_images(bytes_data)

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
            "study_guide": None, 
            "chat_history": [], 
            "last_image_name": None,
            "content_to_analyze": None, 
            "quiz_data": None, 
            "user_answers": {},
            "weak_topics": [], 
            "quiz_submitted": False, 
            "last_score": 0,
            "quiz_history": [], 
            "current_doc_id": None,  # <--- THIS IS CRITICAL
            "pdf_bytes": None,
            "user_id": "Guest",
            "prev_user_id": "Guest",
        }
        for key, val in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = val

    # Run it once at the very top of your script
init_state()


# This ensures that if the page refreshes, we reload the chat history
if st.session_state.get("current_doc_id") and not st.session_state.get("chat_history"):
    with st.spinner("Syncing chat history..."):
        history = db.get_chat_history(st.session_state.current_doc_id, st.session_state.user_id)
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
    st.title("🎓 AI Study Buddy")
    
    # 1. Check Auth Status
    current_user = st.session_state.get("user_id", "Guest")
    is_authenticated = current_user != "Guest"

    # 2. Navigation (You can disable these if not authenticated if you want)
    page = st.radio("Navigation", ["🏠 Dashboard", "📂 Library", "📖 Study Room", "🧠 Quiz Center"])

    st.divider()

    # 3. User Account Section
    st.subheader("👤 Account")
    
    if not is_authenticated:
        # --- LOGIN VIEW ---
        user_input = st.text_input(
            "Enter Student ID to Begin:", 
            value="", 
            placeholder="e.g. Student_123",
            key="sidebar_user_input"
        )

        if user_input: 
            st.session_state.user_id = user_input
            st.session_state.prev_user_id = user_input
            
            # --- THE UPGRADE: Auto-load recent work ---
            # We ask the DB: "Does this user have any documents already?"
            recent_doc = db.get_user_recent_document(user_input)
            
            if recent_doc:
                st.session_state.current_doc_id = recent_doc['id']
                st.session_state.study_guide = {
                    "summary": recent_doc['ai_summary'],
                    "key_terms": recent_doc['ai_flashcards']
                }
                # Load existing chat history for this doc too
                history = db.get_chat_history(recent_doc['id'], user_input)
                st.session_state.chat_history = history if history else []
                st.toast(f"✅ Welcome back, {user_input}! Recent data loaded.")
            else:
                st.toast(f"✅ Account '{user_input}' created/loaded!")

            st.rerun()
            
        st.warning("⚠️ Please enter a User ID to unlock features.")
    
    else:
        # --- LOGGED IN VIEW ---
        st.success(f"Logged in as: **{current_user}**")
        
        # The Logout Button
        if st.button("🚪 Logout", use_container_width=True):
            # Reset everything back to Guest state
            st.session_state.user_id = "Guest"
            st.session_state.prev_user_id = "Guest"
            st.session_state.current_doc_id = None
            st.session_state.study_guide = None
            st.session_state.quiz_data = None
            st.session_state.chat_history = []
            st.toast("Logged out successfully.")
            st.rerun()

    st.divider()

    # --- SETTINGS & AI SERVICE ---
    with st.expander("⚙️ Preferences"):
        model_choice = st.radio("Model:", ["🧠 Think Mode", "⚡ Fast Mode"])
        language = st.selectbox("Language", ["Bahasa Indonesia", "English"])

    ai_service = get_ai_service(st.session_state.client, language)

    st.divider()
    if st.button("🧹 Clear Workspace", use_container_width=True):
        st.session_state.study_guide = None
        st.session_state.quiz_data = None
        st.session_state.chat_history = []
        st.rerun()

# --- 4. PAGE LOGIC ---

# PAGE 1: DASHBOARD
if page == "🏠 Dashboard":
    # Check authentication
    if not st.session_state.get("user_id") or st.session_state.user_id == "Guest":
        # --- THE WELCOME LANDING PAGE ---
        st.title("🚀 Welcome to AI Study Buddy!")
        st.markdown("""
        ### Your Personal AI-Powered Learning Assistant.
        To get started and track your progress, please **enter your Student ID in the sidebar**.
        
        **What you can do here:**
        * 📂 **Upload Notes:** Turn PDFs or Images into structured study guides.
        * 📖 **Interactive Study:** Listen to summaries and flip flashcards.
        * 💬 **AI Tutor:** Chat with your documents for deep explanations.
        * 🧠 **Smart Quizzes:** Test yourself with AI-generated questions.
        """)
        
        # Using a nice visual container for the instruction
        with st.container(border=True):
            st.info("👈 **Action Required:** Look at the sidebar on the left and enter any ID (like your name) to unlock your dashboard.")
            
    else:
        # --- THE ACTUAL DASHBOARD (Only shows after login) ---
        st.title(f"🚀 Welcome back, {st.session_state.user_id}!")
        st.caption("Here's your learning progress at a glance.")
    
        # 1. Summary Cards
        with st.container(border=True):
            col1, col2, col3 = st.columns(3)
        
            avg_score = db.get_average_score(st.session_state.user_id) or 0
            accuracy_pct = round(avg_score * 100, 1)
        
            # Accuracy Metric
            col1.metric("Global Accuracy", f"{accuracy_pct}%", 
                    delta=f"{round(accuracy_pct - 70, 1)}% vs Target" if accuracy_pct > 0 else None)
        
            # Quantity Metric
            total_q = db.get_total_questions_practiced(st.session_state.user_id) or 0
            col2.metric("Questions Practiced", total_q)
        
            # Dynamic Rank Metric (Replaces the Alpha/Sigma)
            if total_q < 500: rank = "Apprentice"
            elif total_q < 5000: rank = "Scholar"
            else: rank = "Master"
        
            col3.metric("Knowledge Rank", rank, help="Your rank grows based on total questions answered.")

        st.write("") 

        # 2. Main Analytics Row
        chart_col, weak_col = st.columns([2, 1])

        with chart_col:
            st.subheader("📈 Knowledge Growth")
            trend_data = db.get_score_trend(st.session_state.user_id)
            if trend_data:
                df_trend = pd.DataFrame(trend_data)
                df_trend["Date"] = pd.to_datetime(df_trend["Date"]) 
                df_trend["Date"] = df_trend["Date"].dt.strftime('%d %b') 
                df_trend["Score"] = pd.to_numeric(df_trend["Score"], errors="coerce") * 100
            
                with st.container(border=True):
                    st.line_chart(df_trend.set_index("Date"), color="#ff4b4b")
            else:
                st.info("No quiz data found yet. Start your first quiz!")

        with weak_col:
            st.subheader("🎯 Danger Zones")
            if st.session_state.get("current_doc_id"):
                weak_topics = db.get_top_weak_topics(st.session_state.user_id, st.session_state.current_doc_id)
                if weak_topics:
                    df_weak = pd.DataFrame(weak_topics, columns=['Topic', 'Errors'])
                    with st.container(border=True):
                        st.bar_chart(df_weak.set_index('Topic'), color="#ffa500")
                else:
                    st.success("No weak spots! You're crushing it.")
            else:
                st.info("Load notes to see analysis.")

        # 3. Recent Mistakes Section
        st.divider()
        st.subheader("📓 Recent Mistakes & Feedback")
        recent_mistakes = db.get_wrong_questions(user_id=st.session_state.user_id)
    
        if recent_mistakes:
            for m in recent_mistakes[-3:]:
                with st.status(f"Issue in: {m.get('topic', 'Key Concept')}", state="error"):
                    st.write(f"**Question:** {m['question']}")
                    st.write(f"✅ **Correct Answer:** {m['correct_answer']}")
                    st.error(f"❌ **Your Choice:** {m['user_answer']}")
        else:
            st.success("No mistakes tracked yet. Stay sharp!")

# PAGE 2: LIBRARY (The "Vault" Logic)
elif page == "📂 Library":
    st.title("📂 Document Library")
    st.caption("Upload new study materials or access your previously saved notes.")
    
    # Handle the success message cleanly
    if "load_message" in st.session_state:
        st.toast(st.session_state.load_message, icon="✅")
        del st.session_state.load_message

    # Organize inputs into tabs for a cleaner UI
    tab_upload, tab_paste = st.tabs(["📤 Upload File", "✍️ Paste Notes"])

    with tab_upload:
        uploaded_file = st.file_uploader("Drop your PDF or image here", type=["pdf", "png", "jpg", "jpeg"])
        
        if uploaded_file:
            file_name = uploaded_file.name
            bytes_data = uploaded_file.getvalue()
            file_hash = hashlib.sha256(bytes_data).hexdigest()
            
            # Check the Vault
            existing_doc = db.get_document_by_hash(file_hash, st.session_state.user_id)
            
            if existing_doc:
                # Use a bordered container to highlight the Vault match
                with st.container(border=True):
                    st.success(f"✨ **{file_name}** is already in your Vault!")
                    st.write("Save time and AI credits by loading your previous analysis.")
                    
                    if st.button("📥 Load from Vault", type="primary", use_container_width=True):
                        with st.spinner("Retrieving your study materials..."):
                            st.session_state.current_doc_id = existing_doc['id']
                            st.session_state.study_guide = {
                                "summary": existing_doc['ai_summary'],
                                "key_terms": existing_doc['ai_flashcards']
                            }
                            st.session_state.quiz_data = existing_doc['ai_quiz'] if existing_doc['ai_quiz'] else None
                            st.session_state.chat_history = [] 
            
                            # Load the new history immediately
                            history = db.get_chat_history(st.session_state.current_doc_id, st.session_state.user_id)
                            if history:
                                st.session_state.chat_history = history
                                
                            # Process images for preview/chat
                            st.session_state.content_to_analyze = cached_pdf_processing(bytes_data) if uploaded_file.type == "application/pdf" else [Image.open(BytesIO(bytes_data))]
                            st.session_state.last_image_name = file_name # Ensure name updates!
                            
                            st.session_state.load_message = "Document loaded! Head over to the Study Room."
                            st.rerun()
            else:
                st.info("New document detected. Ready for AI processing.")
                if st.button("🚀 Analyze New Document", type="primary", use_container_width=True):
                    with st.spinner("🤖 Gemini is reading your notes... This takes a few seconds."):
                        # 1. Process and Analyze
                        imgs = cached_pdf_processing(bytes_data) if uploaded_file.type == "application/pdf" else [Image.open(BytesIO(bytes_data))]
                        data = ai_service.generate_study_guide(imgs)
            
                        # 2. IDK Protocol Check
                        if data.get("error") == "ILLEGIBLE":
                            st.error(f"⚠️ AI Clarity Issue: {data.get('reason')}")
                        else:
                            # 3. Fetch fresh record
                            saved_doc = db.save_document(
                                file_name,
                                file_hash,
                                st.session_state.user_id,
                                "PDF/Image Content",
                                data['summary'],
                                data['key_terms'],
                                None
                            )
                            if saved_doc:
                                # 4. Synchronize all state at once
                                st.session_state.current_doc_id = saved_doc['id']
                                st.session_state.study_guide = data
                                st.session_state.last_image_name = saved_doc.get('file_name', file_name)
                                st.session_state.content_to_analyze = imgs
                                st.session_state.chat_history = []
                                
                                st.session_state.load_message = "Analysis Complete! Ready in the Study Room."
                                st.rerun() 
                            else:
                                st.error("Failed to retrieve document after saving. Please try again.")

    with tab_paste:
        st.markdown("### Quick Paste")
        st.caption("Don't have a file? Just paste your lecture notes or text directly.")
        doc_title = st.text_input("Note Title (e.g., Geometry Basics)", placeholder="Enter a descriptive title...")
        pasted_text = st.text_area("Paste your study notes here:", height=200, placeholder="Paste your text here...")
        
        if st.button("🚀 Analyze Text", type="primary", use_container_width=True):
            if pasted_text and doc_title:
                with st.spinner("Analyzing text..."):
                    data = ai_service.generate_study_guide(pasted_text)
            
                    if data.get("error"):
                        st.error(f"AI Issue: {data.get('reason')}")
                    else:
                        file_hash = hashlib.sha256(pasted_text.encode()).hexdigest()

                        saved_doc = db.save_document(
                            doc_title, file_hash, st.session_state.user_id,
                            pasted_text, data['summary'], data['key_terms'], None
                        )

                        if saved_doc:
                            st.session_state.current_doc_id = saved_doc['id']
                            
                        st.session_state.study_guide = data
                        st.session_state.last_image_name = doc_title
                        st.session_state.chat_history = [] 
                        
                        st.session_state.load_message = "Manual notes processed! Ready in Study Room."
                        st.rerun()
            else:
                st.warning("⚠️ Please provide both a title and some text content.")

# PAGE 3: STUDY ROOM (Summary & Chat)
elif page == "📖 Study Room":
    if not st.session_state.get("study_guide"):
        # Polished Empty State
        st.warning("📂 No document loaded into active memory.")
        st.info("Please head over to the **Library** to upload or select a document to study.")
    else:
        # 1. Dynamic Header
        doc_name = st.session_state.get('last_image_name', 'Your Notes')
        st.title(f"📖 Studying: {doc_name}")
        
        tab_guide, tab_chat = st.tabs(["📝 Study Guide", "💬 AI Tutor"])
        
        # --- TAB 1: STUDY GUIDE ---
        with tab_guide:
            st.subheader("Executive Summary")
            # Wrap summary in a container for readability
            with st.container(border=True):
                st.markdown(st.session_state.study_guide['summary'])

            # 2. Action Bar (Columns for buttons)
            col_audio, col_down = st.columns(2)
            
            with col_audio:
                if st.button("🔊 Listen to Summary", use_container_width=True):
                    with st.spinner("Generating audio..."):
                        # Safe default to English if 'language' variable isn't in scope
                        lang_choice = 'en' if globals().get("language", "English") == "English" else 'id'
                        tts = gTTS(text=st.session_state.study_guide['summary'], lang=lang_choice)
                        b = BytesIO()
                        tts.write_to_fp(b)
                        st.audio(b)
                        
            with col_down:
                now = datetime.now().strftime("%Y-%m-%d_%H-%M")
                guide_text = f"Study Guide: {doc_name}\nDate: {now}\n\n"
                guide_text += "--- SUMMARY ---\n" + st.session_state.study_guide['summary'] + "\n\n"
                guide_text += "--- KEY TERMS ---\n"
                for item in st.session_state.study_guide.get('key_terms', []):
                    guide_text += f"{item['term']}: {item['definition']}\n"
                
                st.download_button(
                    label="📥 Download Full Guide (.txt)",
                    data=guide_text,
                    file_name=f"Study_Guide_{now}.txt",
                    mime="text/plain",
                    use_container_width=True
                )
            
            st.divider()
            
            # 3. Native Flashcard Layout
            st.subheader("🎴 Flashcards")
            terms = st.session_state.study_guide.get('key_terms', [])
            
            if terms:
                cols = st.columns(2)
                for i, item in enumerate(terms):
                    # Distribute cards evenly across the 2 columns
                    with cols[i % 2]:
                        # A bordered container acts as the physical "card"
                        with st.container(border=True):
                            st.markdown(f"**{item['term']}**")
                            if st.toggle("Flip Card", key=f"flash_{i}"):
                                st.info(item['definition'])
            else:
                st.info("No flashcards generated for this document.")

        # --- TAB 2: AI TUTOR ---
        with tab_chat:
            # Header and Download button side-by-side
            head_col, down_col = st.columns([3, 1])
            with head_col: 
                st.subheader("Ask questions about your notes")
            with down_col:
                now = datetime.now().strftime("%Y-%m-%d_%H-%M")
                chat_text = f"Study Session: {doc_name}\nDate: {now}\n\n"
                for chat in st.session_state.get("chat_history", []):
                    chat_text += f"Q: {chat['question']}\nA: {chat['answer']}\n{'-'*20}\n"
                
                st.download_button(
                    label="📥 Export Chat",
                    data=chat_text,
                    file_name=f"Chat_Log_{now}.txt",
                    mime="text/plain",
                    use_container_width=True
                )

            # Chat Interface
            chat_container = st.container(height=500, border=True)
            
            if not st.session_state.chat_history:
                chat_container.info("👋 Hi! I'm your AI Tutor. Ask me to explain a concept, summarize a section, or quiz you on these notes!")
                
            for chat in st.session_state.chat_history:
                with chat_container.chat_message("user"): st.write(chat['question'])
                with chat_container.chat_message("assistant"): st.write(chat['answer'])
            
            user_q = st.chat_input("Ask a question about this document...")
            if user_q:
                with chat_container.chat_message("user"): st.write(user_q)
                with chat_container.chat_message("assistant"):
                    full_res = ""
                    placeholder = st.empty()
                    try:
                        model_choice = globals().get("selected_model", "gemini-2.5-flash") 
                        for chunk in ai_service.stream_chat(user_q, st.session_state.content_to_analyze, model_choice):
                            if getattr(chunk, "text", None):
                                full_res += chunk.text
                                placeholder.markdown(full_res)
                    except Exception as e:
                        st.error("⚠️ AI response failed. Please try again.")

                # Save and append
                db.save_chat_message(st.session_state.current_doc_id, user_q, full_res, st.session_state.user_id)
                st.session_state.chat_history.append({"question": user_q, "answer": full_res})
                st.rerun() # Force a quick rerun so the input clears and chat stays pinned

# PAGE 4: QUIZ CENTER
elif page == "🧠 Quiz Center":
    if not st.session_state.get("study_guide"):
        st.warning("📂 No document loaded into active memory.")
        st.info("Please head over to the **Library** to upload or select a document to study.")
    else:
        doc_name = st.session_state.get('last_image_name', 'Your Notes')
        st.title("🧠 Knowledge Check")
        st.caption(f"Testing your knowledge on: **{doc_name}**")
        
        # Top-level quiz controls
        col1, col2 = st.columns([2, 1])
        with col1:
            st.write("Generate a fresh 5-question multiple-choice quiz based on your document.")
        with col2:
            if st.button("✨ Generate New Quiz", use_container_width=True, type="primary"):
                with st.spinner("Drafting questions..."):
                    st.session_state.quiz_data = ai_service.generate_quiz(
                        st.session_state.content_to_analyze,
                        globals().get("selected_model", "gemini-2.5-flash"), # Safe fallback
                        _seed=random.randint(1, 10000)
                    )
                    st.session_state.quiz_submitted = False
                st.rerun()

        st.divider()

        # --- ACTIVE QUIZ STATE ---
        if st.session_state.get("quiz_data"):
            if not st.session_state.get("quiz_submitted"):
                with st.form("quiz_form", border=False):
                    current_answers = {}
                    
                    # 1. Display Questions as "Cards"
                    for i, q in enumerate(st.session_state.quiz_data):
                        with st.container(border=True):
                            st.subheader(f"Question {i+1}")
                            st.write(f"**{q['question']}**")
                            current_answers[i] = st.radio("Select your answer:", q["options"], index=None, key=f"q_{i}", format_func=lambda x: x)
                    
                    st.write("") # Spacing
                    submit_button = st.form_submit_button("Submit Answers", use_container_width=True, type="primary")

                    if submit_button:
                        if None in current_answers.values():
                            st.error("⚠️ Please answer all questions before submitting!")
                        else:
                            with st.spinner("📊 Calculating score and saving progress..."):
                                # Calculate Score
                                score = sum(1 for i, q in enumerate(st.session_state.quiz_data) 
                                        if str(current_answers[i]).startswith(str(q["answer"])))
                            
                                existing_weaknesses = st.session_state.get("weak_topics", [])
                                new_found_mistakes = []
                                
                                # Track Weaknesses
                                for i, q in enumerate(st.session_state.quiz_data):
                                    if current_answers[i] != q["answer"]:
                                        topic_name = q.get('topic', 'General Concepts')
                                        new_found_mistakes.append(topic_name)
                                        db.save_wrong_question(
                                            st.session_state.current_doc_id, 
                                            q['question'], q['answer'], current_answers[i],
                                            topic_name, st.session_state.user_id
                                        )
                            
                                # Update State
                                st.session_state.weak_topics = list(set(existing_weaknesses + new_found_mistakes))
                                st.session_state.last_score = score
                                st.session_state.user_answers = current_answers
                                st.session_state.quiz_submitted = True
                            
                                # Save Results
                                db.save_quiz_result(st.session_state.current_doc_id, score, len(st.session_state.quiz_data), st.session_state.user_id)
                                db.save_study_session(st.session_state.current_doc_id, len(st.session_state.quiz_data), score, st.session_state.user_id)
                            
                            st.rerun()
                            
            # --- RESULTS STATE ---
            else:
                total_q = len(st.session_state.quiz_data)
                score = st.session_state.last_score
                pct = int((score / total_q) * 100)
                
                # 2. Celebration for Perfect Score!
                if score == total_q:
                    st.balloons()
                    st.success("🎉 **Perfect Score!** You absolutely crushed it.")
                elif pct >= 70:
                    st.info(f"👍 **Great job!** You passed with {pct}%.")
                else:
                    st.warning(f"📚 **Keep practicing!** You scored {pct}%. Review your mistakes below.")

                # Big Score Display
                col_score, col_pct = st.columns(2)
                col_score.metric("Points", f"{score} / {total_q}")
                col_pct.metric("Accuracy", f"{pct}%")
                
                st.divider()
                st.subheader("📝 Review Your Answers")
                
                # 3. Clean Review Layout
                for i, q in enumerate(st.session_state.quiz_data):
                    user_ans = st.session_state.user_answers.get(i)
                    correct = str(user_ans).startswith(str(q["answer"]))
                    
                    status = "✅ Correct" if correct else "❌ Incorrect"
                    with st.expander(f"Q{i+1}: {q['question'][:50]}... ({status})"):
                        st.write(f"**Question:** {q['question']}")
                        if correct:
                            st.success(f"**Your Answer:** {user_ans}")
                        else:
                            st.error(f"**Your Answer:** {user_ans}")
                            st.success(f"**Correct Answer:** {q['answer']}")
                        
                        st.info(f"💡 **Explanation:** {q.get('explanation', 'No explanation provided.')}")
                
                st.divider()
                
                # 4. Adaptive Quiz Pitch
                st.markdown("### 🎯 Still struggling?")
                st.caption("Generate a targeted quiz focusing *only* on the topics you got wrong today.")
                if st.button("✨ Generate Adaptive Quiz", use_container_width=True):
                    with st.spinner("Analyzing your past mistakes..."):
                        focus_areas = st.session_state.get("weak_topics", [])
                        st.session_state.quiz_data = ai_service.generate_adaptive_quiz(
                            st.session_state.content_to_analyze, 
                            globals().get("selected_model", "gemini-2.5-flash"),
                            focus_areas=focus_areas,
                            _seed=random.randint(1, 10000)
                        )
                        st.session_state.quiz_submitted = False
                    st.rerun()