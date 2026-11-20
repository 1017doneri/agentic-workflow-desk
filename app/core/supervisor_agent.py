from typing import TypedDict,Annotated,Literal
from operator import add
from langchain_core.messages import AnyMessage, AIMessage
from app.core.refund_agent import init_state as init_refund_state
from app.llm import degrade_on_llm_failure

class SupervisorState(TypedDict):
    messages:Annotated[list[AnyMessage],add]
    next:str
    worker_result:str

    refund_type: str
    amount: float
    policy_result: str
    needs_approval: bool
    approval: bool
    final_result: str
    refund_status:str

    step: int
    prompt_tokens: int
    completion_tokens: int
    request_id: str

import json
from langchain_core.messages import HumanMessage
from app.llm import get_llm
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
    result=await get_llm().ainvoke([HumanMessage(content=prompt)])
    next_worker=result.content.strip().lower()

    if next_worker not in ["customer","refund","FINISH"]:
        next_worker="customer"

    print(f"[Supervisor]分派任务给{next_worker}")
    return {"next":next_worker}

from app.core.customer_agent import build_customer_graph
from app.core.refund_agent import build_refund_graph


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
    builder.add_node("customer",build_customer_graph())
    builder.add_node("refund",build_refund_graph())
    #builder.add_node("supervisor",supervisor_node)
    builder.add_node("supervisor", degrade_on_llm_failure(supervisor_node))
    builder.add_edge(START,"supervisor")
    builder.add_conditional_edges("supervisor",route_supervisor,{
        "customer":"customer",
        "refund":"refund",
        END:END
    })
    builder.add_edge("customer","supervisor")
    builder.add_edge("refund","supervisor")

    return builder.compile(checkpointer=checkpointer)