import streamlit as st
import sys
import os
import time

# Ensure src is in the path so we can import the router
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
from src.main import GemmaCascadeRouter

st.set_page_config(
    page_title="GemmaCascade AI Router",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS for a beautiful modern dark look ---
st.markdown("""
<style>
    .stApp {
        background-color: #0e1117;
    }
    .metric-card {
        background-color: #1e2127;
        padding: 20px;
        border-radius: 12px;
        border-left: 5px solid;
        box-shadow: 0 4px 6px rgba(0,0,0,0.2);
        margin-bottom: 20px;
        transition: transform 0.2s;
    }
    .metric-card:hover {
        transform: translateY(-2px);
    }
    .metric-value {
        font-size: 26px;
        font-weight: 700;
        color: #ffffff;
        margin-top: 5px;
    }
    .metric-label {
        font-size: 13px;
        text-transform: uppercase;
        letter-spacing: 1px;
        color: #9ca3af;
    }
    h1, h2, h3 {
        color: #f3f4f6;
        font-family: 'Inter', sans-serif;
    }
    .stTextArea textarea {
        background-color: #1f2937 !important;
        color: #f9fafb !important;
        border: 1px solid #374151 !important;
        border-radius: 8px !important;
    }
    .stTextArea textarea:focus {
        border-color: #3b82f6 !important;
        box-shadow: 0 0 0 1px #3b82f6 !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("🧠 GemmaCascade: Hybrid Token-Efficient Routing")
st.markdown("*A highly optimized AI agent that routes tasks locally (0 tokens) or escalates to the API based on task complexity and model confidence.*")

@st.cache_resource
def get_router():
    # Cache the router so we don't reload llama.cpp (or API client) on every interaction
    return GemmaCascadeRouter()

try:
    router = get_router()
except Exception as e:
    st.error(f"Failed to initialize router: {e}")
    st.stop()

prompt = st.text_area("Enter your prompt (Math, Logic, Factual, etc.):", height=120, placeholder="e.g. A merchant marks up goods by 40%. If he then offers a 20% discount on the marked price, what is his actual profit percentage?")

if st.button("Route & Process", type="primary"):
    if prompt.strip():
        with st.spinner("Analyzing and routing task..."):
            start_time = time.time()
            
            # Construct a mock task for the router
            task = {"task_id": "demo", "prompt": prompt.strip()}
            
            # Process the task through the exact same logic as the main pipeline
            result = router.process_task(task)
            
            duration = time.time() - start_time
            
            st.markdown("### Output Answer")
            
            # Determine color based on source
            source = result.get("source", "unknown")
            is_local = "local" in source.lower()
            
            # Display answer with a success box if local (0 tokens), warning box if API
            if is_local:
                st.success(f"**Final Answer:**\n\n{result.get('answer', '')}")
            else:
                st.warning(f"**Final Answer:**\n\n{result.get('answer', '')}")
            
            st.markdown("### Routing Intelligence")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown(f"""
                <div class="metric-card" style="border-left-color: #3b82f6;">
                    <div class="metric-label">Task Category</div>
                    <div class="metric-value">{result.get("category", "unknown").upper()}</div>
                </div>
                """, unsafe_allow_html=True)
                
            with col2:
                source_color = "#10b981" if is_local else "#ef4444"
                st.markdown(f"""
                <div class="metric-card" style="border-left-color: {source_color};">
                    <div class="metric-label">Execution Source</div>
                    <div class="metric-value">{source.upper()}</div>
                </div>
                """, unsafe_allow_html=True)
                
            with col3:
                entropy = result.get("entropy", 0.0)
                entropy_color = "#f59e0b" if entropy > 1.0 else "#10b981"
                st.markdown(f"""
                <div class="metric-card" style="border-left-color: {entropy_color};">
                    <div class="metric-label">Model Entropy</div>
                    <div class="metric-value">{entropy:.2f}</div>
                </div>
                """, unsafe_allow_html=True)
                
            with col4:
                st.markdown(f"""
                <div class="metric-card" style="border-left-color: #8b5cf6;">
                    <div class="metric-label">Time Taken</div>
                    <div class="metric-value">{duration:.2f}s</div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.error("Please enter a prompt first.")
