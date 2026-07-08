"""
GBNF (Grammar-Based Network Format) definitions for constraining local model output.
This ensures the model output is strictly parsed and zero tokens are wasted on formatting fluff.
"""

from llama_cpp import LlamaGrammar

# 1. NER Grammar (Strict JSON)
# Forces output to strictly follow:
# { "persons": ["Name"], "organizations": ["Name"], "locations": ["Name"], "dates": ["Name"] }
NER_GRAMMAR_STRING = r'''
root ::= "{" ws "\"persons\"" ws ":" ws stringlist "," ws "\"organizations\"" ws ":" ws stringlist "," ws "\"locations\"" ws ":" ws stringlist "," ws "\"dates\"" ws ":" ws stringlist "}" ws
stringlist ::= "[" ws "]" | "[" ws string ("," ws string)* "]" ws
string ::= "\"" [^"]* "\"" ws
ws ::= [ \t\n]*
'''

# 2. Sentiment Grammar
# Forces output to be exactly one of the 4 valid labels
SENTIMENT_GRAMMAR_STRING = r'''
root ::= "positive" | "negative" | "neutral" | "mixed"
'''

def get_ner_grammar() -> LlamaGrammar:
    """Returns a parsed grammar forcing strict JSON output for Named Entity Recognition."""
    return LlamaGrammar.from_string(NER_GRAMMAR_STRING)

def get_sentiment_grammar() -> LlamaGrammar:
    """Returns a parsed grammar forcing exactly one sentiment word."""
    return LlamaGrammar.from_string(SENTIMENT_GRAMMAR_STRING)
