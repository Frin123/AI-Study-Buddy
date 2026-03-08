import streamlit as st
from google import genai
from PIL import Image
from ai_service import AIService
from file_utils import process_pdf_to_images, generate_study_pdf
from gtts import gTTS
from io import BytesIO
from datetime import datetime
import random
import json
import hashlib
import pandas as pd
from database_manager import DatabaseManager
db = DatabaseManager()

def generate_file_hash(file_bytes):
    """Create a unique hash for the uploaded file."""
    return hashlib.sha256(file_bytes).hexdigest()

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

# --- INITIALIZATION (Add this at the very top of your script) ---
def init_session_state():
    defaults = {
        "study_guide": None,
        "chat_history": [],
        "last_image_name": None,
        "quiz_data": None,
        "user_answers": {},
        "weak_topics": [],
        "quiz_submitted": False,
        "current_doc_id": None,
        "pdf_bytes": None
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

init_session_state()

# --- 3. SIDEBAR ---
with st.sidebar:
    st.title("⚙️ Settings")
    model_choice = st.radio("Mode:", ["🧠 Think Mode", "⚡ Fast Mode"])
    if model_choice == "🧠 Think Mode":
        selected_model = "gemini-3.1-flash-lite-preview"
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
    # 1. Setup
    file_name = uploaded_file.name
    bytes_data = uploaded_file.getvalue()
    file_hash = hashlib.sha256(bytes_data).hexdigest()
    
    if "content_to_analyze" not in st.session_state:
        st.session_state.content_to_analyze = []

    # 2. CHECK THE DATABASE (The Vault)
    existing_doc = db.get_document(file_name)

    if existing_doc:
        # --- CACHE HIT: No AI tokens needed! ---
        if st.session_state.get('last_image_name') != file_name:
            st.success(f"✨ Found '{file_name}' in your library. Loading cached data...")
            
            # Load stored AI results into session state
            st.session_state.study_guide = {
                "summary": existing_doc['ai_summary'],
                "key_terms": json.loads(existing_doc['ai_flashcards']) if isinstance(existing_doc['ai_flashcards'], str) else existing_doc['ai_flashcards']
            }
            # Convert string back to Python list/dict
            if existing_doc['ai_quiz']:
                st.session_state.quiz_data = json.loads(existing_doc['ai_quiz'])
            else:
                st.session_state.quiz_data = None
            # Keep track of the current ID for the "Mistake Inbox" later
            st.session_state.current_doc_id = existing_doc['id']
            st.session_state.last_image_name = file_name
            
            # We still need the images for the UI/Chat display
            if not st.session_state.content_to_analyze:
                with st.spinner("Preparing views..."):
                    bytes_data = uploaded_file.getvalue()
                    st.session_state.content_to_analyze = process_pdf_to_images(bytes_data)
    
    else:
        # --- CACHE MISS: Process with Gemini for the first time ---
        with st.spinner("Analyzing new document... (This uses tokens)"):
            # A. Process file to images/text
            bytes_data = uploaded_file.read()
            if uploaded_file.type == "application/pdf":
                st.session_state.content_to_analyze = process_pdf_to_images(bytes_data)
            else:
                img = Image.open(BytesIO(bytes_data))
                st.session_state.content_to_analyze = [img]

            # B. Clear old state
            st.session_state.last_image_name = file_name
            st.session_state.study_guide = None
            st.session_state.quiz_data = None
            
            # Note: We SAVE to the DB only AFTER the first AI calls are made 
            # in your "Generate" buttons to make sure we have data to store.

    # --- STEP 2: DISPLAY PREVIEW (Instant from memory) ---
    if st.session_state.content_to_analyze:
        st.image(st.session_state.content_to_analyze[0], caption="Preview", width=400)

    # --- STEP 3: AUTO-SUMMARIZE ---
if st.session_state.study_guide is None and st.session_state.content_to_analyze:
    with st.spinner("🤖 Analyzing..."):
        try:
            # 1. CALL THE AI
            data = ai_service.generate_study_guide(st.session_state.content_to_analyze)
            
            # 2. SAVE TO DATABASE (The "Vault")
            db.save_document(
                filename=file_name,
                file_hash=file_hash,
                raw_text="", # Add your text extraction here if needed
                summary=data['summary'],
                flashcards=data['key_terms'], # Manager will JSON stringify this!
                quiz_data=None
            )
            
            # 3. SET STATE
            st.session_state.study_guide = data
            
            # 4. GET THE ID (Crucial for linking quiz results later)
            saved_doc = db.get_document(file_name)
            st.session_state.current_doc_id = saved_doc['id']
            
            st.rerun()
        except Exception as e:
            st.error(f"Analysis Error: {e}")

# --- 5. DISPLAY TABS ---
if st.session_state.study_guide:
    tab1, tab2, tab3, tab4 = st.tabs(["📖 Study Guide", "💬 Chat", "🧠 Quiz", "📊 Analytics"])
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

        # --- DB SYNC LOGIC ---
        # 1. Ensure the session state exists
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []

        # 2. Load from DB if the session state is empty (prevents redundant DB calls)
        doc_id = st.session_state.get('current_doc_id')
        if doc_id and not st.session_state.chat_history:
            # Pull saved messages from your database_manager
            db_history = db.get_chat_history(doc_id)
            # Convert DB format (role/content) to your UI format (question/answer) if necessary
            # If your DB stores pairs, load them here. 
            # For simplicity, let's assume get_chat_history returns the pairs:
            st.session_state.chat_history = db_history

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

                            # --- SAVE TO DB ---
                            # Save the Q&A pair to your new chat_history table
                            db.save_chat_message(doc_id, user_q, full_res)
                            
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

        # 2. VALIDATION & RENDERING
        if st.session_state.quiz_data:
            # The Guardrail: Check if the data is actually a quiz (has 'question' key)
            is_valid = isinstance(st.session_state.quiz_data, list) and \
                    len(st.session_state.quiz_data) > 0 and \
                    'question' in st.session_state.quiz_data[0]

            if is_valid:
                # --- CASE A: QUIZ NOT SUBMITTED (Show Form) ---
                if not st.session_state.quiz_submitted:
                    st.info("💡 Select the best answer for each question and hit 'Check My Answers'.")
                
                    # Dynamic Form Key prevents the "Duplicate Key" error
                    doc_id = st.session_state.get('current_doc_id', 'new')
                    form_key = f"quiz_form_{doc_id}"

                    with st.form(form_key):
                        current_answers = {} 
                        for i, q in enumerate(st.session_state.quiz_data):
                            st.subheader(f"Q{i+1}: {q['question']}")
                        
                            # Handle persistence (index management)
                            current_val = st.session_state.user_answers.get(i)
                            try:
                                idx = q["options"].index(current_val) if current_val in q["options"] else None
                            except:
                                idx = None

                            current_answers[i] = st.radio(
                                "Choose an answer:",
                                q["options"],
                                key=f"q_radio_{i}_{doc_id}", # Unique key per question/doc
                                index=idx
                            )
                            st.divider()

                        submit_quiz = st.form_submit_button("🏁 Check My Answers", use_container_width=True)

                        # 3. CONSOLIDATED GRADING & DATABASE LOGIC
                        if submit_quiz:
                            if None in current_answers.values():
                                st.warning("⚠️ Please answer all questions before submitting.")
                            else:
                                # 1. Update Session State status
                                st.session_state.user_answers = current_answers
                                st.session_state.quiz_submitted = True
                            
                                score = 0
                                temp_weak_topics = []
                                db_mistakes = [] # For the JSON attempt storage

                                # 2. Grade the Quiz
                                for i, q in enumerate(st.session_state.quiz_data):
                                    user_ans = current_answers[i]
                                    # Clean up strings for comparison
                                    if user_ans.strip().lower() == q["answer"].strip().lower():
                                        score += 1
                                    else:
                                        # Add to UI weak topics
                                        temp_weak_topics.append({
                                            "question": q["question"],
                                            "your_answer": user_ans,
                                            "correct_answer": q["answer"],
                                            "explanation": q["explanation"]
                                        })

                                        # DAY 8: Save individual mistake to DB
                                        db.save_wrong_question(doc_id, q["question"], q["answer"], user_ans)
                                    
                                        # Prepare mistake list for the full attempt JSON
                                        db_mistakes.append({
                                            "q": q["question"], 
                                            "a": user_ans, 
                                            "correct": q["answer"]
                                        })

                                # 3. SAVE TO DATABASE
                                # Save the deep details (mistakes as JSON)
                                db.save_quiz_attempt(doc_id, score, len(st.session_state.quiz_data), db_mistakes)
                                # Save the high-level result for quick stats
                                db.save_quiz_result(doc_id, score, len(st.session_state.quiz_data))

                                # 4. Final Session State Updates
                                st.session_state.last_score = score
                                st.session_state.weak_topics = temp_weak_topics
                            
                                if "quiz_history" not in st.session_state:
                                    st.session_state.quiz_history = []
                                    st.session_state.quiz_history.append({"score": score, "total": len(st.session_state.quiz_data)})

                                # 1. Save the Quiz Attempt (Existing)
                                db.save_quiz_attempt(doc_id, score, len(st.session_state.quiz_data), db_mistakes)
        
                                # 2. SAVE THE STUDY SESSION (New Step 2 Code)
                                # This treats the completion of a quiz as the 'end' of a study block
                                db.save_study_session(
                                    doc_id=doc_id,
                                    questions_answered=len(st.session_state.quiz_data),
                                    score=score
                                )
        
                                # ... (rest of your rerun logic) ...
                                st.success("Session recorded! Check the Analytics tab to see your progress.")
                            
                                # 5. Rerun to show the "Results" view (Case B)
                                st.rerun()

                # --- CASE B: QUIZ SUBMITTED (Show Results) ---
                else:
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

                    # 5. ADAPTIVE PRACTICE
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
            else:
                # The Guardrail caught bad data (like flashcards)
                st.warning("⚠️ Saved quiz data is in an old format or invalid. Please click 'Generate New Quiz' above.")
        else:
            st.info("No quiz found for this document. Click 'Generate New Quiz' to get started!")

        # 6. HISTORY (Always at the bottom)
        if st.session_state.quiz_history:
            st.divider()
            st.subheader("📊 Your Progress")
            import pandas as pd
            df = pd.DataFrame(st.session_state.quiz_history)
            df["Accuracy"] = (df["score"] / df["total"].replace(0,1) * 100).round(2)
            st.line_chart(df["Accuracy"])
            st.dataframe(df, use_container_width=True)

    with tab4:
        st.header("📊 Performance Dashboard")
        st.caption("📦 Data stored in local SQLite (Resets on new deployment)")

        # 1. FETCH AGGREGATE STATS
        avg_score = db.get_average_score()
    
        # We query the new study_sessions table for volume stats
        with db.get_connection() as conn:
            cursor = conn.cursor()
            session_stats = cursor.execute("""
                SELECT 
                    SUM(questions_answered) as total_q, 
                    COUNT(*) as total_sessions 
                FROM study_sessions
            """).fetchone()
        
            total_questions = session_stats['total_q'] or 0
            total_sessions = session_stats['total_sessions'] or 0
            total_sessions = session_stats['total_sessions'] if session_stats['total_sessions'] else 0

        # 2. TOP METRICS ROW
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Global Accuracy", f"{round(avg_score * 100, 1)}%")
        with col2:
            st.metric("Questions Practiced", total_questions)
        with col3:
            st.metric("Study Sessions", total_sessions)

        st.divider()

        # 3. PERFORMANCE OVER TIME (Chart)
        st.subheader("📈 Knowledge Growth")
        trend_data = db.get_score_trend()
    
        if trend_data:
            # Convert SQLite rows to a DataFrame for plotting
            df = pd.DataFrame(trend_data)
            df.columns = ["Date", "Score"]
            df["Score"] = df["Score"] * 100
            df["Date"] = pd.to_datetime(df["Date"])
        
            # Plotting the line chart
            st.line_chart(df.set_index("Date"))
        else:
            st.info("Finish your first quiz to see your performance trend!")

        st.divider()

        # 4. THE MISTAKE INBOX (Review)
        st.subheader("📓 Mistake Inbox")
        st.write("Review your most recent errors to turn them into strengths.")
    
        recent_mistakes = db.get_wrong_questions()
    
        if recent_mistakes:
            # Show only the 5 most recent mistakes to keep the UI clean
            for m in recent_mistakes[-5:]:
                with st.expander(f"Question: {m['question'][:60]}..."):
                    st.write(f"**Full Question:** {m['question']}")
                    st.error(f"**Your Answer:** {m['user_answer']}")
                    st.success(f"**Correct Answer:** {m['correct_answer']}")
        else:
            st.success("Clean slate! You haven't made any mistakes yet.")


        # 5. DANGER ZONE
        st.markdown("---")
        with st.expander("⚠️ Danger Zone"):
            st.write("Deleting your history is permanent and cannot be undone.")
            if st.button("🗑️ Clear All Study History", use_container_width=True, type="primary"):
                db.clear_all_history()
                st.session_state.quiz_history = []
                st.session_state.last_score = 0
                st.success("History wiped! Starting with a clean slate.")
                st.rerun()