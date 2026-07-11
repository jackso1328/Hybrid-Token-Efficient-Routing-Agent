import os
import sys
import json
import time
import re
import gc
import threading
import subprocess
import tempfile

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

# Categories that should skip local model and go directly to API
DIRECT_API_CATEGORIES = set()  # All categories handled locally (math uses Code-as-Reasoning)

# Maximum seconds to wait for local model before escalating to API
LOCAL_TIMEOUT = 65  # Give the local model exactly the time it needs to finish long Factual essays without timing out

import signal

class TimeoutException(Exception):
    pass

def _timeout_handler(signum, frame):
    raise TimeoutException("Local model timeout")

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

    def _run_local_with_timeout(self, messages, grammar, max_tokens):
        """
        Run local model generation with a timeout using signal.alarm to prevent C++ segfaults.
        If the model takes longer than LOCAL_TIMEOUT seconds, returns None.
        """
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(LOCAL_TIMEOUT)
        
        try:
            result = self.local_engine.chat_completion(
                messages=messages,
                grammar=grammar,
                max_tokens=max_tokens
            )
            return result
        except TimeoutException:
            return None
        except Exception as e:
            print(f"  [ERROR] Local generation failed: {e}")
            return None
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    def _escalate_to_api(self, task, task_type, budget):
        """Helper to send a task directly to the API with category-specific prompts."""
        compressed_prompt = task.get("compressed_prompt", task["prompt"])
        api_difficulty = "hard" if task_type in ["math", "code_gen"] else "medium"
        api_budget = max(budget, 4096)  # Give premium models enough room to think without getting cut off
        
        if task_type in ["code_debug", "code_gen"]:
            api_prompt = f"{compressed_prompt}\nOnly output final code. No explanation."
        elif task_type == "ner":
            api_prompt = f'{compressed_prompt}\nOnly output JSON: {{"persons":[],"organizations":[],"locations":[],"dates":[]}}'
        elif task_type == "sentiment":
            api_prompt = f"{compressed_prompt}\nOne word only: positive, negative, neutral, or mixed."
        else:
            api_prompt = f"{compressed_prompt}\nOnly output final answer. No reasoning."
        
        return self.api_client.generate_escalated_answer(
            prompt=api_prompt,
            task_difficulty=api_difficulty,
            max_tokens=api_budget
        )

    def process_task(self, task: dict) -> dict:
        """
        The core pipeline with Direct Routing and Timeout:
        0. Check Cache (Token Recycling)
        1. Classify
        2. Direct Route (math/code → API immediately)
        3. Local Generation with 50s timeout
        4. Verify deterministically
        5. Escalate to API if verification fails
        6. Distill answer
        """
        prompt = task["prompt"]
        task_id = task["task_id"]
        entropy = 0.0
        
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
        
        # 2. Direct Routing: categories the local 2B model consistently fails at
        if task_type in DIRECT_API_CATEGORIES:
            print(f"[{task_id}] [DIRECT ROUTE] {task_type} -> Skipping local model, sending to API")
            final_answer = self._escalate_to_api(task, task_type, budget)
            source = "api_direct"
        else:
            # 3. Local Generation with timeout
            grammar = None
            if task_type == "ner":
                grammar = self.ner_grammar
            elif task_type == "sentiment":
                grammar = self.sentiment_grammar

            messages = [{"role": "user", "content": prompt}]
            if task_type == "logic":
                messages.insert(0, {"role": "system", "content": "You are a precise problem solver. You must enclose your step-by-step reasoning inside <think>...</think> tags before providing the final answer."})
                local_max_tokens = 1024
            else:
                messages.insert(0, {"role": "system", "content": "You are a precise assistant. Do NOT use <think> tags. Provide your answer directly and concisely."})
                local_max_tokens = 256
            
            local_result = self._run_local_with_timeout(messages, grammar, local_max_tokens)
            
            if local_result is None:
                # Timeout or error -> escalate to API
                print(f"[{task_id}] [TIMEOUT] Local model exceeded {LOCAL_TIMEOUT}s -> Escalating to API")
                final_answer = self._escalate_to_api(task, task_type, budget)
                source = "api_timeout"
            else:
                raw_local_answer = local_result["content"]
                raw_local_answer = re.sub(r'<think>.*?(?:</think>|$)\s*', '', raw_local_answer, flags=re.DOTALL).strip()
                entropy = local_result["entropy"]
                
                tokens_used = len(raw_local_answer.split())
                self.budget_manager.record_usage(task_type, tokens_used)
                
                # 4. Deterministic Verification
                verified = True
                corrected_answer = None
                
                if task_type == "ner":
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
                elif task_type in ["logic", "factual"] and "[MOCK]" not in raw_local_answer:
                    if entropy > 0.8:
                        print(f"[{task_id}] [WARN] High entropy ({entropy:.2f}). Triggering self-debate...")
                        second_opinion = self.local_engine.chat_completion(messages, max_tokens=local_max_tokens, temperature=0.5)["content"]
                        if second_opinion.split()[:5] != raw_local_answer.split()[:5]:
                            verified = False
                
                # Force escalation if local model is dead or returned empty text
                if task_type == "unknown" or "[MOCK]" in raw_local_answer or not raw_local_answer:
                    verified = False
                
                print(f"[{task_id}] Verification: {'PASSED' if verified else 'FAILED -> Escalating to API'}")
                
                # 5. Routing Decision
                if verified and corrected_answer is None:
                    final_answer = raw_local_answer
                    source = "local"
                elif corrected_answer is not None:
                    final_answer = corrected_answer
                    source = "local_corrected"
                else:
                    final_answer = self._escalate_to_api(task, task_type, budget)
                    source = "api_escalation"
        
        # 6. Answer Distillation
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

    # ════════════════════════════════════════════
    # PHASE 1: Pre-computing Prompt Compression
    # ════════════════════════════════════════════
    print(f"\n{'=' * 60}")
    print("  PHASE 1: Pre-computing Prompt Compression")
    print(f"{'=' * 60}")
    compressor = LLMPromptCompressor()
    for t in tasks:
        t["compressed_prompt"] = compressor.compress(t["prompt"])
    print("  Compression complete. Freeing memory...")
    compressor.free_memory()
    del compressor
    gc.collect()

    # ════════════════════════════════════════════
    # PHASE 2: Local Intelligence (Gemma + Code-as-Reasoning)
    # ════════════════════════════════════════════
    print(f"\n{'=' * 60}")
    print("  PHASE 2: Local Intelligence (Gemma + Code-as-Reasoning)")
    print(f"{'=' * 60}")
    router = GemmaCascadeRouter()
        
    results = []
    total_start = time.time()
    
    for task in tasks:
        start_time = time.time()
        try:
            # Route math tasks through Code-as-Reasoning (PAL)
            if _is_math_task(task["prompt"]):
                result = _process_math_with_code(router, task)
            else:
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
    
    local_count = sum(1 for r in results if r['source'] in ['local', 'local_corrected', 'local_pal', 'cache_recycled'])
    api_count = sum(1 for r in results if 'api' in r['source'])
    blank_count = sum(1 for r in results if not r['answer'].strip())
    
    total_api_tokens = router.api_client.total_prompt_tokens + router.api_client.total_completion_tokens + router.api_client.total_reasoning_tokens
    
    print(f"  Total tasks: {len(results)}")
    print(f"  Local solves: {local_count} (zero API tokens)")
    print(f"  API escalations: {api_count}")
    print(f"  Total API Tokens (Input/Thinking/Output): {total_api_tokens} ({router.api_client.total_prompt_tokens} input / {router.api_client.total_reasoning_tokens} thinking / {router.api_client.total_completion_tokens} output)")
    print(f"  Blank answers: {blank_count}")
    print(f"  Total runtime: {total_elapsed:.2f}s")
    print(f"  Results saved to {output_file}")
    print(f"{'=' * 60}")


