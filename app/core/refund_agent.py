import json
import re
from typing import TypedDict, Annotated
from operator import add

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from app.llm import llm
from app.config import APPROVAL_THRESHOLD
from app.core.rag import search_knowledge
from app.safety.input_guard import is_safe_input
from app.safety.output_guard import desensitize
from app.safety.audit import audit_log


class RefundState(TypedDict):
    messages: Annotated[list, add]
    refund_type: str
    amount: float
    policy_result: str
    needs_approval: bool
    approval: bool
    final_result: str


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


async def planner_node(state: RefundState):
    """分析用户请求，判断退款类型和金额"""
    user_msg = state["messages"][-1].content

    prompt = f"""分析用户的退款请求，输出 json：
{{"refund_type": "未发货/已发货/生鲜/其他", "amount": 金额数字}}

用户：{user_msg}

只输出 json，不要解释。"""

    resp = await llm.ainvoke([HumanMessage(content=prompt)])
    try:
        data = json.loads(resp.content)
    except json.JSONDecodeError:
        data = {"refund_type": "其他", "amount": 0}

    print(f"[Planner] 类型={data.get('refund_type')}, 金额={data.get('amount')}")

    return {
        "refund_type": data.get("refund_type", "其他"),
        "amount": float(data.get("amount", 0)),
    }

async def policy_agent(state: RefundState):
    """查询改写 + 多查询检索 + 自我反思 + 二次检索"""

    original_query = f"{state['refund_type']}退款政策"

    rewrite_prompt = f"""把用户的退款问题改写成 2 个适合检索的查询，用 json 数组输出。

用户问题：{state['messages'][-1].content}
退款类型：{state['refund_type']}

输出示例：["未发货退款流程", "未发货退款到账时间"]

只输出 json 数组。"""

    resp = await llm.ainvoke([HumanMessage(content=rewrite_prompt)])
    try:
        queries = json.loads(resp.content)
        if isinstance(queries, dict):
            queries = queries.get("queries", [original_query])
        if not isinstance(queries, list):
            queries = [original_query]
    except json.JSONDecodeError:
        queries = [original_query]

    queries = [original_query] + queries[:2]
    print(f"[Policy] 改写后的查询：{queries}")

    # ---- 第 2 轮：多查询检索 ----
    all_contexts = []
    for q in queries:
        ctx = search_knowledge(q)
        if ctx:
            all_contexts.append(ctx)

    combined_context = "\n\n".join(all_contexts)
    print(f"[Policy] 检索到 {len(all_contexts)} 段上下文")

    # ---- 第 3 轮：自我反思 ----
    reflect_prompt = f"""根据以下检索到的政策，判断是否能回答用户的退款问题。

用户问题：{state['messages'][-1].content}
退款类型：{state['refund_type']}

检索到的政策：
{combined_context}

输出 json：
{{"sufficient": true/false, "reason": "简要说明"}}

如果政策里明确提到了用户的情况，sufficient 为 true。
如果政策里没有覆盖用户的情况，sufficient 必须为 false。不要轻易说 true。

只输出 json。"""

    resp = await llm.ainvoke([HumanMessage(content=reflect_prompt)])
    try:
        reflection = json.loads(resp.content)
    except json.JSONDecodeError:
        reflection = {"sufficient": True, "reason": "解析失败，默认足够"}

    print(f"[Policy] 反思：sufficient={reflection.get('sufficient')}, "
          f"reason={reflection.get('reason')}")


    if not reflection.get("sufficient", True):
        fallback_query = f"退款政策 {state['refund_type']}"
        extra_ctx = search_knowledge(fallback_query)
        if extra_ctx:
            combined_context += "\n\n" + extra_ctx
            print(f"[Policy] 二次检索补充：{fallback_query}")

    judge_prompt = f"""根据以下退款政策，判断用户的退款请求是否符合：

政策：
{combined_context}

退款类型：{state['refund_type']}
金额：{state['amount']} 元

输出 json：
{{"result": "符合/不符合/需要进一步确认", "reason": "简要说明"}}

只输出 json。"""

    resp = await llm.ainvoke([HumanMessage(content=judge_prompt)])
    try:
        data = json.loads(resp.content)
    except json.JSONDecodeError:
        data = {"result": "需要进一步确认", "reason": "政策解析失败"}

    needs_approval = (
        state["amount"] > APPROVAL_THRESHOLD
        or data.get("result") == "需要进一步确认"
    )

    print(f"[Policy] 结果={data.get('result')}, 需要审批={needs_approval}")

    return {
        "policy_result": data.get("reason", ""),
        "needs_approval": needs_approval,
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


async def executor_node(state: RefundState):
    """执行退款操作"""
    if state.get("needs_approval") and not state.get("approval"):
        result = "退款申请未通过审批，已拒绝。"
    elif state["policy_result"] and "不符合" in state["policy_result"]:
        result = f"退款申请不符合政策：{state['policy_result']}"
    else:
        result = f"退款 {state['amount']} 元已处理，预计 24 小时内到账。"

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
    graph.add_node("executor", executor_node)
    graph.add_node("output_guard", output_guard_node)

    graph.add_edge(START, "input_guard")
    graph.add_conditional_edges("input_guard", route_after_input_guard, {
        "planner": "planner",
        "end": END,
    })
    graph.add_edge("planner", "policy")
    graph.add_conditional_edges("policy", route_after_policy, {
        "approval": "approval",
        "executor": "executor",
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
