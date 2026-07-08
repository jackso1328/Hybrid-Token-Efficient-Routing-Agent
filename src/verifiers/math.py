import sympy
import re
from typing import Tuple, Optional

def verify_math_answer(prompt: str, gemma_answer: str, local_engine=None) -> Tuple[bool, Optional[str]]:
    """
    Verify Gemma's math answer using deterministic computation.
    Returns (is_correct, corrected_answer_if_wrong).
    """
    
    # We first try to extract numbers directly from the answer to find the final claim
    numbers_in_answer = re.findall(r'[\d,]+\.?\d*', gemma_answer)
    if not numbers_in_answer:
        # If there are no numbers in the answer, it's likely a logic failure
        return False, None
        
    gemma_number_str = numbers_in_answer[-1].replace(',', '')
    try:
        gemma_number = float(gemma_number_str)
    except ValueError:
        return False, None

    # Ask the engine to express the math problem as a pure Python expression
    if local_engine:
        expression_prompt = f"""<|im_start|>system
You are a calculator. The user provides a math problem and its answer.
Output ONLY the final mathematical calculation as a single Python expression. Do not output anything else.
Example: 80 * (1 - 0.25)<|im_end|>
<|im_start|>user
Problem: {prompt}
Claimed answer: {gemma_answer}<|im_end|>
<|im_start|>assistant
"""
        result = local_engine.generate(expression_prompt, max_tokens=50, temperature=0.0)
        expression = result["text"].strip()
        
        try:
            # Sanitize: only allow numbers, operators, parentheses
            clean_expr = re.sub(r'[^0-9+\-*/().,%\s]', '', expression)
            if clean_expr:
                computed_result = eval(clean_expr)
                
                # Check if it matches within a small epsilon (for floats)
                if abs(computed_result - gemma_number) < 0.01:
                    return True, None  # Math checks out!
                else:
                    # Fix it
                    corrected = gemma_answer.replace(numbers_in_answer[-1], str(round(computed_result, 4)))
                    return False, corrected
        except Exception:
            pass # Fallback to SymPy if eval fails
            
    # Try SymPy for symbolic math if simple eval didn't work
    if local_engine:
        sympy_prompt = f"""<|im_start|>system
Convert this math problem to a SymPy script that prints the final numeric answer.
Output ONLY the Python code. No markdown formatting.<|im_end|>
<|im_start|>user
{prompt}<|im_end|>
<|im_start|>assistant
"""
        result = local_engine.generate(sympy_prompt, max_tokens=200, temperature=0.0)
        sympy_code = result["text"].strip()
        
        namespace = {
            "sympy": sympy, "Eq": sympy.Eq, "solve": sympy.solve,
            "symbols": sympy.symbols, "Rational": sympy.Rational,
            "print": lambda x: namespace.update({"result": x})
        }
        try:
            # Dangerous in prod without ast checks, but acceptable in a constrained container
            exec(sympy_code, namespace)
            if "result" in namespace:
                computed_val = float(namespace["result"])
                if abs(computed_val - gemma_number) < 0.01:
                    return True, None
                else:
                    corrected = gemma_answer.replace(numbers_in_answer[-1], str(round(computed_val, 4)))
                    return False, corrected
        except Exception:
            pass
            
    # If we cannot deterministically verify, we reject it (Accuracy > Tokens)
    return False, None
