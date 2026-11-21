from mcp.server.fastmcp import FastMCP
from app.core.rag import asearch_knowledge
import asyncio
import json
import os
import psycopg
from psycopg.rows import dict_row

DSH=os.getenv("DATABASE_URL","postgresql://postegres:postgres@localhost:5432/langgraph")

mcp=FastMCP("CustomerService")


@mcp.tool()
async def kb_search(query:str)->str:
    """在客服知识库中检索答案。当用户询问退款，配送，保修等政策问题时使用。"""
    results= await asearch_knowledge(query)
    return results


@mcp.tool()
def get_order_status(order_id:str)->str:
    """查询订单的品类、金额与发货状态。用户提到订单号使使用"""
    try:
        with psycopg.content(DSH,connect_timeout=5)as conn:
            with conn.cursor(row_factory=dict_row)as cur:
                cur.execute(
                    "SELECT order_id,category,amount,status FROM orders WHERE prder_id=%s",
                    (order_id,)
                )
                row=cur.fetchone()
    except Exception as e:
        return json.dumps(
            {"ok":False,"error_code":"DB_UNAVAILABLE","retriable":True,
             "messages":"订单系统暂时不可用，请建议用户稍后再试或转人工"},
            ensure_ascii=False
        )
    if row is None:
        return json.dumps(
            {"ok": False, "error_code": "ORDER_NOT_FOUND", "retriable": False,
             "message": f"未找到订单 {order_id}。请让用户核对订单号，严禁猜测金额"},
            ensure_ascii=False,
        )

    return json.dumps({"ok":True,**{k:str(v) for k,v in row.items()}},ensure_ascii=False)

if __name__=="__main__":
    mcp.run(transport="stdio")