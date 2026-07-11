import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from openai import OpenAI
from config import FIREWORKS_API_KEY, FIREWORKS_BASE_URL, OPENROUTER_API_KEY, OPENROUTER_BASE_URL, ALLOWED_MODELS

class APIClient:
    """
    Handles escalation to API models.
    In judging mode (FIREWORKS_API_KEY set): uses Fireworks AI exclusively.
    In testing mode (only OPENROUTER_API_KEY set): uses OpenRouter.
    """
    def __init__(self):
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_reasoning_tokens = 0
        if FIREWORKS_API_KEY:
            # JUDGING MODE: Fireworks only, OpenRouter completely disabled
            self.client = OpenAI(
                base_url=FIREWORKS_BASE_URL,
                api_key=FIREWORKS_API_KEY,
            )
            self.is_openrouter = False
            print("API Client initialized using Fireworks AI.")
        elif OPENROUTER_API_KEY:
            # TESTING MODE: OpenRouter for local development
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
        """
        if not ALLOWED_MODELS or ALLOWED_MODELS == ["tencent/hy3:free"]:
            return "tencent/hy3:free" if self.is_openrouter else "accounts/fireworks/models/gemma-4-26b-a4b-it"
            
        if task_difficulty == "hard":
            return ALLOWED_MODELS[-1]
        return ALLOWED_MODELS[0]

    def generate_escalated_answer(self, prompt: str, task_difficulty: str = "medium", max_tokens: int = 500) -> str:
        """
        Calls the API using the Chain of Draft prompting strategy to minimize output tokens.
        Will NOT fall back to OpenRouter if Fireworks fails during judging.
        """
        if not self.client:
            return "[API_FAILED] No client configured."
            
        model_name = self.select_model(task_difficulty)
        print(f"  [API] Using model: {model_name} (difficulty: {task_difficulty}, max_tokens: {max_tokens})")
        
        # CHAIN OF DRAFT: Allow thinking but in hyper-compressed format
        system_prompt = """You are a token-efficiency system. Use 'Chain of Draft' reasoning: think in highly compressed, abbreviated format using minimal words. Then output EXACTLY the final answer. No conversational preamble."""

        try:
            # For Fireworks, we strictly disable the thinking budget
            extra_body = {"budget_tokens": 0} if not self.is_openrouter else None
            
            # OpenRouter extra headers (only in testing mode)
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

            if hasattr(response, 'usage') and response.usage:
                p_tokens = response.usage.prompt_tokens
                c_tokens = response.usage.completion_tokens
                
                # Extract reasoning tokens (OpenRouter / OpenAI latest spec)
                r_tokens = 0
                if hasattr(response.usage, 'completion_tokens_details') and response.usage.completion_tokens_details:
                    r_tokens = getattr(response.usage.completion_tokens_details, 'reasoning_tokens', 0)
                if r_tokens is None:
                    r_tokens = 0
                    
                o_tokens = c_tokens - r_tokens
                
                self.total_prompt_tokens += p_tokens
                self.total_completion_tokens += o_tokens
                self.total_reasoning_tokens += r_tokens
                print(f"  [API] Tokens for this question -> Input: {p_tokens} | Thinking: {r_tokens} | Output: {o_tokens}")

            return content.strip() if content else ""
        except Exception as e:
            print(f"  [API] Call Failed: {e}")
            return f"[API_ERROR] {str(e)}"
