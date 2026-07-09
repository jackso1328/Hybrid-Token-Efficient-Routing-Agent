import os
import sys
import json
import time
import concurrent.futures
from concurrent.futures import TimeoutError

# Ensure modules in src/ can be found
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import INPUT_PATH, OUTPUT_PATH
from local_engine import LocalGemmaEngine
from classifier import TaskClassifier
from api_client import APIClient
from compressor import LLMPromptCompressor
from distiller import AnswerDistiller
from budget_manager import BudgetManager
from grammars import get_ner_grammar, get_sentiment_grammar
from verifiers import verify_math_answer, verify_code_answer, verify_ner_answer, verify_summary

class GemmaCascadeRouter:
    def __init__(self):
        print("Initializing Gemma Cascade Router...")
        self.local_engine = LocalGemmaEngine()
        self.classifier = TaskClassifier(self.local_engine)
        self.api_client = APIClient()
        self.compressor = LLMPromptCompressor()
        self.distiller = AnswerDistiller()
        self.budget_manager = BudgetManager()
        
        self.ner_grammar = get_ner_grammar()
        self.sentiment_grammar = get_sentiment_grammar()
        
        # Token Recycling (Fragment Reuse Cache)
        self.token_cache = {}

    def _check_cache(self, prompt: str) -> str:
        """
        Simple exact-match and prefix-match token recycling.
        If we already solved an identical problem, reuse the answer.
        """
        # Exact match
        if prompt in self.token_cache:
            return self.token_cache[prompt]
            
        # Very rough similarity (if it's 90% the same prompt)
        for cached_prompt, cached_answer in self.token_cache.items():
            if cached_prompt[:50] == prompt[:50] and len(cached_prompt) == len(prompt):
                return cached_answer
                
        return None

    def process_task(self, task: dict) -> dict:
        """
        The core pipeline:
        0. Check Cache (Token Recycling)
        1. Classify
        2. Generate locally (with budget & grammar)
        3. Verify deterministically
        4. Escalate to API if verification fails
        5. Distill answer
        """
        prompt = task["prompt"]
        task_id = task["task_id"]
        
        print(f"\n[{task_id}] Starting pipeline")
        
        # 0. Token Recycling (Fragment reuse)
        cached_ans = self._check_cache(prompt)
        if cached_ans:
            print(f"[{task_id}] Cache hit! Recycled tokens.")
            return {
                "task_id": task_id,
                "answer": cached_ans,
                "source": "cache_recycled",
                "category": "recycled",
                "entropy": 0.0
            }
        
        # 1. Classify
        task_type = self.classifier.classify(prompt)
        budget = self.budget_manager.get_budget(task_type)
        print(f"[{task_id}] Classified as: {task_type} (Budget: {budget})")
        
        # Determine Grammars
        grammar = None
        if task_type == "ner":
            grammar = self.ner_grammar
        elif task_type == "sentiment":
            grammar = self.sentiment_grammar

        # 2. Local Generation (The Brain)
        messages = [{"role": "user", "content": prompt}]
        # Wild-Card: Thinking Mode locally for hard tasks
        if task_type in ["math", "logic", "code_gen", "code_debug"]:
            messages.insert(0, {"role": "system", "content": "You are a precise problem solver. You must enclose your step-by-step reasoning inside <think>...</think> tags before providing the final answer."})
            
        local_result = self.local_engine.chat_completion(
            messages=messages,
            grammar=grammar,
            max_tokens=budget
        )
        
        raw_local_answer = local_result["content"]
        entropy = local_result["entropy"]
        
        # Track simulated usage (mock)
        tokens_used = len(raw_local_answer.split()) # Rough estimate
        self.budget_manager.record_usage(task_type, tokens_used)
        
        # 3. Deterministic Verification (The Safety Net)
        verified = True
        corrected_answer = None
        
        if task_type == "math":
            verified, corrected_answer = verify_math_answer(prompt, raw_local_answer, self.local_engine)
        elif task_type in ["code_debug", "code_gen"]:
            verified, error_msg = verify_code_answer(raw_local_answer, task_type)
        elif task_type == "ner":
            verified, enriched_json = verify_ner_answer(prompt, raw_local_answer)
            if enriched_json:
                corrected_answer = enriched_json
        elif task_type == "summarize":
            verified, shortened = verify_summary(prompt, raw_local_answer, self.local_engine)
            if shortened:
                corrected_answer = shortened
        elif task_type == "sentiment":
            valid_sentiments = ["positive", "negative", "neutral", "mixed"]
            if not any(s in raw_local_answer.lower() for s in valid_sentiments):
                verified = False
        elif task_type in ["logic", "factual"]:
            # Self-Debate (Trust entropy. If uncertain, double check)
            if entropy > 0.8: # High uncertainty
                print(f"[{task_id}] High entropy ({entropy:.2f}). Triggering self-debate.")
                second_opinion = self.local_engine.chat_completion(messages, max_tokens=budget, temperature=0.5)["content"]
                if second_opinion.split()[:5] != raw_local_answer.split()[:5]: # Very rough similarity check
                    verified = False # Escalated!
                    
        # Force escalation if local model is dead or failed classification
        if task_type == "unknown" or "[MOCK]" in raw_local_answer:
            verified = False

        print(f"[{task_id}] Verification passed: {verified}")

        # 4. Routing Decision
        final_answer = raw_local_answer
        source = "local"
        
        if verified and corrected_answer is None:
            # Local answer is perfect
            final_answer = raw_local_answer
        elif corrected_answer is not None:
            # We fixed it locally!
            final_answer = corrected_answer
            source = "local_corrected"
        else:
            # Verification failed. Escalate to API!
            print(f"[{task_id}] Escalating to API...")
            source = "api_escalation"
            compressed_prompt = self.compressor.compress(prompt)
            api_difficulty = "hard" if task_type in ["math", "logic", "code_gen"] else "medium"
            
            # Dual-Pass Refinement
            if task_type in ["code_debug", "code_gen"] and "[MOCK]" not in raw_local_answer:
                api_prompt = f"Draft answer:\n{raw_local_answer}\n\nOriginal prompt:\n{compressed_prompt}\n\nFix the draft if it is wrong. Provide ONLY the final answer."
            else:
                api_prompt = f"{compressed_prompt}\nProvide ONLY the final answer. No reasoning."
                
            # Disable thinking trace on API to save tokens
            final_answer = self.api_client.generate_escalated_answer(
                prompt=api_prompt,
                task_difficulty=api_difficulty,
                max_tokens=budget
            )
            
        # 5. Answer Distillation
        distilled_answer = self.distiller.distill(final_answer)
        
        # Cache the result for future Token Recycling
        self.token_cache[prompt] = distilled_answer
        
        return {
            "task_id": task_id,
            "answer": distilled_answer,
            "source": source,
            "category": task_type,
            "entropy": round(entropy, 2)
        }

def run_pipeline(input_file=INPUT_PATH, output_file=OUTPUT_PATH):
    print(f"Reading tasks from: {input_file}")
    if not os.path.exists(input_file):
        print(f"ERROR: Input file not found at {input_file}")
        return
        
    router = GemmaCascadeRouter()
    
    with open(input_file, "r") as f:
        tasks = json.load(f)
        
    results = []
    
    # Timeout Guards: We strictly bound each task to 30 seconds
    # (Increased from 12s to 30s to allow real local generation if it's slow)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        for task in tasks:
            start_time = time.time()
            try:
                future = executor.submit(router.process_task, task)
                result = future.result(timeout=30)
                results.append(result)
                print(f"[{task['task_id']}] Solved via {result.get('source', 'pipeline')} in {time.time() - start_time:.2f}s")
            except TimeoutError:
                print(f"[{task['task_id']}] TIMEOUT! Local model hung. Escalating immediately to API...")
                # Emergency API Fallback if local model hangs
                emergency_ans = router.api_client.generate_escalated_answer(task["prompt"], "hard", max_tokens=100)
                results.append({
                    "task_id": task["task_id"],
                    "answer": router.distiller.distill(emergency_ans),
                    "source": "api_escalation_timeout",
                    "category": "unknown",
                    "entropy": 0.0
                })
            except Exception as e:
                print(f"[{task['task_id']}] ERROR: {e}")
                results.append({
                    "task_id": task["task_id"],
                    "answer": f"Error processing task: {e}",
                    "source": "error",
                    "category": "unknown",
                    "entropy": 0.0
                })
                
    if not os.path.exists(os.path.dirname(output_file)):
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"\nFinished! Processed {len(tasks)} tasks.")
    print(f"Results saved to {output_file}.")

if __name__ == "__main__":
    run_pipeline()
