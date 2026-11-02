import os
from dotenv import load_dotenv
load_dotenv()

MODEL_NAME="deepseek-v4-flash"
LLM_API_KEY=os.getenv("OPENAI_API_KEY")
LLM_URL=os.getenv("OPENAI_URL")

DB_URL="postgresql://postgres:agent123@localhost:5432/agentdb?sslmode=disable"
CHECKPOINTER_DB="refund.db"

APPROVAL_THRESHOLD=500.0
MAX_STEPS=10

KNOWLEDGE_DIR="data/knowledge"
CHROMA_DIR="data/chroma_db"
