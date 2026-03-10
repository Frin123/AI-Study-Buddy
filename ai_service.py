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

        "TOPIC SPECIFICITY RULE: You are forbidden from using generic topics like 'General Concept', 'Notes', or 'Study Material'.
          You must categorize questions based on the actual academic sub-topic (e.g., 'Algebraic Geometry', 'Cellular Respiration', 'Macroeconomics'). 
          If the material is Math, use the specific mathematical operation as the topic."
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

    def generate_study_guide(self, _content_text):
        """
        Analyzes text/images and returns structured JSON.
        Includes IDK Protocol and Topic Tagging.
        """
        if not _content_text:
            raise ValueError("No content was provided for analysis.")
    
        # 1. UPDATED SCHEMA (Adding error handling and topic tagging)
        model_config = types.GenerateContentConfig(
            system_instruction=self.sys_instr + """
            IDK PROTOCOL: If the input is blurry or not study material, 
            set 'error' to 'ILLEGIBLE' and 'reason' to a brief explanation.
            Otherwise, ensure every Key Term has a 'topic' associated with it.
            """,
            response_mime_type='application/json',
            response_schema={'type': 'object', 'required': ['summary','key_terms'],'properties': {
                'summary': {'type': 'string'},
                'error': {'type': 'string'}, # For IDK Protocol
                'reason': {'type': 'string'}, # For IDK Protocol
                'key_terms': {
                    'type': 'array', 
                    'items': {
                        'type': 'object', 
                        'properties': {
                            'term': {'type': 'string'}, 
                            'definition': {'type': 'string'},
                            'topic': {'type': 'string'} # For Priority Tracking
                        }
                    }
                }
            }},
            max_output_tokens=4000,
            temperature=0.1
        )
    
        # 2. THE PROMPT
        prompt = "Analyze the provided material. Return a DENSE summary and exactly 10-15 key terms with topics."

        if not isinstance(_content_text, list):
            _content_text = [_content_text]
    
        clean_contents = [prompt] + [item for item in _content_text if item is not None]
    
        res = self.client.models.generate_content(
            model=self.get_model("auto"),
            config=model_config,
            contents=clean_contents
        )

        try:
            data = json.loads(res.text)
            # IDK Protocol Check
            if data.get("error") == "ILLEGIBLE":
                return data # Let the UI handle the error display
            return data
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
                    "explanation": {"type": "string"},
                    "topic": {
                        "type": "string", 
                        "description": "Specific academic sub-topic only. DO NOT use 'General'."
                    }
                },
                "required": ["question", "options", "answer", "explanation", "topic"]
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
        - EVERY question must be tagged with a specific academic topic (e.g., 'Linear Transformations', 'Cell Mitosis').
        - DO NOT use generic topics like 'General' or 'Study Notes'.  

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
        
    def generate_adaptive_quiz(self, _content_text, model_id, focus_areas=None, _seed=None):
        """
        Adaptive version that replaces your old generate_followup_quiz.
        """
        # 1. Prepare the prompt with focus_areas if they exist
        topics_str = "\n".join([str(t) for t in focus_areas]) if focus_areas else "General concepts from the notes"
        
        prompt = f"""
        Generate a 3-question multiple choice quiz.
        FOCUS AREA: {topics_str}
        
        Requirements:
        - Return ONLY a valid JSON array.
        - Format: [{{"question": "...", "options": ["A", "B", "C", "D"], "answer": "...", "explanation": "..."}}]
        """

        config = types.GenerateContentConfig(
            system_instruction=self.sys_instr,
            temperature=0.7,
            max_output_tokens=2500
        )

        # 2. Safely combine prompt and content
        if isinstance(_content_text, list):
            clean_payload = [prompt] + [item for item in _content_text if item is not None]
        else:
            clean_payload = [prompt, _content_text]

        # 3. Call Gemini
        res = self.client.models.generate_content(
            model=model_id,
            config=config,
            contents=clean_payload
        )

        # 4. JSON cleanup
        raw_text = res.text.strip()
        try:
            start = raw_text.find("[")
            end = raw_text.rfind("]") + 1
            return json.loads(raw_text[start:end])
        except Exception as e:
            raise ValueError(f"AI Format Error: {e}")

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