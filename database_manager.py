import streamlit as st
import requests

class SupabaseManager:
    def __init__(self):
        self.url = st.secrets["SUPABASE_URL"]
        self.key = st.secrets["SUPABASE_KEY"]
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
    
    # Add this right under your __init__ function
    def _get(self, table, query=""):
        endpoint = f"{self.url}/rest/v1/{table}{query}"
        res = requests.get(endpoint, headers=self.headers)
        return res.json() if res.status_code == 200 else []

    def _post(self, table, data, upsert=False):
        headers = self.headers.copy()
        if upsert:
            headers["Prefer"] = "resolution=merge-duplicates, return=representation"
        
        endpoint = f"{self.url}/rest/v1/{table}"
        res = requests.post(endpoint, headers=headers, json=data)
        return res.json() if res.status_code in [200, 201] else []

    # --- Documents (The Token Saver) ---
    def save_document(self, filename, file_hash, raw_text, summary=None, flashcards=None, quiz_data=None):
        data = {
            "file_name": filename,
            "content_hash": file_hash,
            "raw_text": raw_text,
            "ai_summary": summary,
            "ai_flashcards": flashcards, # Send as dict/list, no json.dumps!
            "ai_quiz": quiz_data
        }
        # Upsert: Updates if hash exists, otherwise inserts.
        headers = {**self.headers, "Prefer": "resolution=merge-duplicates, return=representation"}
        res = requests.post(f"{self.url}/rest/v1/documents", headers=headers, json=data)
        return res.json()[0] if res.status_code in [200, 201] else None

    def get_document_by_hash(self, file_hash):
        # Using the helper we defined, which automatically handles status checks
        res = self._get("documents", f"?content_hash=eq.{file_hash}")
        return res[0] if res else None

    # --- Quiz Results & Analytics ---
    def save_quiz_result(self, doc_id, score, total):
        payload = {"doc_id": doc_id, "score": score, "total_questions": total}
        requests.post(f"{self.url}/rest/v1/quiz_results", headers=self.headers, json=payload)

    def save_wrong_question(self, doc_id, question, correct, user_ans, topic):
        payload = {
            "doc_id": doc_id, 
            "question": question, 
            "correct_answer": correct, 
            "user_answer": user_ans,
            "topic": topic
        }
        requests.post(f"{self.url}/rest/v1/wrong_questions", headers=self.headers, json=payload)

    @st.cache_data(ttl=60)
    def get_top_weak_topics(_self, doc_id):
        # This fetches all wrong questions for this doc
        res = _self._get("wrong_questions", f"?doc_id=eq.{doc_id}")
        if not res: return []
        
        # Simple counting logic
        from collections import Counter
        topics = [r['topic'] for r in res if r.get('topic')]
        return Counter(topics).most_common(3) # Returns [('Topic', count), ...]

    def get_wrong_questions(self, doc_id=None):
        url = f"{self.url}/rest/v1/wrong_questions"
        if doc_id:
            url += f"?doc_id=eq.{doc_id}"
        res = requests.get(url, headers=self.headers)
        return res.json()

    # --- Chat History ---
    def save_chat_message(self, doc_id, question, answer):
        payload = {"doc_id": doc_id, "question": question, "answer": answer}
        requests.post(f"{self.url}/rest/v1/chat_messages", headers=self.headers, json=payload)

    def get_chat_history(self, doc_id):
        res = requests.get(f"{self.url}/rest/v1/chat_messages?doc_id=eq.{doc_id}&order=created_at.asc", headers=self.headers)
        return res.json()
    
    def get_average_score(self):
        res = self._get("quiz_results")
        if not res: return 0
        total = sum((r['score'] / r['total_questions']) for r in res)
        return total / len(res)

    def get_total_questions_practiced(self):
        res = self._get("quiz_results")
        return sum(r['total_questions'] for r in res) if res else 0

    def get_score_trend(self):
        res = self._get("quiz_results", "?select=created_at,score,total_questions&order=created_at.asc")
        return [{"Date": r['created_at'], "Score": r['score']/r['total_questions']} for r in res]
    
    def save_study_session(self, doc_id, questions_answered, score):
        # We reuse the quiz_results table to track session stats
        payload = {
            "doc_id": doc_id, 
            "score": score, 
            "total_questions": questions_answered
        }
        # Using the _post helper we created earlier
        self._post("quiz_results", payload)

    def get_dashboard_stats(self):
        # One request to get all quiz results
        res = self._get("quiz_results")
        if not res:
            return {"avg": 0, "total": 0, "trend": []}
    
        # Do the math in Python (fast!) instead of making more cloud calls
        total_q = sum(r['total_questions'] for r in res)
        avg_score = sum(r['score'] / r['total_questions'] for r in res) / len(res)
    
        return {"avg": avg_score, "total": total_q, "data": res}
    
    @st.cache_data(ttl=600)  # Caches the result for 10 minutes (600 seconds)
    def get_document_by_hash(_self, file_hash):
        # We use the internal _get helper you created
        return _self._get("documents", f"?content_hash=eq.{file_hash}")

    @st.cache_data(ttl=600)
    def get_dashboard_stats(_self):
        # This will now only run once every 10 minutes
        res = _self._get("quiz_results")
        if not res:
            return {"avg": 0, "total": 0}
            
        total_q = sum(r['total_questions'] for r in res)
        # Calculate average safely
        avg_score = sum(r['score'] / r['total_questions'] for r in res) / len(res)
        
        return {"avg": avg_score, "total": total_q}