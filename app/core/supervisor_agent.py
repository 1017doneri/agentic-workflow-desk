from typing import TypedDict,Annotated,Literal
from operator import add
from langchain_core.messages import AnyMessage, AIMessage
from app.core.refund_agent import init_state as init_refund_state


class SupervisorState(TypedDict):
    messages:Annotated[list[AnyMessage],add]
    next:str
    worker_result:str

import json
from langchain_core.messages import HumanMessage
from app.llm import llm
async def supervisor_node(state: SupervisorState):
    user_msg=state['messages'][-1]
    if  isinstance(user_msg,AIMessage):
        return {"next":"FINISH"}
    user_msg=user_msg.content
    prompt=f"""你是一个客服团队的主管。请判断用户的诉求，并分派给对应的专员：
-customer:咨询政策、查订单、闲聊。
-refund：明确要求退款、退货，明确的退款意图,并带有金额或订单号等
-FINISH：专员已经处理完毕，可以结束对话

用户输入：{user_msg}
请只输出一个词（customer/refund/FINISH）
"""
    result=await llm.ainvoke([HumanMessage(content=prompt)])
    next_worker=result.content.strip().lower()

    if next_worker not in ["customer","refund","FINISH"]:
        next_worker="customer"

    print(f"[Supervisor]分派任务给{next_worker}")
    return {"next":next_worker}

from app.core.customer_agent import build_customer_graph
from app.core.refund_agent import build_refund_graph

customer_agent=build_customer_graph()
refund_agent=build_refund_graph()

async def call_customer_agent(state: SupervisorState):
    print("[Worker]客服专员接手。。。")
    result=await customer_agent.ainvoke({"messages":state["messages"]})

    return {
        "messages":[result["messages"][-1]],
        "worker_result":result["messages"][-1].content,
    }

async def call_refund_agent(state: SupervisorState):
    print("[Refund]专员接手中。。。")

    user_msg=state['messages'][-1].content
    refund_input=init_refund_state(user_msg)
    result=await refund_agent.ainvoke(refund_input)

    final_result=result.get("final_result","退款处理中。。。")
    return {
        "messages":[AIMessage(final_result)],
        "worker_result":final_result
    }

from langgraph.graph import StateGraph,START,END


def route_supervisor(state:SupervisorState)->Literal["customer","refund","__end__"]:
    if state["next"]=="customer":
        return "customer"
    elif state["next"]=="refund":
        return "refund"
    else:
        return END


def build_supervisor_graph(checkpointer=None):
    builder = StateGraph(SupervisorState)
    builder.add_node("customer",call_customer_agent)
    builder.add_node("refund",call_refund_agent)
    builder.add_node("supervisor",supervisor_node)
    builder.add_edge(START,"supervisor")
    builder.add_conditional_edges("supervisor",route_supervisor,{
        "customer":"customer",
        "refund":"refund",
        END:END
    })
    builder.add_edge("customer","supervisor")
    builder.add_edge("refund","supervisor")

    return builder.compile(checkpointer=checkpointer)