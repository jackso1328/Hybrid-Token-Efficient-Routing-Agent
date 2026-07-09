import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from openai import OpenAI
from config import FIREWORKS_API_KEY, FIREWORKS_BASE_URL, OPENROUTER_API_KEY, OPENROUTER_BASE_URL, ALLOWED_MODELS

class APIClient:
    """
    Handles escalation to API models (Fireworks by default, OpenRouter for testing).
    Implements Token Optimization techniques like Chain of Draft.
    """
    def __init__(self):
        # Prefer Fireworks if both exist, fallback to OpenRouter for testing
        if FIREWORKS_API_KEY:
            self.client = OpenAI(
                base_url=FIREWORKS_BASE_URL,
                api_key=FIREWORKS_API_KEY,
            )
            self.is_openrouter = False
            print("API Client initialized using Fireworks AI.")
        elif OPENROUTER_API_KEY:
            self.client = OpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=OPENROUTER_API_KEY,
            )
            self.is_openrouter = True
            print("API Client initialized using OpenRouter (Testing Mode).")
        else:
            self.client = None
            print("WARNING: No API keys configured. API Escalation will fail.")

    def select_model(self, task_difficulty: str = "medium") -> str:
        """
        Selects the optimal model from ALLOWED_MODELS based on difficulty.
        In testing mode, uses whatever is configured in ALLOWED_MODELS.
        """
        if not ALLOWED_MODELS:
            # Fallback to a highly reliable free model on OpenRouter if config is empty
            return "google/gemma-2-9b-it:free" if self.is_openrouter else "accounts/fireworks/models/gemma-4-26b-a4b-it"
            
        # Simplistic selection: 
        # For 'hard' tasks, pick the last model in the list (usually the biggest)
        # For 'medium/easy', pick the first
        if task_difficulty == "hard":
            return ALLOWED_MODELS[-1]
        return ALLOWED_MODELS[0]

    def generate_escalated_answer(self, prompt: str, task_difficulty: str = "medium", max_tokens: int = 500) -> str:
        """
        Calls the API using the Chain of Draft prompting strategy to minimize output tokens.
        """
        if not self.client:
            return "[API_FAILED] No client configured."
            
        model_name = self.select_model(task_difficulty)
        
        # CHAIN OF DRAFT: Force the model to think minimally and output only the absolute answer
        system_prompt = """You are a token-efficiency system. Provide the final answer with absolute minimal reasoning. 
Do not use conversational preamble like 'Here is the answer'. Keep output strictly necessary."""

        try:
            # We specifically DO NOT use tools here because API tokens cost money.
            # We just want the raw answer generated as cheaply as possible.
            
            # For Fireworks, we strictly disable the thinking budget
            # to prevent it from wasting tokens on hidden reasoning.
            extra_body = {"budget_tokens": 0} if not self.is_openrouter else None
            
            # OpenRouter extra headers
            extra_headers = {
                "HTTP-Referer": "https://github.com/jackso1328/Hybrid-Token-Efficient-Routing-Agent",
                "X-Title": "GemmaCascade Router"
            } if self.is_openrouter else None
            
            kwargs = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            }
            
            if extra_body:
                kwargs["extra_body"] = extra_body
            if extra_headers:
                kwargs["extra_headers"] = extra_headers
                
            response = self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            return content.strip() if content else ""
        except Exception as e:
            print(f"API Call Failed: {e}")
            return f"[API_ERROR] {str(e)}"