def _is_math_task(prompt: str) -> bool:
    """Precise heuristic to detect math word problems only.
    Uses multi-signal matching to avoid false positives on factual/sentiment tasks.
    """
    prompt_lower = prompt.lower()
    
    # Must have at least one strong math indicator (numbers + operations)
    has_numbers = any(char.isdigit() for char in prompt)
    
    strong_math_signals = [
        "mph", "marks up", "profit percentage", "discount",
        "triples every", "doubles every", "times larger",
        "how far", "how much", "how many times",
        "compound interest", "solve for",
    ]
    
    # Must match a strong signal AND contain numbers
    has_strong_signal = any(signal in prompt_lower for signal in strong_math_signals)
    
    # Exclude patterns that look like math but aren't
    exclusion_signals = [
        "sentiment", "summarize", "explain", "describe", "extract",
        "fix the bug", "write a python", "classify", "what is the pauli",
        "what is the"
    ]
    is_excluded = any(excl in prompt_lower for excl in exclusion_signals)
    
    return has_strong_signal and has_numbers and not is_excluded


def _execute_python_code(code: str, timeout: int = 10) -> str:
    """
    Execute Python code in a sandboxed subprocess and capture stdout.
    Returns the printed output, or None if execution fails.
    """
    # Write code to a temporary file
    tmp_path = os.path.join(tempfile.gettempdir(), "math_solver.py")
    with open(tmp_path, "w") as f:
        f.write(code)
    
    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        else:
            if result.stderr:
                print(f"    [CODE ERROR] {result.stderr.strip()[:200]}")
            return None
    except subprocess.TimeoutExpired:
        print(f"    [CODE TIMEOUT] Script exceeded {timeout}s")
        return None
    except Exception as e:
        print(f"    [CODE EXEC ERROR] {e}")
        return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _process_math_with_code(router, task: dict) -> dict:
    """
    Program-Aided Language Model (PAL) for math tasks.
    1. Ask Gemma to write a Python script that solves the problem.
    2. Execute the script locally.
    3. Capture the printed output as the answer.
    If the code fails, retry once. If it still fails, fall back to API.
    """
    prompt = task["prompt"]
    task_id = task["task_id"]
    
    print(f"\n{'-' * 50}")
    print(f"[{task_id}] Starting math pipeline (Code-as-Reasoning)")
    print(f"  Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")

    PAL_SYSTEM_PROMPT = f"""You are an expert math solver that writes perfect Python code. Given a math word problem, write a short Python script that calculates the exact answer and prints ONLY the final numerical answer.

CRITICAL RULES:
- Read the logic carefully. Do not calculate the wrong thing (e.g. if asked for profit percentage, don't just calculate the discount).
- Use print() to output ONLY the final numerical answer.
- Output ONLY the Python code, nothing else.

EXAMPLES:

Problem: A merchant marks up goods by 50%. If he then offers a 10% discount on the marked price, what is his actual profit percentage?
Code:
cost = 100
marked = cost * 1.50
final_price = marked * (1 - 0.10)
profit = final_price - cost
profit_percentage = (profit / cost) * 100
print(profit_percentage)

Problem: If a population quadruples every 12 hours, how many times larger will it be after 3 days?
Code:
hours = 3 * 24
periods = hours / 12
result = 4 ** periods
print(result)

Problem: Train X leaves at 60 mph. Three hours later, Train Y leaves on a parallel track at 90 mph. How far from the station does Y catch X?
Code:
speed_X = 60
speed_Y = 90
delay = 3
# X_distance = Y_distance -> 60(t + 3) = 90t -> 60t + 180 = 90t -> 30t = 180 -> t = 6
t = (speed_X * delay) / (speed_Y - speed_X)
distance = speed_Y * t
print(distance)

Problem: {prompt}
Code:"""

    messages = [
        {"role": "system", "content": PAL_SYSTEM_PROMPT}
    ]

    # Attempt 1: Ask Gemma to write the code
    MAX_ATTEMPTS = 2
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"  [PAL] Attempt {attempt}: Asking Gemma to write Python code...")
        local_result = router._run_local_with_timeout(messages, grammar=None, max_tokens=256)
        
        if local_result is None:
            print(f"  [PAL] Gemma timed out generating code.")
            continue
        
        raw_code = local_result["content"]
        
        # Strip markdown code fences if present
        code = re.sub(r'^```python\s*', '', raw_code, flags=re.MULTILINE)
        code = re.sub(r'^```\s*$', '', code, flags=re.MULTILINE)
        code = code.strip()
        
        if not code:
            print(f"  [PAL] Empty code generated.")
            continue
        
        print(f"  [PAL] Generated code:\n    {code[:150].replace(chr(10), chr(10) + '    ')}")
        
        # Execute the code
        output = _execute_python_code(code)
        
        if output:
            # Clean up the output — take just the last printed line
            lines = [l.strip() for l in output.split('\n') if l.strip()]
            final_answer = lines[-1] if lines else output
            print(f"  [PAL] Python output: {final_answer}")
            
            distilled = router.distiller.distill(final_answer)
            print(f"[{task_id}] Source: local_pal")
            print(f"[{task_id}] Answer: {safe_str(distilled[:120])}")
            
            return {
                "task_id": task_id,
                "answer": distilled,
                "source": "local_pal",
                "category": "math",
                "entropy": 0.0
            }
        
        # If code failed, add error context for retry
        if attempt < MAX_ATTEMPTS:
            print(f"  [PAL] Code execution failed. Retrying with error feedback...")
            messages.append({"role": "assistant", "content": raw_code})
            messages.append({"role": "user", "content": "That code had an error. Please write a corrected Python script that solves the problem and prints only the final numerical answer."})
    
    # All attempts failed — fall back to API
    print(f"[{task_id}] [PAL FAILED] All code attempts failed -> Escalating to API")
    final_answer = router._escalate_to_api(task, "math", 4096)
    distilled = router.distiller.distill(final_answer)
    
    print(f"[{task_id}] Source: api_escalation")
    print(f"[{task_id}] Answer: {safe_str(distilled[:120])}")
    
    return {
        "task_id": task_id,
        "answer": distilled,
        "source": "api_escalation",
        "category": "math",
        "entropy": 0.0
    }


if __name__ == "__main__":
    run_pipeline()
