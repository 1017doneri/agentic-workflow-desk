import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from app.core.refund_agent import build_refund_graph,init_state

ORDER_SMALL = {"order_id": "A1001", "category": "服饰", "amount": 20.0, "status": "未发货"}
ORDER_BIG = {"order_id": "A1002", "category": "电子", "amount": 3000.0, "status": "已发货"}

PLANNER_SMALL = '{"order_id": "A1001", "reason": "不想要了"}'
PLANNER_BIG = '{"order_id": "A1002", "reason": "想退款"}'
NO_APPROVAL = '{"sufficient": true, "needs_approval": false, "reason": "符合政策"}'
NEED_APPROVAL = '{"sufficient": true, "needs_approval": true, "reason": "金额超过阈值"}'


def _graph():
    return build_refund_graph(checkpointer=MemorySaver())

def _cfg(thread:str):
    return {"configurable":{"thread_id":thread}}

async def test_small_refund_auto_approved(fake_llm,fake_orders):
    fake_llm(**{"退款意图解析器": PLANNER_SMALL, "退款政策审核员": NO_APPROVAL})
    fake_orders({"A1001": ORDER_SMALL})

    result=await _graph().ainvoke(init_state("訂單A1001退款"),_cfg("t_small"))

    assert "__interrupt__" not in result
    assert "已经处理" in result["final_result"]
    assert "20.0" in result["final_result"]

async def test_large_refund_interrupts(fake_llm,fake_orders):
    fake_llm(**{"退款意图解析器": PLANNER_BIG, "退款政策审核员": NEED_APPROVAL})
    fake_orders({"A1002": ORDER_BIG})

    result=await _graph().ainvoke(init_state("订单 A1002 退款"), _cfg("t_big"))

    assert "__interrupt__"  in result

async def test_approved_then_executed(fake_llm,fake_orders):
    fake_llm(**{"退款意图解析器": PLANNER_BIG, "退款政策审核员": NEED_APPROVAL})
    fake_orders({"A1002": ORDER_BIG})

    app,cfg=_graph(),_cfg("t_approve")
    first=await app.ainvoke(init_state("订单 A1002 退款"), cfg)
    assert "__interrupt__" in first

    second=await app.ainvoke(Command(resume="y"),cfg)
    assert "已经处理" in second["final_result"]

async def test_rejected(fake_llm,fake_orders):
    fake_llm(**{"退款意图解析器": PLANNER_BIG, "退款政策审核员": NEED_APPROVAL})
    fake_orders({"A1002": ORDER_BIG})

    app, cfg = _graph(), _cfg("t_reject")
    await app.ainvoke(init_state("订单 A1002 退款"), cfg)

    second = await app.ainvoke(Command(resume="n"), cfg)
    assert "未通过审批" in second["final_result"]

async def test_lying_about_amount_still_needs_approval(fake_llm,fake_orders):
    fake_llm(**{
        "退款意图解析器": PLANNER_BIG,
        "退款政策审核员": NO_APPROVAL,  # ← 模型被"我记成 20 块"骗了
    })
    fake_orders({"A1002": ORDER_BIG})

    result=await _graph().ainvoke(init_state("訂單A1002,我記成20元"),_cfg("t_lying"))
    assert "__interrupt__" in result

async def test_unknown_order_goes_to_human(fake_llm,fake_orders):
    fake_llm(**{"退款意图解析器": '{"order_id": "A9999", "reason": "退款"}'})
    fake_orders({})
    result=await _graph().ainvoke(init_state("訂單A9999退款"),_cfg("t_unknown"))
    assert "__interrupt__" not in result
    assert "人工" in result["final_result"]
    assert "已處理"  not in result["final_result"]


