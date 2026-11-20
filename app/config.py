import os
from dotenv import load_dotenv
load_dotenv()

MODEL_NAME="deepseek-v4-flash"
LLM_API_KEY=os.getenv("OPENAI_API_KEY")
LLM_URL=os.getenv("OPENAI_URL")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "20"))        # 单次调用上限
LLM_MAX_ATTEMPTS = int(os.getenv("LLM_MAX_ATTEMPTS", "3")) # 最多几次
LLM_DEADLINE = float(os.getenv("LLM_DEADLINE", "45"))      #一次调用总预算
CHECKPOINTER_DB="refund.db"

APPROVAL_THRESHOLD=500.0
MAX_STEPS=10

KNOWLEDGE_DIR="data/knowledge"
CHROMA_DIR="data/chroma_db"
