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

# --- Custom CSS for a beautiful modern light look ---
st.markdown("""
<style>
    /* Main Background */
    .stApp {
        background-color: #f8fafc;
    }
    
    /* Typography */
    h1, h2, h3 {
        color: #1e293b;
        font-family: 'Inter', 'Segoe UI', sans-serif;
        font-weight: 800;
    }
    
    /* Input Text Area */
    .stTextArea textarea {
        background-color: #ffffff !important;
        color: #334155 !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 12px !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
        font-size: 16px;
    }
    .stTextArea textarea:focus {
        border-color: #3b82f6 !important;
        box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2) !important;
    }
    
    /* Metric Cards */
    .metric-card {
        background-color: #ffffff;
        padding: 24px;
        border-radius: 16px;
        border-top: 6px solid;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -2px rgba(0, 0, 0, 0.025);
        margin-bottom: 20px;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
    }
    .metric-value {
        font-size: 28px;
        font-weight: 800;
        color: #0f172a;
        margin-top: 8px;
    }
    .metric-label {
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        font-weight: 600;
        color: #64748b;
    }
    
    /* Success/Warning Boxes */
    div[data-testid="stSuccess"], div[data-testid="stWarning"] {
        border-radius: 12px;
        border: none;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
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
                <div class="metric-card" style="border-top-color: #3b82f6;">
                    <div class="metric-label">Task Category</div>
                    <div class="metric-value">{result.get("category", "unknown").upper()}</div>
                </div>
                """, unsafe_allow_html=True)
                
            with col2:
                source_color = "#10b981" if is_local else "#ef4444"
                st.markdown(f"""
                <div class="metric-card" style="border-top-color: {source_color};">
                    <div class="metric-label">Execution Source</div>
                    <div class="metric-value">{source.upper()}</div>
                </div>
                """, unsafe_allow_html=True)
                
            with col3:
                entropy = result.get("entropy", 0.0)
                entropy_color = "#f59e0b" if entropy > 1.0 else "#10b981"
                st.markdown(f"""
                <div class="metric-card" style="border-top-color: {entropy_color};">
                    <div class="metric-label">Model Entropy</div>
                    <div class="metric-value">{entropy:.2f}</div>
                </div>
                """, unsafe_allow_html=True)
                
            with col4:
                st.markdown(f"""
                <div class="metric-card" style="border-top-color: #8b5cf6;">
                    <div class="metric-label">Time Taken</div>
                    <div class="metric-value">{duration:.2f}s</div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.error("Please enter a prompt first.")
