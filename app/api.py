import os
import asyncio
import sys
import uuid
from contextlib import asynccontextmanager
if sys.platform=="win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
import traceback
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
import json
from fastapi.responses import StreamingResponse
from app.core.refund_agent import(
RefundState,
build_refund_graph,
init_state
)
from langgraph.types import Command
from app.core.rag import get_embedder,get_reranker


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

import jwt
from datetime import datetime,timedelta,timezone
from fastapi import Depends,HTTPException,status
from fastapi.security import OAuth2PasswordBearer,OAuth2PasswordRequestForm
from argon2 import PasswordHasher

@asynccontextmanager
async def lifespan(app:FastAPI):
    global customer_agent,refund_agent,supervisor_agent
    env=os.environ.copy()
    env["PYTHONIOENCODING"]="utf-8"
    await asyncio.to_thread(get_embedder)
    await asyncio.to_thread(get_reranker)
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
                conninfo=os.getenv("DATABASE_URL","postgresql://postgres:postgres@localhost:5432/langgraph"),
                max_size=20,
                kwargs={"autocommit":True,"prepare_threshold":0,"row_factory":dict_row}
            ) as pool:
                checkpointer=AsyncPostgresSaver(pool)
                await checkpointer.setup()
                await init_user_db(pool)

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
                if user_pool:
                    await user_pool.close()

    print("Agent关闭")

app=FastAPI(lifespan=lifespan)

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "").strip()
if len(SECRET_KEY)<16:
    raise RuntimeError(
        "JWT_SECRET_KEY未设置或过短，拒绝启动"
        "生成方法：python -c \"import secrets;print(secrets.token_urlsafe(32))\""
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

ph = PasswordHasher()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

user_pool: AsyncConnectionPool|None=None

async def init_user_db(pool:AsyncConnectionPool|None=None):
    global user_pool
    user_pool=pool
    async with pool.connection() as conn:
        await conn.execute("""
           CREATE TABLE IF NOT EXISTS users(
           username  TEXT PRIMARY KEY,
           hashed_password TEXT NOT NULL,
           created_at TIMESTAMPTZ DEFAULT now()
           )
        """)
        await conn.commit()

def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": user_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise exc
        return user_id
    except jwt.PyJWTError:
        raise exc


class RegisterRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/register")
async def register(req: RegisterRequest):
    try:
        async with user_pool.connection() as conn:
            await conn.execute(
                "INSERT INTO users (username,hashed_password) VALUES (%s,%s)",
                (req.username,ph.hash(req.password)),
            )
            await conn.commit()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(400,"User already exists")
    return {"status":"ok","user_id":req.username}

@app.post("/auth/login")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    async with user_pool.connection() as conn:
        result=await conn.execute(
            "SELECT hashed_password FROM users WHERE username=%s",
            [form.username],
        )
        row= await result.fetchone()

    if not row:
        raise HTTPException(401,"Incorrect username or password")
    try:
        ph.verify(row["hashed_password"],form.password)
        print(f"[LOGIN] 密码验证通过: {form.username}")
    except Exception as e:
        print(f"[LOGIN] 密码验证失败: {form.username} / {type(e).__name__}: {e}")
        raise HTTPException(401,"Incorrect username or password")

    return {
        "access_token":create_access_token(form.username),
        "token_type":"bearer",
        "user_id":form.username
    }



class ChatRequest(BaseModel):
    question:str

class ChatResponse(BaseModel):
    answer:str
    needs_approval:bool=False


@app.post("/agent",response_model=ChatResponse)
async def agent_chat(req:ChatRequest,current_user:str=Depends(get_current_user)):
    config={"configurable":{"thread_id":f"agent_{current_user}"}}
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
    decision:str=""

@app.post("/agent/approval",response_model=ChatResponse)
async def agent_approval(req:ApprovalRequest,current_user:str=Depends(get_current_user)):
    config={"configurable":{"thread_id":f"agent_{current_user}"}}
    result=await supervisor_agent.ainvoke(
        Command(resume=req.decision),
        config
    )
    return ChatResponse(answer=result.get("worker_result","处理完成"))

def sse_pack(event:str,data:dict)->str:
    return f"event:{event}\ndata:{json.dumps(data,ensure_ascii=False)}\n\n"


@app.post("/chat",response_model=ChatResponse)
async def chat(req:ChatRequest,current_user:str=Depends(get_current_user)):
    config={"configurable":{"thread_id":f"chat_{current_user}"}}
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

class RefundResponse(BaseModel):
    answer:str
    needs_approval:bool=False

@app.post("/refund",response_model=RefundResponse)
async def refund(req:RefundRequest,current_user:str=Depends(get_current_user)):
    config={"configurable":{"thread_id":f"refund_{current_user}"}}

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
    decision:str

@app.post("/refund/approval",response_model=RefundResponse)
async def refund_approval(req:RefundApprovalRequest,current_user:str=Depends(get_current_user)):
    config={"configurable":{"thread_id":f"refund_{current_user}"}}

    result=await refund_agent.ainvoke(
        Command(resume=req.decision),
        config
    )
    return RefundResponse(answer=result["final_result"])

@app.post("/agent/stream")
async def agent_stream(req:ChatRequest,current_user:str=Depends(get_current_user)):
    thread_id=f"agent_{current_user}"

    async def event_generator():
        config={"configurable":{"thread_id":thread_id}}
        got_token = False
        try:
            input_state={
                "messages":[HumanMessage(content=req.question)],
                "next":""
            }
            async for mode,data in supervisor_agent.astream(
                input_state,
                config,
                stream_mode=["messages","updates"],
            ):
                if mode =="messages":
                    msg_chunk,metadata=data
                    node=metadata.get("langgraph_node","")
                    if node=="supervisor":
                        continue
                    text=getattr(msg_chunk,"content","")
                    if text:
                        got_token=True
                        yield sse_pack("token",{"text":text})

                elif mode=="updates":
                    if "__interrupt__" in data:
                        info=data["__interrupt__"][0].value
                        yield sse_pack("interrupt",{
                            "question":info.get("question","请审批"),
                            "policy_result":info.get("policy_result",""),
                        })
            state=await supervisor_agent.aget_state(config)
            if not state.tasks or not state.tasks[0].interrupts:
                answer=""
                if not got_token:
                    answer = state.values.get("worker_result", "")
                    if not answer and state.values.get("messages"):
                      answer=state.values["messages"][-1].content
                yield sse_pack("done",{"answer":answer})

        except Exception as e:
            traceback.print_exc()
            yield sse_pack("error",{"message":str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )