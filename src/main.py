import json
import time
import concurrent.futures
from concurrent.futures import TimeoutError

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
        
        # 0. Token Recycling (Fragment reuse)
        cached_ans = self._check_cache(prompt)
        if cached_ans:
            print(f"  -> Cache hit! Recycled tokens for {task_id}.")
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
            # Gap 5 Fix: Use explicit system instruction instead of raw special tokens
            messages.insert(0, {"role": "system", "content": "You are a precise problem solver. You must enclose your step-by-step reasoning inside <think>...</think> tags before providing the final answer."})
            
        local_result = self.local_engine.chat_completion(
            messages=messages,
            grammar=grammar,
            max_tokens=budget
        )
        
        raw_local_answer = local_result["content"]
        
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
            # Gap 2: Sentiment Verification
            valid_sentiments = ["positive", "negative", "neutral", "mixed"]
            if not any(s in raw_local_answer.lower() for s in valid_sentiments):
                verified = False
        elif task_type in ["logic", "factual"]:
            # Wild-Card: Self-Debate (Trust entropy. If uncertain, double check)
            if local_result["entropy"] > 0.8: # High uncertainty
                second_opinion = self.local_engine.chat_completion(messages, max_tokens=budget, temperature=0.5)["content"]
                if second_opinion.split()[:5] != raw_local_answer.split()[:5]: # Very rough similarity check
                    verified = False # Escalated!
                    
        # Force escalation if local model is dead or failed classification
        if task_type == "unknown" or "[MOCK]" in raw_local_answer:
            verified = False

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
            source = "api_escalation"
            compressed_prompt = self.compressor.compress(prompt)
            api_difficulty = "hard" if task_type in ["math", "logic", "code_gen"] else "medium"
            
            # Gap 1: Dual-Pass Refinement
            if task_type in ["code_debug", "code_gen"] and "[MOCK]" not in raw_local_answer:
                # Send the draft and ask the API to fix it (cheaper than solving from scratch)
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
        
        # Gap 7: Return exactly the 2 keys required by the Hackathon spec
        return {
            "task_id": task_id,
            "answer": distilled_answer
        }

def run_pipeline(input_file="input/tasks.json", output_file="output/results.json"):
    router = GemmaCascadeRouter()
    
    with open(input_file, "r") as f:
        tasks = json.load(f)
        
    results = []
    
    # 6.3 Timeout Guards
    # We strictly bound each task to 12 seconds to ensure we survive the 10-minute global limit
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        for task in tasks:
            print(f"Processing Task {task['task_id']}...")
            start_time = time.time()
            try:
                # Submit task to thread
                future = executor.submit(router.process_task, task)
                # Wait for up to 12 seconds
                result = future.result(timeout=12)
                results.append(result)
                print(f"  -> Solved via {result.get('source', 'pipeline')} in {time.time() - start_time:.2f}s")
            except TimeoutError:
                print(f"  -> TIMEOUT! Local model hung. Escalating immediately to API...")
                # Emergency API Fallback if local model hangs
                emergency_ans = router.api_client.generate_escalated_answer(task["prompt"], "hard", max_tokens=100)
                results.append({
                    "task_id": task["task_id"],
                    "answer": router.distiller.distill(emergency_ans)
                })
            except Exception as e:
                print(f"  -> ERROR: {e}")
                results.append({
                    "task_id": task["task_id"],
                    "answer": "Error processing task."
                })
                
    import os
    if not os.path.exists(os.path.dirname(output_file)):
        os.makedirs(os.path.dirname(output_file))
        
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"Finished! Processed {len(tasks)} tasks. Results saved to {output_file}.")

if __name__ == "__main__":
    run_pipeline()

