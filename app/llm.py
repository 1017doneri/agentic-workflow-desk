from functools import lru_cache

from langchain_openai import ChatOpenAI
import os

@lru_cache
def get_llm()->ChatOpenAI:
    return ChatOpenAI(
        model="deepseek-v4-flash",
        temperature=0.5,
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPEMAI_BASE_URL")
    )