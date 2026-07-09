import ast
import re
from typing import Tuple, Optional

def extract_code_block(text: str) -> Optional[str]:
    """Extracts python code from a markdown code block."""
    matches = re.findall(r'```(?:python|py)?(.*?)```', text, re.DOTALL)
    if matches:
        return matches[0].strip()
    return None

def verify_code_answer(gemma_answer: str, task_type: str = "code_gen") -> Tuple[bool, Optional[str]]:
    """
    Verify generated/debugged code is at minimum syntactically valid.
    """
    code = extract_code_block(gemma_answer)
    if not code:
        # If no code block is found but the task is coding, it's a fail
        return False, "No code block found."
        
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"
        
    # Check for obviously undefined variables
    defined_names = set()
    used_names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined_names.add(node.name)
            if hasattr(node, 'args') and getattr(node.args, 'args', None):
                for arg in node.args.args:
                    defined_names.add(arg.arg)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store):
                defined_names.add(node.id)
            elif isinstance(node.ctx, ast.Load):
                used_names.add(node.id)
                
    builtins = set(dir(__builtins__)) if isinstance(__builtins__, dict) else set(dir(__builtins__))
    undefined = used_names - defined_names - builtins - {'self', 'cls'}
    
    if undefined:
        return False, f"Potentially undefined variables: {undefined}"
        
    # Check for function definition if it's code generation
    if task_type == "code_gen":
        has_function = any(isinstance(n, ast.FunctionDef) for n in ast.walk(tree))
        if not has_function:
            return False, "No function definition found."
            
    # Sandboxed quick execution (only if it defines a function, not a destructive script)
    try:
        if any(isinstance(n, ast.FunctionDef) for n in ast.walk(tree)):
            # We execute it just to ensure it defines correctly (no runtime crashes on def)
            exec(code, {"__builtins__": {}})
    except Exception as e:
        return False, f"Runtime error on definition: {type(e).__name__}: {e}"
        
    return True, None
