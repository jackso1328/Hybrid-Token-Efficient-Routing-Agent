import os
import math
import json
from typing import Dict, Any, List, Optional

try:
    from llama_cpp import Llama, LlamaGrammar
except ImportError:
    print("WARNING: llama-cpp-python is not installed. Local generation will fail.")
    Llama = None
    LlamaGrammar = None

# The real Gemma E4B model for production (Docker)
DEFAULT_MODEL_PATH = "models/gemma-4-e4b-it-q4_k_m.gguf"

# Categories that benefit from thinking mode locally (free reasoning)
THINKING_CATEGORIES = {"math", "logic", "code_gen", "code_debug"}

class LocalGemmaEngine:
    def __init__(self, model_path: str = DEFAULT_MODEL_PATH, n_ctx: int = 4096, n_threads: int = 4):
        """
        Initializes the local Gemma engine with full support for Chat Templates and Tool Calling.
        """
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.llm = None
        
        self._load_model()

    def _load_model(self):
        if not os.path.exists(self.model_path):
            print(f"WARNING: Model file not found at {self.model_path}")
            return
            
        if Llama is None:
            return
            
        print(f"Loading local model from {self.model_path}...")
        self.llm = Llama(
            model_path=self.model_path,
            n_ctx=self.n_ctx,
            n_threads=self.n_threads,
            verbose=False, # Keep logs clean
            chat_format="gemma" # Enforce Gemma-native prompt format
        )
        print("Local model loaded successfully.")

    def generate(self, prompt: str, max_tokens: int = 256, temperature: float = 0.1) -> Dict[str, Any]:
        """
        Raw text completion used by verifiers (math, format) for simple tasks
        like converting a problem to a Python expression.
        Returns {"text": str, "entropy": float}.
        """
        if not self.llm:
            return {"text": "[MOCK] Model not loaded.", "entropy": 0.0}
        
        response = self.llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            echo=False,
        )
        text = response['choices'][0]['text'].strip()
        return {"text": text, "entropy": 0.0}

    def chat_completion(
        self, 
        messages: List[Dict[str, str]], 
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str] = "auto",
        grammar: Optional['LlamaGrammar'] = None,
        max_tokens: int = 256, 
        temperature: float = 0.1
    ) -> Dict[str, Any]:
        """
        Generates text or tool calls using Gemma's native chat completion endpoint.
        Calculates entropy of the generation for confidence scoring.
        """
        if not self.llm:
            return {"content": "[MOCK] Model not loaded.", "tool_calls": [], "entropy": 0.0}
            
        # Optional parameters dictionary to avoid passing None to llama.cpp
        kwargs = {}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        if grammar:
            kwargs["grammar"] = grammar
            
        response = self.llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            logprobs=True,
            **kwargs
        )
        
        message_out = response['choices'][0]['message']
        content = message_out.get('content', '')
        tool_calls = message_out.get('tool_calls', [])
        
        # Calculate entropy if logprobs are available
        entropy = 0.0
        if 'logprobs' in response['choices'][0] and response['choices'][0]['logprobs']:
            entropy = self._calculate_chat_entropy(response['choices'][0]['logprobs'])
            
        return {
            "content": content,
            "tool_calls": tool_calls,
            "entropy": entropy,
            "raw_response": response
        }
        
    def _calculate_chat_entropy(self, logprobs_data: dict) -> float:
        """
        Calculates mean entropy from chat completion logprobs.
        """
        if not logprobs_data or 'content' not in logprobs_data:
            return 0.0
            
        content_logprobs = logprobs_data['content']
        if not content_logprobs:
            return 0.0
            
        # Extract the actual logprob value from each token dictionary
        valid_logprobs = []
        for lp_dict in content_logprobs:
            if isinstance(lp_dict, dict) and 'logprob' in lp_dict:
                valid_logprobs.append(lp_dict['logprob'])
        
        if not valid_logprobs:
            return 0.0
            
        total_entropy = sum(-lp for lp in valid_logprobs)
        return total_entropy / len(valid_logprobs)

