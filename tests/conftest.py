import os
import uuid
import pytest
import httpx
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from langchain_core.messages import AIMessage
from app import api as api_module
from app.api import app


TEST_DB_URL=os.getenv("TEST_DB_URL","postgresql://postgres:postgres@127.0.0.1:5432/langgraph")

class FakeLLM:

    def __init__(self,mapping:dict[str,str]):
        self.mapping = mapping
        self.calls:list[str]=[]

    async def ainvoke(self,messages,**kwargs):
        system=messages[0].content if messages else ""
        self.calls.append(system[:40])
        for marker,reply in self.mapping.items():
            if marker in system:
                return AIMessage(content=reply)
        raise AssertionError(f"未預期的LLM調用：{system[:100]}")

    def bind_tools(self,tools):
        return self


DEFAULT_REPLIES = {
    "输入安全检测器": '{"safe": true, "reason": "正常业务请求"}',
    "退款意图解析器": '{"order_id": "A1002", "reason": "不想要了"}',
    "检索查询改写器": '{"queries": ["退款政策"]}',
    "退款政策审核员": '{"sufficient": true, "needs_approval": true, "reason": "金额超过阈值"}',
    "客服团队的主管": "refund",
}

@pytest.fixture
def fake_llm(monkeypatch):
    def _install(**overrides):
        replies={**DEFAULT_REPLIES,**overrides}
        fake=FakeLLM(replies)
        for target in (
            "app.core.refund_agent.get_llm",
            "app.core.customer_agent.get_llm",
            "app.core.supervisor_agent.get_llm",
            "app.safety.input_guard.get_llm",
        ):
            monkeypatch.setattr(target,lambda:fake)
        return fake
    return _install

@pytest.fixture
def fake_orders(monkeypatch):

    def _install(orders:dict[str,dict],first_time:bool=True):
        async def _fetch(order_id):
            return orders.get(order_id)
        records=[]
        async def _record(order_id,thread_id,amount,decision):
            records.append(order_id)
            return first_time

        monkeypatch.setattr("app.core.refund_agent.fetch_order", _fetch)
        monkeypatch.setattr("app.core.refund_agent.record_refund", _record)
        return records

    return _install


@pytest.fixture(autouse=True)
def fake_search(monkeypatch):
    async def _search(query,*args,**kwargs):
        return "[refund.txt]未發貨可申請退款；生鮮不支持無理由；金額超過500需要人工審批"
    monkeypatch.setattr("app.core.refund_agent.asearch_knowledge",_search)



@pytest.fixture
async def db_pool():
    pool=AsyncConnectionPool(
        conninfo=TEST_DB_URL,
        open=False,
        kwargs={"autocommit":True,"row_factory":dict_row}
    )
    await pool.open(wait=True)
    async with pool.connection() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
        username TEXT PRIMARY KEY,
        hashed_password TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now()
        )
        """)
    yield pool
    await pool.close()

@pytest.fixture
async def client(db_pool,monkeypatch):
    monkeypatch.setattr(api_module,"user_pool",db_pool)
    transport=httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,base_url="http://test")as c:
       yield c

@pytest.fixture
def unique_user():
    return f"test_{uuid.uuid4().hex[:8]}"