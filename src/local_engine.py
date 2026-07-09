import os
import math
import json
from typing import Dict, Any, List, Optional

try:
    from llama_cpp import Llama, LlamaGrammar
    LLAMA_AVAILABLE = True
except ImportError:
    print("WARNING: llama-cpp-python is not installed. Local generation will return mock responses.")
    Llama = None
    LlamaGrammar = None
    LLAMA_AVAILABLE = False

from config import LOCAL_MODEL_PATH

# Categories that benefit from thinking mode locally (free reasoning)
THINKING_CATEGORIES = {"math", "logic", "code_gen", "code_debug"}


class LocalGemmaEngine:
    """
    The local brain of the Gemma Cascade Router.
    Runs Gemma 4 E4B via llama.cpp for ZERO Fireworks token cost.
    Supports:
      - Chat completion with Gemma-native format
      - Entropy-based confidence scoring via logprobs
      - Grammar-constrained generation (GBNF)
      - Tool/function calling schema support
      - Raw text completion for verifiers
    """

    def __init__(self, model_path: str = None, n_ctx: int = 8192, n_threads: int = 4):
        self.model_path = model_path or LOCAL_MODEL_PATH
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.llm = None
        self.is_loaded = False

        self._load_model()

    def _load_model(self):
        """Load the GGUF model via llama-cpp-python."""
        if not LLAMA_AVAILABLE:
            print("llama-cpp-python not available — running in API-only mode.")
            return

        if not os.path.exists(self.model_path):
            print(f"WARNING: Model file not found at {self.model_path}")
            print("  The router will fall back to API for all tasks.")
            return

        try:
            print(f"Loading local model from {self.model_path}...")
            print(f"  Context window: {self.n_ctx} tokens, Threads: {self.n_threads}")
            self.llm = Llama(
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                n_gpu_layers=0,        # CPU-only (Docker container)
                verbose=False,
                logits_all=False,
            )
            self.is_loaded = True
            print("Local model loaded successfully!")
        except Exception as e:
            print(f"ERROR loading local model: {e}")
            print("  The router will fall back to API for all tasks.")

    def generate(self, prompt: str, max_tokens: int = 256, temperature: float = 0.1) -> Dict[str, Any]:
        """
        Raw text completion — used by verifiers (math, format) for simple tasks
        like converting a problem to a Python expression.
        Returns {"text": str, "entropy": float}.
        """
        if not self.is_loaded:
            return {"text": "[MOCK] Model not loaded.", "entropy": 99.0}

        try:
            response = self.llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                echo=False,
            )
            text = response['choices'][0]['text'].strip()
            return {"text": text, "entropy": 0.0}
        except Exception as e:
            print(f"  Local generate error: {e}")
            return {"text": "[MOCK] Generation failed.", "entropy": 99.0}

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str] = "auto",
        grammar: Optional[Any] = None,
        max_tokens: int = 256,
        temperature: float = 0.1
    ) -> Dict[str, Any]:
        """
        Chat completion using Gemma's native format.
        Calculates entropy of the generation for confidence scoring.

        Returns:
            {
                "content": str,
                "tool_calls": list,
                "entropy": float,
                "raw_response": dict
            }
        """
        if not self.is_loaded:
            return {
                "content": "[MOCK] Model not loaded.",
                "tool_calls": [],
                "entropy": 99.0,
                "raw_response": {}
            }

        try:
            # Build kwargs — only pass optional params if they are set
            kwargs = {}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice
            if grammar is not None:
                kwargs["grammar"] = grammar

            response = self.llm.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                logprobs=True,
                top_logprobs=5,
                **kwargs
            )

            message_out = response['choices'][0]['message']
            content = message_out.get('content', '') or ''
            tool_calls = message_out.get('tool_calls', [])

            # Calculate entropy from logprobs for confidence scoring
            entropy = 0.0
            choice = response['choices'][0]
            if 'logprobs' in choice and choice['logprobs']:
                entropy = self._calculate_chat_entropy(choice['logprobs'])

            return {
                "content": content,
                "tool_calls": tool_calls,
                "entropy": entropy,
                "raw_response": response
            }
        except Exception as e:
            print(f"  Local chat_completion error: {e}")
            return {
                "content": "[MOCK] Chat completion failed.",
                "tool_calls": [],
                "entropy": 99.0,
                "raw_response": {}
            }

    def _calculate_chat_entropy(self, logprobs_data: dict) -> float:
        """
        Calculates mean entropy from chat completion logprobs.
        Low entropy = model is confident → keep local answer.
        High entropy = model is guessing → escalate to API.
        """
        if not logprobs_data:
            return 0.0

        # Handle different logprobs formats from llama-cpp-python
        content_logprobs = None
        if isinstance(logprobs_data, dict) and 'content' in logprobs_data:
            content_logprobs = logprobs_data['content']
        elif isinstance(logprobs_data, list):
            content_logprobs = logprobs_data

        if not content_logprobs:
            return 0.0

        valid_logprobs = []
        for lp_entry in content_logprobs:
            if isinstance(lp_entry, dict):
                if 'logprob' in lp_entry:
                    valid_logprobs.append(lp_entry['logprob'])
                elif 'token_logprob' in lp_entry:
                    valid_logprobs.append(lp_entry['token_logprob'])

        if not valid_logprobs:
            return 0.0

        # Mean negative log-probability (higher = more uncertain)
        total_entropy = sum(-lp for lp in valid_logprobs)
        return total_entropy / len(valid_logprobs)
