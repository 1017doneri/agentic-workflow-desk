from mcp.server.fastmcp import FastMCP
from app.core.rag import search_knowledge

mcp=FastMCP("CustomerService")


@mcp.tool()
def kb_search(query:str)->str:
    """在客服知识库中检索答案。当用户询问退款，配送，保修等政策问题时使用。"""
    results=search_knowledge(query)
    return results

@mcp.tool()
def get_order_status(order_id:str)->str:
    fake_orders={
        "12345":"订单12345：已发货，预计10月8日送达",
        "67890":"订单67890：未发货，预计24小时内送出"
    }
    return fake_orders[order_id]

if __name__=="__main__":
    mcp.run(transport="stdio")