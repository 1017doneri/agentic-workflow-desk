import json
import re
from typing import TypedDict, Annotated
from operator import add

from langchain_core.messages import HumanMessage, AIMessage,SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from pydantic import BaseModel,Field
from app.llm import get_llm
from app.config import APPROVAL_THRESHOLD
from app.core.rag import search_knowledge
from app.safety.input_guard import is_safe_input
from app.safety.output_guard import desensitize
from app.safety.audit import audit_log
from langchain_core.output_parsers import PydanticOutputParser
from app.core.parsing import clean_json
from app.orders import fetch_order,record_refund

class RefundState(TypedDict):
    messages: Annotated[list, add]
    order_id:str
    refund_type: str
    amount: float
    policy_result: str
    needs_approval: bool
    approval: bool
    final_result: str
    refund_reason:str

def init_state(question:str)->RefundState:
    return {
        "messages":[HumanMessage(content=question)],
        "order_id":"",
        "refund_type":"",
        "amount":0,
        "policy_result":"",
        "needs_approval":False,
        "approval":False,
        "final_result":"",
        "refund_reason":"",
    }


async def input_guard_node(state: RefundState):
    """语义安全分类，拦截 Prompt 注入/越狱"""
    user_msg = state["messages"][-1].content
    safe, reason = await is_safe_input(user_msg)

    if not safe:
        print(f"[InputGuard] 拦截：{reason}")
        result = "您的请求包含不安全内容，已被拦截。如有疑问请联系人工客服。"
        return {
            "final_result": result,
            "messages": [AIMessage(content=result)],
        }

    print(f"[InputGuard] 通过：{reason}")
    return {}


class RefundPlan(BaseModel):
    order_id:str=Field(description="订单号，用户没提就留空")
    reason:str=Field(default="",description="用户给出的退款原因")

plan_parser=PydanticOutputParser(pydantic_object=RefundPlan)

PLANNER_SYSTEM_PROMPT = f"""你是退款意图解析器。从用户消息中提取：
- order_id:用户想要退款的订单号，如果用户没有给出订单号，留空字符串
- reason：退款原因简述（可选）

请严格按以下 json 格式输出，不要任何额外文本、不要 markdown 代码块：
{plan_parser.get_format_instructions()}
"""

async def planner_node(state: RefundState):
    user_msg = state["messages"][-1].content
    llm = get_llm()

    resp = await llm.ainvoke([
        SystemMessage(content=PLANNER_SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ])

    try:
        plan: RefundPlan = plan_parser.parse(clean_json(resp.content))
    except Exception as e:
        print(f"[Planner] 解析失败，原始返回：{resp.content!r}, 错误：{e}")
        raise

    return {
        "order_id":plan.order_id,
        "refund_reason": plan.reason,
    }


async def load_order_node(state:RefundState):
    order_id=state.get("order_id","").strip()
    if not order_id:
        msg="未提供订单号，无法核对退款金额，请转人工处理"
        return {"final_result":msg,"messages":[AIMessage(content=msg)]}

    order=await fetch_order(order_id)
    if order is None:
        msg = f"未查询到订单 {order_id}，已转人工核实。"
        return {"final_result": msg, "messages": [AIMessage(content=msg)]}

    print(f"[Order] {order_id} → {order['category']} / {order['amount']} 元 / {order['status']}")
    return {
        "refund_type": order["category"],
        "amount": float(order["amount"]),
    }


def route_after_load_order(state: RefundState):
    if state.get("final_result"):
        return "output_guard"
    return "policy"


class QueryRewrite(BaseModel):
    queries:list[str]=Field(description="2-3个改写后的检索查询，每个查询是一个完整短语，不要重复")

class PolicyDecision(BaseModel):
    sufficient:bool=Field(description="检索到的政策是否足以判断")
    needs_approval:bool=Field(description="是否需要人工审批,判断模糊时设为true")
    reason:str=Field(default="",description="简要说明判断理由")


rewrite_parser = PydanticOutputParser(pydantic_object=QueryRewrite)
decision_parser = PydanticOutputParser(pydantic_object=PolicyDecision)

REWRITE_SYSTEM_PROMPT = f"""你是检索查询改写器。根据用户的退款请求，生成 2-3 个用于检索退款政策知识库的查询。
每个查询是一个简短完整的中文短语，不要重复，不要包含订单号。

请严格按以下 json 格式输出，不要任何额外文本、不要 markdown 代码块：
{rewrite_parser.get_format_instructions()}
"""

DECISION_SYSTEM_PROMPT = f"""你是退款政策审核员。根据检索到的政策文本，判断这笔退款是否符合政策、是否需要人工审批。
判断规则：
- 金额超过 {APPROVAL_THRESHOLD} 元：needs_approval=true
- 生鲜类不支持无理由退款：needs_approval=true
- 政策文本无法明确覆盖用户情况：sufficient=false, needs_approval=true
- 其余情况按政策文本直接判断

请严格按以下 json 格式输出，不要任何额外文本、不要 markdown 代码块：
{decision_parser.get_format_instructions()}
"""


async def policy_agent(state: RefundState):
    """查询改写 + 多查询检索 + 自我反思 + 二次检索"""
    user_msg=state["messages"][-1].content
    refund_type=state.get("refund_type","其他")
    amount=state.get("amount",0.0)
    llm=get_llm()
    resp = await llm.ainvoke([
        SystemMessage(content=REWRITE_SYSTEM_PROMPT),
        HumanMessage(content=f"用户请求：{user_msg}\n退款类型：{refund_type}\n退款金额：{amount}"),
    ])
    try:
        rewrite: QueryRewrite = rewrite_parser.parse(clean_json(resp.content))
    except Exception as e:
        print(f"[Policy] 改写解析失败，原始返回：{resp.content!r}, 错误：{e}")
        raise

    queries = rewrite.queries or [f"{refund_type}退款政策"]
    print(f"[Policy] 改写后的查询：{queries}")

    contexts = []
    for q in queries:
        result = search_knowledge(q)
        if result:
            contexts.extend(result if isinstance(result, list) else [result])
    print(f"[Policy] 检索到 {len(contexts)} 段")

    context_text = "\n\n".join(contexts) if contexts else "(无检索结果)"

    resp = await llm.ainvoke([
        SystemMessage(content=DECISION_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"用户请求：{user_msg}\n"
            f"退款类型：{refund_type}\n"
            f"金额：{amount}元\n\n"
            f"检索到的政策：\n{context_text}"
            ))
        ])
    try:
        reflection:PolicyDecision=decision_parser.parse(clean_json(resp.content))
    except Exception as e:
        print(f"[Policy]反思解析失败，原始返回：{resp.content!r},错误：{e}")
        raise

    print(f"[Policy]反思：sufficient={reflection.sufficient},reason={reflection.reason}")

    if not reflection.sufficient:
        extra_query=f"{refund_type}退款政策{reflection.reason}" if reflection.reason else f"{refund_type}退款政策，特殊情况"
        print(f"[Policy]二次检索补充{extra_query}")
        extra=search_knowledge(extra_query)
        if extra:
            contexts.extend(extra if isinstance(extra,list)else [extra])
            context_text="\n\n".join(contexts)

        resp = await llm.ainvoke([
            SystemMessage(content=DECISION_SYSTEM_PROMPT),
            HumanMessage(content=(
                f"用户请求：{user_msg}\n"
                f"退款类型：{refund_type}\n"
                f"金额：{amount}元\n\n"
                f"补充后的政策：\n{context_text}"
            )),
        ])
        try:
            reflection = decision_parser.parse(clean_json(resp.content))
        except Exception as e:
            print(f"[Policy] 二次反思解析失败，原始返回：{resp.content!r}, 错误：{e}")
            raise
        print(f"[Policy]二次反思：sufficient={reflection.sufficient}"
              f"needs_approval={reflection.needs_approval}")

    needs_approval=reflection.needs_approval or amount>=APPROVAL_THRESHOLD

    print(f"[Policy]结果={reflection.reason}，需要审批={needs_approval}")

    return {
        "policy_result":reflection.reason,
        "needs_approval":needs_approval
    }

