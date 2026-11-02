import asyncio
import time
from typing import TypedDict,Annotated
from operator import add

from langgraph.graph import StateGraph,START,END
from langchain_core.messages import ToolMessage

from app.llm import llm
from app.config import MAX_STEPS

class AgentState(TypedDict):
    messages:Annotated[list,add]
    step:int
    prompt_tokens:int
    completion_tokens:int
    request_id:str

MCP_TOOLS=[]
MCP_TOOL_MAP={}
llm_with_tools=None

def setup_tools(tools):
    global MCP_TOOLS,MCP_TOOL_MAP,llm_with_tools
    MCP_TOOLS.append(tools)
    MCP_TOOL_MAP={tool.name: tool for tool in tools}
    llm_with_tools=llm.bind_tools(tools)

async def call_llm(state:AgentState):
    print(f"[call_llm] 当前消息数：{len(state['messages'])}")
    msg=await llm_with_tools.ainvoke(state["messages"])
    usage=msg.usage_metadata or {}
    input_tokens=usage.get("input_tokens",0)
    output_tokens=usage.get("output_tokens",0)
    print(f"输入{input_tokens},输出{output_tokens}")

    return {
        "messages":[msg],
        "step":state.get("step",0)+1,
        "prompt_tokens":state.get("prompt_tokens",0)+input_tokens,
        "completion_tokens":state.get("completion_tokens",0)+output_tokens,
    }

async def run_one_tool(tc):
    name=tc["name"]
    args=tc["args"]
    print(f"[run_tools]调用{name}（{args}）")

    try:
        if name in MCP_TOOL_MAP:
            result=await asyncio.wait_for(
                MCP_TOOL_MAP[name].ainvoke(args),
                timeout=10,
            )
        else:
            result=f"未知工具{name}"
    except asyncio.TimeoutError:
        result=f"工具{name}超时"
    except Exception as e:
        result=f"工具执行失败{name}：{e}"

    return ToolMessage(content=str(result),tool_call_id=tc["id"])

async def run_tools(state:AgentState):
    last=state["messages"][-1]
    start=time.time()
    results=await asyncio.gather(
        *[run_one_tool(tool) for tool in last.tool_calls]
    )
    elapsed=time.time()-start
    print(f"共执行了{len(results)}个工具，耗时{elapsed}秒")
    return {
        "messages":list(results),
    }

def should_continue(state:AgentState):
    if state.get("step",0)>=MAX_STEPS:
        print(f"[警告]达到最大步数{MAX_STEPS},强制结束")
        return END

    last=state["messages"][-1]
    if last.tool_calls:
        return"run_tools"
    return END

def build_customer_graph(checkpointer=None):
    graph=StateGraph(AgentState)
    graph.add_node("call_llm",call_llm)
    graph.add_node("run_tools",run_tools)
    graph.add_edge(START,"call_llm")
    graph.add_conditional_edges("call_llm",should_continue)
    graph.add_edge("run_tools","call_llm")

    return graph.compile(checkpointer=checkpointer)