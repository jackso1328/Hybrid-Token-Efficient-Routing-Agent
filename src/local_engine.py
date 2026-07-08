import os
import math
from typing import Dict, Any, Optional

try:
    from llama_cpp import Llama
except ImportError:
    print("WARNING: llama-cpp-python is not installed. Local generation will fail.")
    Llama = None

class LocalGemmaEngine:
    def __init__(self, model_path: str = "models/test-model-q4_k_m.gguf", n_ctx: int = 4096, n_threads: int = 4):
        """
        Initializes the local Gemma engine.
        Using a placeholder model path by default for rapid testing.
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
            verbose=False # Keep logs clean
        )
        print("Local model loaded successfully.")

    def generate(self, prompt: str, max_tokens: int = 256, temperature: float = 0.1, stop: list = None) -> Dict[str, Any]:
        """
        Generates text using the local model.
        Also calculates entropy to measure the model's uncertainty.
        """
        if not self.llm:
            return {"text": "[MOCK] Model not loaded. Would generate locally.", "entropy": 0.0}
            
        if stop is None:
            stop = ["<|im_end|>", "</s>", "<eos>"]
            
        # We request logprobs so we can calculate entropy
        response = self.llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop,
            logprobs=1, 
            echo=False
        )
        
        generated_text = response['choices'][0]['text'].strip()
        logprobs_data = response['choices'][0]['logprobs']
        
        entropy = self._calculate_entropy(logprobs_data)
        
        return {
            "text": generated_text,
            "entropy": entropy,
            "raw_response": response
        }
        
    def _calculate_entropy(self, logprobs_data: dict) -> float:
        """
        Calculates the mean entropy of the generated tokens based on log probabilities.
        Higher entropy = higher uncertainty.
        """
        if not logprobs_data or 'token_logprobs' not in logprobs_data:
            return 0.0
            
        token_logprobs = logprobs_data['token_logprobs']
        # Filter out None values (first token often lacks logprob)
        valid_logprobs = [lp for lp in token_logprobs if lp is not None]
        
        if not valid_logprobs:
            return 0.0
            
        # Entropy H = -1 * logprob (since logprob is log2 or ln of probability)
        # Average it across all generated tokens
        total_entropy = sum(-lp for lp in valid_logprobs)
        mean_entropy = total_entropy / len(valid_logprobs)
        
        return mean_entropy

if __name__ == "__main__":
    # Simple test
    engine = LocalGemmaEngine()
    result = engine.generate("The capital of France is ")
    print(f"Generated: {result['text']}")
    print(f"Entropy: {result['entropy']:.4f}")