async def approval_node(state: RefundState, config: RunnableConfig):
    """高风险操作，暂停等待人工确认"""
    decision = interrupt({
        "question": f"用户申请退款 {state['amount']} 元（{state['refund_type']}），是否批准？",
        "policy_result": state["policy_result"],
        "options": ["y", "n"],
    })

    thread_id = config["configurable"]["thread_id"]
    approved = decision == "y"
    print(f"[Approval] 人工决策：{decision}")

    audit_log(
        thread_id=thread_id,
        node="approval",
        refund_type=state["refund_type"],
        amount=state["amount"],
        policy_result=state["policy_result"],
        needs_approval=True,
        approval=approved,
    )

    return {"approval": approved}


async def executor_node(state: RefundState,config:RunnableConfig):
    """执行退款操作"""
    if state.get("needs_approval") and not state.get("approval"):
        result = "退款申请未通过审批，已拒绝。"
    elif state["policy_result"] and "不符合" in state.get("policy_result",""):
        result = f"退款申请不符合政策：{state['policy_result']}"
    else:
        thread_id =config["configurable"]["thread_id"]
        first_time=await record_refund(
            state["order_id"],thread_id,state["amount"],"approved"
        )
        if not first_time:
            result=f"订单{state['order_id']}已经退款过，请勿重复退款"
        else:
            result=f"退款{state['amount']}元已经处理，预计24小时内到账"

    print(f"[Executor] {result}")

    return {
        "final_result": result,
        "messages": [AIMessage(content=result)],
    }


async def output_guard_node(state: RefundState):
    """对最终结果做 PII 脱敏"""
    text = state.get("final_result", "")
    safe_text = desensitize(text)
    return {
        "final_result": safe_text,
        "messages": [AIMessage(content=safe_text)],
    }


def route_after_input_guard(state: RefundState):
    if state.get("final_result"):
        return "end"
    return "planner"

def route_after_policy(state: RefundState):
    if state.get("needs_approval"):
        return "approval"
    return "executor"

def build_refund_graph(checkpointer=None):
    graph = StateGraph(RefundState)

    graph.add_node("input_guard", input_guard_node)
    graph.add_node("planner", planner_node)
    graph.add_node("policy", policy_agent)
    graph.add_node("approval", approval_node)
    graph.add_node("load_order",load_order_node)
    graph.add_node("executor", executor_node)
    graph.add_node("output_guard", output_guard_node)

    graph.add_edge(START, "input_guard")
    graph.add_conditional_edges("input_guard", route_after_input_guard, {
        "planner": "planner",
        "end": END,
    })
    graph.add_edge("planner", "load_order")
    graph.add_conditional_edges("load_order", route_after_load_order, {
        "policy":"policy",
        "output_guard":"output_guard",
    })
    graph.add_conditional_edges("policy", route_after_policy,{
        "approval":"approval",
        "executor":"executor"
    })
    graph.add_edge("approval", "executor")
    graph.add_edge("executor", "output_guard")
    graph.add_edge("output_guard", END)

    return graph.compile(checkpointer=checkpointer)


def init_state(question: str) -> RefundState:
    return {
        "messages": [HumanMessage(content=question)],
        "refund_type": "",
        "amount": 0.0,
        "policy_result": "",
        "needs_approval": False,
        "approval": False,
        "final_result": "",
    }
