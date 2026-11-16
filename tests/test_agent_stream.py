import json
import pytest
from langchain_core.messages import AIMessageChunk
from app.api import create_access_token


class FakeState:
    def __init__(self,interrupts=None,worker_result=""):
        self.tasks=[]
        self.values={"worker_result":worker_result,"messages":[]}
        if interrupts is not None:
                self.tasks=[type("Task",(),{"interrupts":interrupts})()]

class FakeGraph:
    def __init__(self,tokens=None,interrupt=None,worker_result="",supervisor_noise=None):
        self._tokens=tokens or []
        self._interrupt=interrupt
        self._worker_result=worker_result
        self._noise=supervisor_noise or []

    def astream(self,input_state,config,stream_mode):
        async def gen():
            for word in self._noise:
                yield("messages",(
                    AIMessageChunk(content=word),
                    {"langgraph_node":"supervisor"}
                ))
            for t in self._tokens:
                yield ("messages",(
                    AIMessageChunk(content=t),
                    {"langgraph_node":"call_llm"}
                ))
            if self._interrupt is not None:
                yield ("updates",{
                    "__interrupt__":[type("Intr",(),{"value":self._interrupt})()]
                })
        return gen()

    async def aget_state(self,config):
        interrupts=[]
        if self._interrupt is not None:
            interrupts=[type("Intr",(),{"value":self._interrupt})()]
        return FakeState(interrupts=interrupts,worker_result=self._worker_result)

@pytest.fixture
def auth_token():
    return create_access_token("stream_tester")

async def parse_sse(response):
    events=[]
    current={}
    async for line in response.aiter_lines():
        if not line:
            if current:
                events.append(current)
                current={}
            continue
        if line.startswith("event:"):
            current["event"]=line.split(":",1)[1].strip()
        elif line.startswith("data:"):
            current["data"]=json.loads(line.split(":",1)[1].strip())
    if current:
        events.append(current)
    return events

async def test_stream_requires_auth(client):
    r=await client.post("/agent/stream",json={"question":"你好"})
    assert r.status_code==401

async def test_stream_returns_tokens_and_done(client,auth_token,monkeypatch):

    fake=FakeGraph(tokens=["你","好","!"],worker_result="你好！")
    monkeypatch.setattr("app.api.supervisor_agent",fake)
    async with client.stream(
        "POST",
        "/agent/stream",
        json={"question":"你好"},
        headers={"Authorization":f"Bearer {auth_token}"}
    )as r:
        assert r.status_code==200
        events=await parse_sse(r)
    token_texts=[e["data"]["text"]for e in events if e["event"]=="token"]
    assert token_texts==["你","好","!"]

    done_events=[e for e in events if e["event"]=="done"]
    assert len(done_events)==1
    assert done_events[0]["data"]["answer"]==""

async def test_stream_emits_interrupt(client,auth_token,monkeypatch):
    fake=FakeGraph(
        tokens=[],
        interrupt={"question":"请审批","policy_result":"超过阈值"},
    )
    monkeypatch.setattr("app.api.supervisor_agent",fake)

    async with client.stream(
        "POST",
        "/agent/stream",
        json={"question":"退款3000"},
        headers={"Authorization":f"Bearer {auth_token}"},
    ) as r:
        events=await parse_sse(r)

    intr=[e for e in events if e["event"]=="interrupt"]
    assert len(intr)==1
    assert intr[0]["data"]["question"]=="请审批"
    assert intr[0]["data"]["policy_result"]=="超过阈值"


async def test_stream_filters_supervisor_tokens(client,auth_token,monkeypatch):
    fake=FakeGraph(
        tokens=["您好","，","在"],
        supervisor_noise=["customer"]
    )
    monkeypatch.setattr("app.api.supervisor_agent",fake)
    async with client.stream(
        "POST",
        "/agent/stream",
        json={"question":"你好"},
        headers={"Authorization":f"Bearer {auth_token}"}
    )as r:
        events= await parse_sse(r)

    all_text="".join(e["data"]["text"] for e in events if e["event"]=="token")
    assert "customer" not in all_text
    assert "您好" in all_text
