import sqlite3
import json

class DatabaseManager:
    def __init__(self, db_name="study_tool.db"):
        self.db_name = db_name
        self.init_db()

    def get_connection(self):
        """Returns a connection that allows accessing columns by name."""
        conn = sqlite3.connect(self.db_name, timeout=10)
        conn.row_factory = sqlite3.Row # The magic line
        return conn

    def init_db(self):
        """Create database tables if they don't exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # USERS TABLE
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # DOCUMENTS TABLE (Token Saver)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT,
                file_hash TEXT UNIQUE,
                raw_text TEXT,
                ai_summary TEXT,
                ai_flashcards TEXT,
                ai_quiz TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # QUIZ HISTORY TABLE
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS quiz_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER,
                score INTEGER,
                total_questions INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doc_id) REFERENCES documents (id)
            )
            """)

            # WRONG QUESTIONS TABLE (for Mistake Inbox)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS wrong_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER,
                question TEXT,
                correct_answer TEXT,
                user_answer TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doc_id) REFERENCES documents (id)
            )
            """)

            cursor.execute('''
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER,
                score INTEGER,
                total_questions INTEGER,
                mistakes_json TEXT,  -- Stores the questions you got wrong as JSON
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doc_id) REFERENCES documents (id)
            )
            ''')

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER,
                start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                end_time TIMESTAMP,
                questions_answered INTEGER DEFAULT 0,
                score INTEGER DEFAULT 0,
                FOREIGN KEY (doc_id) REFERENCES documents (id)
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER,
                question TEXT,
                answer TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doc_id) REFERENCES documents (id)
            )
            """)

            conn.commit()

    # -------------------------------
    # DOCUMENT MANAGEMENT
    # -------------------------------

    def save_document(self, filename, file_hash, raw_text, summary=None, flashcards=None, quiz_data=None):
        """Save or update a document. Automatically handles JSON conversion."""
        
        # PRO TWEAK: Convert lists/dicts to strings internally
        if flashcards and not isinstance(flashcards, str):
            flashcards = json.dumps(flashcards)
        if summary and not isinstance(summary, str):
            summary = json.dumps(summary)
        if quiz_data and not isinstance(quiz_data, str):
            quiz_data = json.dumps(quiz_data)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO documents (filename, file_hash, raw_text, ai_summary, ai_flashcards, ai_quiz)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_hash) DO UPDATE SET
                filename=excluded.filename,
                raw_text=excluded.raw_text,
                ai_summary=excluded.ai_summary,
                ai_flashcards=excluded.ai_flashcards,
                ai_quiz=excluded.ai_quiz
                """, (filename, file_hash, raw_text, summary, flashcards, quiz_data))
            conn.commit()

    def get_document(self, filename):
        """Retrieve document by filename."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM documents WHERE filename = ?", (filename,))
            return cursor.fetchone()

    def get_document_by_id(self, doc_id):
        """Retrieve document using ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
            return cursor.fetchone()

    # -------------------------------
    # QUIZ HISTORY & ANALYTICS
    # -------------------------------

    def save_quiz_result(self, doc_id, score, total_questions):
        """Save quiz results."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO quiz_history (doc_id, score, total_questions)
            VALUES (?, ?, ?)
            """, (doc_id, score, total_questions))
            conn.commit()

    def get_average_score(self):
        """Calculate global average score."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT AVG(score * 1.0 / total_questions) FROM quiz_history")
            result = cursor.fetchone()
            return result[0] if result[0] else 0

    def get_score_trend(self):
        """Get scores over time for charts."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT timestamp, (score * 1.0 / total_questions) * 100
            FROM quiz_history
            ORDER BY timestamp
            """)
            return cursor.fetchall()
    
    def save_quiz_attempt(self, doc_id, score, total, mistakes):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO quiz_attempts (doc_id, score, total_questions, mistakes_json)
                VALUES (?, ?, ?, ?)
            ''', (doc_id, score, total, json.dumps(mistakes)))
            conn.commit()

    # -------------------------------
    # WRONG QUESTIONS (Mistake Inbox)
    # -------------------------------

    def save_wrong_question(self, doc_id, question, correct_answer, user_answer):
        """Save incorrect answers."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO wrong_questions (doc_id, question, correct_answer, user_answer)
            VALUES (?, ?, ?, ?)
            """, (doc_id, question, correct_answer, user_answer))
            conn.commit()

    def get_wrong_questions(self, doc_id=None):
        """Retrieve mistakes for Mistake Inbox."""
        query = "SELECT question, correct_answer, user_answer FROM wrong_questions"
        params = ()
        if doc_id:
            query += " WHERE doc_id = ?"
            params = (doc_id,)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
        
    def save_study_session(self, doc_id, questions_answered, score):
        """Closes the current session by recording the end time and stats."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # We assume the session started when they opened the doc
            # This query finds the most recent 'open' session for this doc and updates it
            cursor.execute("""
                INSERT INTO study_sessions (doc_id, questions_answered, score, end_time)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (doc_id, questions_answered, score))
            conn.commit()
        
    def clear_all_history(self):
        """Wipes all user progress data but keeps the uploaded documents."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM quiz_history")
            cursor.execute("DELETE FROM quiz_attempts")
            cursor.execute("DELETE FROM wrong_questions")
            cursor.execute("DELETE FROM study_sessions")
            conn.commit()


    def save_chat_message(self, doc_id, role, content):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO chat_history (doc_id, question, answer) VALUES (?, ?, ?)",
                (doc_id, role, content)
            )
            conn.commit()

    def get_chat_history(self, doc_id):
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT question, answer FROM chat_history WHERE doc_id = ? ORDER BY timestamp ASC",
                (doc_id,)
            )
            return [dict(row) for row in cursor.fetchall()]