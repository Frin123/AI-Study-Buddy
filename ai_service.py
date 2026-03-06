import json
import streamlit as st
from google.genai import types
import PyPDF2
from io import BytesIO



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

    @st.cache_data
    def process_pdf(_self, uploaded_file):
        """
        Extracts text from a PDF file. 
        Cached so it only runs once per file upload.
        """
        try:
            pdf_reader = PyPDF2.PdfReader(BytesIO(uploaded_file.read()))
            text_content = ""
            for page in pdf_reader.pages:
                text_content += page.extract_text() + "\n"
            return text_content
        except Exception as e:
            raise ValueError(f"Failed to process PDF: {e}")

    def get_model(self, task_type, user_choice="gemini-3.1-flash-lite-preview"):
        """Centralized model router."""
        if task_type == "auto":
            return "gemini-3.1-flash-lite-preview" 
        return user_choice

    def generate_study_guide(_self, _content_text):
        """
        Analyzes text and returns structured JSON.
        Cached to make flashcard toggling instant.
        """

        if not _content_text:
            raise ValueError("No content was provided for analysis.")
        
        model_config = types.GenerateContentConfig(
            system_instruction=_self.sys_instr,
            response_mime_type='application/json',
            response_schema={'type': 'object', 'required': ['summary','key_terms'],'properties': {
                'summary': {'type': 'string'},
                'key_terms': {'type': 'array', 'items': {'type': 'object', 'properties': {'term': {'type': 'string'}, 'definition': {'type': 'string'}}}},
                'quiz_questions': {'type': 'array', 'items': {'type': 'string'}}
            }},
            max_output_tokens=4000,
            temperature=0.1
        )
        
        prompt = "Analyze the provided material. Return a DENSE summary and exactly 10-15 key terms."

        # Ensure we are not sending [prompt, None]
        # We filter out any None values just in case
        if not isinstance(_content_text, list):
            _content_text = [_content_text]
        clean_contents = [prompt] + [item for item in _content_text if item is not None]
        
        res = _self.client.models.generate_content(
            model=_self.get_model("auto"),
            config=model_config,
            contents=clean_contents
        )

        try:
            return json.loads(res.text)
        except Exception as e:
            raise ValueError("JSON Error: Study guide too complex. Try a smaller section.")

    def generate_quiz(_self, _content_text, model_id, _seed=0):
        """
        Generates 5 questions. 
        Increased tokens and stricter rules to prevent JSON errors.
        """

        local_quiz_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer": {"type": "string"},
                    "explanation": {"type": "string"}
                },
                "required": ["question", "options", "answer", "explanation"]
            }
        }

        config = types.GenerateContentConfig(
            system_instruction=_self.sys_instr,
            temperature=0.7,
            max_output_tokens=2500, # Increased to prevent "Unterminated String"
            response_mime_type="application/json",
            response_schema=local_quiz_schema
        )

        prompt = f"""
        Create a 5-question multiple choice quiz based on the provided study material.

        Requirements:
        - Each question should test understanding, not memorization.
        - Each question must have 4 answer options.
        - The correct answer must match one of the options exactly.
        - Include a short explanation for the correct answer.
        - Ensure all strings are JSON-safe. 
        - If you use quotes inside a sentence, use single quotes (') or escape them (\").  

        Seed reference: {_seed}
        """


        res = _self.client.models.generate_content(
            model=model_id,
            config=config,
            contents=[prompt] + _content_text
        )

        raw_text = res.text.strip()

        try:
            # Try to load the AI response normally
            return json.loads(res.text.strip())
        except json.JSONDecodeError as e:
            # If it fails, the AI likely put a newline or a quote in the wrong place
            try:
                # Clean up newlines that often break JSON strings
                fixed_text = res.text.replace('\n', ' ').strip()
                return json.loads(fixed_text)
            except:
                # If it STILL fails, we give a clean error instead of a crash
                raise ValueError("The AI's response format was slightly off. Please click 'Generate' again.")
        
    def generate_followup_quiz(self, weak_topics, _content_text, model_id):
        """
        Generates a targeted quiz based on questions the user got wrong.
        """
        # Convert the list of weak topics into a readable string for the prompt
        topics_str = "\n".join([str(t) for t in weak_topics])
        
        prompt = f"""
        The student is struggling with the following concepts:
        {topics_str}

        Generate a new 3-question multiple choice quiz focusing SPECIFICALLY on these weak areas.
        Return ONLY a valid JSON array. No markdown.
        Format: [{{"question": "...", "options": ["A", "B", "C", "D"], "answer": "...", "explanation": "..."}}]
        """

        config = types.GenerateContentConfig(
            system_instruction=self.sys_instr,
            temperature=0.7,
            max_output_tokens=2500
        )

        # Safety filter for input
        if isinstance(_content_text, list):
            clean_payload = [prompt] + [item for item in _content_text if item is not None]
        else:
            clean_payload = [prompt, _content_text]

        res = self.client.models.generate_content(
            model=model_id,
            config=config,
            contents=clean_payload
        )

        raw_text = res.text.strip()
        try:
            start = raw_text.find("[")
            end = raw_text.rfind("]") + 1
            return json.loads(raw_text[start:end])
        except Exception as e:
            raise ValueError(f"Follow-up Quiz Error: {e}")

    def stream_chat(self, user_question, _content_text, model_id):
        """Streams responses. (No cache needed for streaming)"""
        qa_config = types.GenerateContentConfig(
            system_instruction=self.sys_instr + " Break down complex concepts clearly.",
            max_output_tokens=2000,
            temperature=0.7
        )
        return self.client.models.generate_content_stream(
            model=model_id,
            config=qa_config,
            contents=[user_question] + _content_text
        )