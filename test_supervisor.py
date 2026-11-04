import asyncio
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from langchain_core.messages import HumanMessage
from app.core.supervisor_agent import build_supervisor_graph
from app.core.customer_agent import setup_tools

setup_tools([])

async def main():
    # 测试用 MemorySaver
    app = build_supervisor_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "test_super"}}

    print("=== 测试 1：闲聊（主管 -> 客服） ===")
    result = await app.ainvoke({
        "messages": [HumanMessage(content="你好，退款怎么弄？")],
        "next": ""
    }, config)
    if "__interrupt__" in result:
        print("⚠️ 主管误判，触发了退款中断！当前金额为 0，我们模拟拒绝")
        result = await app.ainvoke(Command(resume="n"), config)

        # 统一从最后一条消息获取结果
    if "worker_result" in result:
        print("最终结果:", result["worker_result"])
    else:
        print("最终结果(兜底):", result["messages"][-1].content)

    print("\n=== 测试 2：大额退款（主管 -> 退款 -> 触发中断） ===")
    # 注意：换一个 thread_id 保证记忆隔离
    config2 = {"configurable": {"thread_id": "test_super_refund"}}
    result = await app.ainvoke({
        "messages": [HumanMessage(content="我买的手机3000元，想退款")],
        "next": ""
    }, config2)

    if "__interrupt__" in result:
        print("✅ 成功拦截，等待审批！")
        info = result["__interrupt__"][0].value
        print("审批问题:", info["question"])

        print("\n=== 模拟人工批准 ===")
        # 👇 关键测试：Command 是否能穿透大图唤醒子图
        result = await app.ainvoke(Command(resume="y"), config2)
        print("批准后最终结果:", result["worker_result"])
    else:
        print("❌ 没有触发审批，当前结果:", result)


if __name__ == "__main__":
    asyncio.run(main())