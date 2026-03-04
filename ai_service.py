import json
from google.genai import types

class AIService:
    def __init__(self, client, language="English"):
        self.client = client
        self.language = language
        self.sys_instr = f"""
        You are an expert tutor. Always respond in {language}. 
        When asked to summarize or answer based on the whole document, 
        be structured and concise. Use bullet points. 
        If the content is too long, focus on the most important academic points first.
        """

    def get_model(self, task_type, user_choice="gemini-2.5-flash"):
        """Centralized model router."""
        if task_type == "auto":
            return "gemini-2.5-flash" # Use the reliable one for JSON
        return user_choice

    def generate_study_guide(self, content_list):
        """Analyzes images/PDF pages and returns structured JSON."""
        model_config = types.GenerateContentConfig(
            system_instruction=self.sys_instr,
            response_mime_type='application/json',
            response_schema={'type': 'object', 'properties': {
                'summary': {'type': 'string'},
                'key_terms': {'type': 'array', 'items': {'type': 'object', 'properties': {'term': {'type': 'string'}, 'definition': {'type': 'string'}}}},
                'quiz_questions': {'type': 'array', 'items': {'type': 'string'}}
            }},
            max_output_tokens=8192,
            temperature=0.1
        )
        
        prompt = """
        Analyze the attached material. 
        Return a DENSE summary and exactly 10-15 key terms. 
        Keep each definition under 20 words. 
        This is critical: The response must be valid JSON and fit within the output limit.
        """
        res = self.client.models.generate_content(
        model=self.get_model("auto"),
        config=model_config,
        contents=[prompt] + content_list
        )

        try:
            return json.loads(res.text)
        except Exception as e:
            # This helps you debug in the VS Code / Terminal window
            print("--- DEBUG: BROKEN JSON RECEIVED ---")
            print(res.text) 
            print("--- END DEBUG ---")
            raise ValueError("The study guide was too long and got cut off. Try uploading fewer pages or a simpler image.")

    def stream_chat(self, user_question, content_list, model_id):
        """Streams a chat response back to the UI."""
        qa_config = types.GenerateContentConfig(
            system_instruction=self.sys_instr + " Provide detailed, step-by-step explanations. If the user asks about a complex concept, break it down clearly.",
            max_output_tokens=8192,
            temperature=0.7                            
            )
        return self.client.models.generate_content_stream(
            model=model_id,
            config=qa_config,
            contents=[user_question] + content_list
        )