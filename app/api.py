import os
import asyncio
import sys
import uuid
from contextlib import asynccontextmanager
if sys.platform=="win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
from app.core.supervisor_agent import build_supervisor_graph

from app.core.refund_agent import(
RefundState,
build_refund_graph,
init_state
)
from langgraph.types import Command

from app.config import DB_URL
from app.core.customer_agent import(
AgentState,
call_llm,
run_tools,
should_continue,
setup_tools
)

customer_agent=None
refund_agent=None
supervisor_agent=None


@asynccontextmanager
async def lifespan(app:FastAPI):
    global customer_agent,refund_agent,supervisor_agent
    env=os.environ.copy()
    env["PYTHONIOENCODING"]="utf-8"

    server_params=StdioServerParameters(
        command=sys.executable,
        args=["-m","app.mcp.server"],
        env=env,
    )

    async with stdio_client(server_params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()

            tools= await load_mcp_tools(session)
            setup_tools(tools)

            async with AsyncConnectionPool(
                conninfo=DB_URL,
                max_size=20,
                kwargs={"autocommit":True,"prepare_threshold":0}
            ) as pool:
                checkpointer=AsyncPostgresSaver(pool)
                await checkpointer.setup()

                graph=StateGraph(AgentState)
                graph.add_node("call_llm",call_llm)
                graph.add_node("run_tools", run_tools)
                graph.set_entry_point("call_llm")
                graph.add_conditional_edges("call_llm", should_continue)
                graph.add_edge("run_tools", "call_llm")

                customer_agent=graph.compile(checkpointer=checkpointer)
                refund_agent=build_refund_graph(checkpointer=checkpointer)
                supervisor_agent=build_supervisor_graph(checkpointer=checkpointer)
                print("Agent初始化完成")

                yield

    print("Agent关闭")

app=FastAPI(lifespan=lifespan)

class ChatRequest(BaseModel):
    question:str
    user_id:str="default"

class ChatResponse(BaseModel):
    answer:str


@app.post("/agent",response_mode=ChatResponse)
async def agent_chat(req:ChatRequest):
    config={"configurable":{"thread_id":f"agent_{req.user_id}"}}
    result=await supervisor_agent.ainvoke(
        {
            "messages":[HumanMessage(content=req.question)],
            "next":""
        },
        config
    )

    if "__interrupt__" in result:
        info=result["__interrupt__"][0].value
        return ChatResponse(
            answer=f"[需要审批]{info.get('question','请审批')}\n政策核对：{info.get('policy_result','')}",
            needs_approval=True
        )
    return ChatResponse(
        answer=result.get("worker_result",result["messages"][-1].content),
    )


class ApprovalRequest(BaseModel):
    user_id:str
    decision:str

@app.post("/agent/approval",response_model=ChatResponse)
async def agent_approval(req:ApprovalRequest):
    config={"configurable":{"thread_id":f"approval_{req.user_id}"}}
    result=await supervisor_agent.ainvoke(
        Command(resume=req.question),
        config
    )
    return ChatResponse(answer=result.get("worker_result","处理完成"))

@app.post("/chat",response_model=ChatResponse)
async def chat(req:ChatRequest):
    config={"configurable":{"thread_id":req.user_id}}
    request_id=str(uuid.uuid4())[:8]

    result=await customer_agent.ainvoke(
        {
            "messages":[HumanMessage(content=req.question)],
            "step":0,
            "prompt_tokens":0,
            "completion_tokens":0,
            "request_id":request_id,
        },
        config
    )
    return ChatResponse(answer=result["messages"][-1].content)

class RefundRequest(BaseModel):
    question:str
    user_id:str="default"

class RefundResponse(BaseModel):
    answer:str
    needs_approval:bool=False

@app.post("/refund",response_model=RefundResponse)
async def refund(req:RefundRequest):
    config={"configurable":{"thread_id":f"refund_{req.user_id}"}}

    result=await refund_agent.ainvoke(
        init_state(req.question),
        config
    )

    if "__interrupt__" in result:
        info=result["__interrupt__"][0].value
        return RefundResponse(
            answer=f"[需要审批]{info['question']}\n政策核对：{info['policy_result']}",
            needs_approval=True
        )

    return RefundResponse(answer=result["final_result"])

class RefundApprovalRequest(BaseModel):
    user_id:str
    decision:str

@app.post("/refund/approval",response_model=RefundResponse)
async def refund_approval(req:RefundApprovalRequest):
    config={"configurable":{"thread_id":f"refund_{req.user_id}"}}

    result=await refund_agent.ainvoke(
        Command(resume=req.decision),
        config
    )
    return RefundResponse(answer=result["final_result"])