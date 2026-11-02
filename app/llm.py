from app.config import LLM_API_KEY,LLM_URL,MODEL_NAME
from langchain_openai import ChatOpenAI

llm=ChatOpenAI(
    model=MODEL_NAME,
    api_key=LLM_API_KEY,
    base_url=LLM_URL
)

