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
        endpoint = f"{self.url}/rest/v1/{table}"

        if upsert:
            headers["Prefer"] = "resolution=merge-duplicates, return=representation"
            endpoint += "?on_conflict=content_hash,user_id"

        res = requests.post(endpoint, headers=headers, json=data)

        if res.status_code not in [200, 201]:
            print("SUPABASE ERROR:", res.status_code)
            print(res.text)

        return res.json() if res.status_code in [200, 201] else []

    # --- Documents (The Token Saver) ---
    def save_document(self, filename, file_hash, user_id, raw_text, summary=None, flashcards=None, quiz_data=None):
        data = {
            "file_name": filename,
            "content_hash": file_hash,
            "user_id": user_id,
            "raw_text": raw_text,
            "ai_summary": summary,
            "ai_flashcards": flashcards, # Send as dict/list, no json.dumps!
            "ai_quiz": quiz_data
        }
        # Upsert: Updates if hash exists, otherwise inserts.
        result = self._post("documents", data, upsert=True)
        return result[0] if result else None

    @st.cache_data(ttl=600)
    def get_document_by_hash(_self, file_hash, user_id):
        query = f"?content_hash=eq.{file_hash}&user_id=eq.{user_id}"
        res = _self._get("documents", query)
        return res[0] if res else None

    # --- Quiz Results & Analytics ---
    def save_quiz_result(self, doc_id, score, total, user_id):
        # Use the internal _post helper
        payload = {"doc_id": doc_id, "user_id": user_id, "score": score, "total_questions": total}
        return self._post("quiz_results", payload)

    def save_wrong_question(self, doc_id, question, correct, user_ans, topic, user_id):
        payload = {
            "doc_id": doc_id, 
            "user_id": user_id,
            "question": question, 
            "correct_answer": correct, 
            "user_answer": user_ans,
            "topic": topic
        }
        return self._post("wrong_questions", payload)

    @st.cache_data(ttl=60)
    def get_top_weak_topics(_self, user_id, doc_id):
        # Pass the user_id into the fetcher
        res = _self.get_wrong_questions(user_id, doc_id)
        if not res: return []
        
        from collections import Counter
        topics = [r['topic'] for r in res if r.get('topic')]
        return Counter(topics).most_common(3) # Returns [('Topic', count), ...]

    def get_wrong_questions(self, user_id, doc_id=None):
        query = f"?user_id=eq.{user_id}"
        if doc_id:
            query += f"&doc_id=eq.{doc_id}"
        return self._get("wrong_questions", query)

    # --- Chat History ---
    def save_chat_message(self, doc_id, question, answer, user_id):
        # The guard clause must return early before any request is made
        if not doc_id:
            # Print a clear error to the terminal so you know it happened
            print(f"CRITICAL ERROR: Cannot save chat. doc_id is {doc_id}")
            return None
            
        payload = {"doc_id": doc_id, "user_id": user_id, "question": question, "answer": answer}
        return self._post("chat_messages", payload)
    
    def get_chat_history(self, doc_id, user_id):
        # We filter by doc_id AND user_id to keep the conversation private
        query = f"?doc_id=eq.{doc_id}&user_id=eq.{user_id}&order=created_at.asc"
        return self._get("chat_messages", query)
    
    def get_average_score(self, user_id):
        res = self._get("quiz_results", f"?user_id=eq.{user_id}")
        if not res: return 0
        total = sum((r['score'] / r['total_questions']) for r in res)
        return total / len(res)

    def get_total_questions_practiced(self, user_id):
        res = self._get("quiz_results", f"?user_id=eq.{user_id}")
        return sum(r['total_questions'] for r in res) if res else 0

    def get_score_trend(self, user_id):
        query = f"?user_id=eq.{user_id}&select=created_at,score,total_questions&order=created_at.asc"
        res = self._get("quiz_results", query)
        return [{"Date": r['created_at'], "Score": r['score']/r['total_questions']} for r in res]
    
    def save_study_session(self, doc_id, questions_answered, score, user_id):
        # We reuse the quiz_results table to track session stats
        payload = {
            "doc_id": doc_id, 
            "user_id": user_id,
            "score": score, 
            "total_questions": questions_answered
        }
        # Using the _post helper we created earlier
        self._post("quiz_results", payload)
    
    
    @st.cache_data(ttl=600)
    def get_dashboard_stats(self, user_id):
        # Filter by user_id in the URL query
        res = self._get("quiz_results", f"?user_id=eq.{user_id}")
        
        if not res:
            return {"avg": 0, "total": 0, "data": []}
    
        total_q = sum(r['total_questions'] for r in res)
        avg_score = sum(r['score'] / r['total_questions'] for r in res) / len(res)
    
        return {"avg": avg_score, "total": total_q, "data": res}
    
    def get_user_recent_document(self, user_id):
        """Fetches the most recently active document for a specific user."""
        try:
            response = self.supabase.table("documents")\
                .select("*")\
                .eq("user_id", user_id)\
                .order("created_at", descending=True)\
                .limit(1)\
                .execute()
        
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error fetching recent doc: {e}")
            return None
    