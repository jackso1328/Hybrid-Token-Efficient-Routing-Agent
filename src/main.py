import os
import sys
import json
import time
import re
import gc
import psutil

def print_mem_usage(stage_name: str):
    process = psutil.Process()
    mem_mb = process.memory_info().rss / (1024 * 1024)
    print(f"\n[MEMORY] {stage_name}: {mem_mb:.1f} MB")

def safe_str(text: str) -> str:
    """Sanitize text for safe Windows console printing by replacing non-ASCII chars."""
    return text.encode('ascii', 'replace').decode('ascii')

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
        print("=" * 60)
        print("  Gemma Cascade Router — Initializing Pipeline")
        print("=" * 60)
        self.local_engine = LocalGemmaEngine()
        self.classifier = TaskClassifier(self.local_engine)
        self.api_client = APIClient()
        self.distiller = AnswerDistiller()
        self.budget_manager = BudgetManager()
        
        self.ner_grammar = get_ner_grammar()
        self.sentiment_grammar = get_sentiment_grammar()
        
        # Token Recycling (Fragment Reuse Cache)
        self.token_cache = {}
        print("=" * 60)
        print("  Pipeline ready. Processing tasks...")
        print("=" * 60)

    def _check_cache(self, prompt: str) -> str:
        """
        Simple exact-match and prefix-match token recycling.
        If we already solved an identical problem, reuse the answer.
        """
        if prompt in self.token_cache:
            return self.token_cache[prompt]
            
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
        
        print(f"\n{'-' * 50}")
        print(f"[{task_id}] Starting pipeline")
        print(f"  Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
        
        # 0. Token Recycling (Fragment reuse)
        cached_ans = self._check_cache(prompt)
        if cached_ans:
            print(f"[{task_id}] [CACHE] Hit! Recycled tokens.")
            return {
                "task_id": task_id,
                "answer": cached_ans,
                "source": "cache_recycled",
                "category": "recycled",
                "entropy": 0.0
            }
        
        # 1. Classify
        task_type = self.classifier.classify(prompt)
        budget = self.budget_manager.get_budget(task_type, prompt)
        print(f"[{task_id}] Category: {task_type} | Dynamic Budget: {budget} tokens")
        
        # Determine Grammars
        grammar = None
        if task_type == "ner":
            grammar = self.ner_grammar
        elif task_type == "sentiment":
            grammar = self.sentiment_grammar

        # 2. Local Generation (The Brain)
        messages = [{"role": "user", "content": prompt}]
        if task_type in ["math", "logic", "code_gen", "code_debug"]:
            messages.insert(0, {"role": "system", "content": "You are a precise problem solver. You must enclose your step-by-step reasoning inside <think>...</think> tags before providing the final answer."})
            local_max_tokens = 1024
        else:
            messages.insert(0, {"role": "system", "content": "You are a precise assistant. Do NOT use <think> tags. Provide your answer directly and concisely."})
            local_max_tokens = 256
            
        local_result = self.local_engine.chat_completion(
            messages=messages,
            grammar=grammar,
            max_tokens=local_max_tokens
        )
        
        raw_local_answer = local_result["content"]
        
        # Strip <think> tags early so verifiers and routing only see the final answer
        raw_local_answer = re.sub(r'<think>.*?(?:</think>|$)\s*', '', raw_local_answer, flags=re.DOTALL).strip()
        
        entropy = local_result["entropy"]
        
        tokens_used = len(raw_local_answer.split())
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
            if entropy > 0.8:
                print(f"[{task_id}] [WARN] High entropy ({entropy:.2f}). Triggering self-debate...")
                second_opinion = self.local_engine.chat_completion(messages, max_tokens=local_max_tokens, temperature=0.5)["content"]
                if second_opinion.split()[:5] != raw_local_answer.split()[:5]:
                    verified = False
                    
        # Force escalation if local model is dead, failed classification, or returned empty text
        if task_type == "unknown" or "[MOCK]" in raw_local_answer or not raw_local_answer:
            verified = False

        print(f"[{task_id}] Verification: {'PASSED' if verified else 'FAILED -> Escalating to API'}")

        # 4. Routing Decision
        final_answer = raw_local_answer
        source = "local"
        
        if verified and corrected_answer is None:
            final_answer = raw_local_answer
        elif corrected_answer is not None:
            final_answer = corrected_answer
            source = "local_corrected"
        else:
            # Verification failed. Escalate to API!
            source = "api_escalation"
            compressed_prompt = task.get("compressed_prompt", prompt)
            api_difficulty = "hard" if task_type in ["math", "logic", "code_gen"] else "medium"
            
            # Use generous token budget for API (minimum 1024 to avoid truncation by reasoning models)
            api_budget = max(budget, 1024)
            
            # Build task-type-specific API prompts for maximum token efficiency
            if task_type in ["code_debug", "code_gen"] and "[MOCK]" not in raw_local_answer:
                api_prompt = f"Draft answer:\n{raw_local_answer}\n\nOriginal prompt:\n{compressed_prompt}\n\nFix the draft if it is wrong. Provide ONLY the final answer."
            elif task_type == "ner":
                api_prompt = f'{compressed_prompt}\nOutput ONLY a JSON object with keys "persons", "organizations", "locations", "dates". Each value is a list of strings. No explanation.'
            elif task_type == "sentiment":
                api_prompt = f"{compressed_prompt}\nOutput ONLY one word: positive, negative, neutral, or mixed."
            else:
                api_prompt = f"{compressed_prompt}\nProvide ONLY the final answer. No reasoning."
                
            final_answer = self.api_client.generate_escalated_answer(
                prompt=api_prompt,
                task_difficulty=api_difficulty,
                max_tokens=api_budget
            )
            
        # 5. Answer Distillation
        distilled_answer = self.distiller.distill(final_answer)
        
        # Cache the result for future Token Recycling
        self.token_cache[prompt] = distilled_answer
        
        print(f"[{task_id}] Source: {source}")
        print(f"[{task_id}] Answer: {safe_str(distilled_answer[:120])}{'...' if len(distilled_answer) > 120 else ''}")
        
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
        
    with open(input_file, "r") as f:
        tasks = json.load(f)
        
    print(f"\n{'=' * 60}")
    print("  PHASE 1: Pre-computing Prompt Compression")
    print(f"{'=' * 60}")
    print_mem_usage("Baseline Memory (Before Phase 1)")
    compressor = LLMPromptCompressor()
    print_mem_usage("After Loading LLMLingua-2 Compressor")
    for t in tasks:
        t["compressed_prompt"] = compressor.compress(t["prompt"])
    print_mem_usage("Peak Phase 1 Memory")
    print("  Compression complete. Freeing memory...")
    del compressor
    gc.collect()
    print_mem_usage("After GC (Compressor Freed)")
        
    router = GemmaCascadeRouter()
    print_mem_usage("After Loading Gemma Router (Phase 2)")
        
    results = []
    total_start = time.time()
    
    for task in tasks:
        start_time = time.time()
        try:
            result = router.process_task(task)
            results.append(result)
            elapsed = time.time() - start_time
            print(f"[{task['task_id']}] Completed in {elapsed:.2f}s")
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
    
    total_elapsed = time.time() - total_start

    # Print summary table
    print(f"\n{'=' * 60}")
    print(f"  PIPELINE SUMMARY")
    print(f"{'=' * 60}")
    print(f"  {'Task':<8} {'Category':<12} {'Source':<20} {'Answer Preview'}")
    print(f"  {'-'*8} {'-'*12} {'-'*20} {'-'*30}")
    for r in results:
        answer_preview = safe_str(r['answer'][:30].replace('\n', ' '))
        print(f"  {r['task_id']:<8} {r.get('category','?'):<12} {r['source']:<20} {answer_preview}")
    print(f"{'-' * 60}")
    
    local_count = sum(1 for r in results if r['source'] in ['local', 'local_corrected', 'cache_recycled'])
    api_count = sum(1 for r in results if 'api' in r['source'])
    blank_count = sum(1 for r in results if not r['answer'].strip())
    
    print(f"  Total tasks: {len(results)}")
    print(f"  Local solves: {local_count} (zero API tokens)")
    print(f"  API escalations: {api_count}")
    print(f"  Blank answers: {blank_count}")
    print(f"  Total runtime: {total_elapsed:.2f}s")
    print(f"  Results saved to {output_file}")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    run_pipeline()
