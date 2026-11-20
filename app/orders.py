import psycopg
from psycopg.rows import dict_row

SEED_ORDERS = [
    ("A1001", "服饰", 20.0, "未发货"),   # 小额，应直接放行
    ("A1002", "电子", 3000.0, "已发货"), # 大额，必须审批
    ("A1003", "生鲜", 88.0, "已发货"),   # 生鲜，政策不同
    ("A1004", "电子", 800.0, "未发货"),  # 刚过阈值
    ("A1005", "服饰", 600.0, "已签收"),
    ("A1006", "服饰", 500.0, "未发货"),
    ("A1007", "服饰", 499.99, "未发货"),
]

_pool=None

def set_pool(pool):
    global _pool
    _pool=pool

async def init_orders():
    async with _pool.connection() as conn:
        await conn.execute("""
           CREATE TABLE IF NOT EXISTS orders(
           order_id TEXT PRIMARY KEY,
           category TEXT  NOT NULL,
           amount NUMERIC(10,2) NOT NULL,
           status TEXT NOT NULL
        )
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS refund_events(
         order_id TEXT PRIMARY KEY,
         thread_id TEXT NOT NULL,
         amount NUMERIC(10,2) NOT NULL,
         decision TEXT NOT NULL,
         created_at TIMESTAMPTZ DEFAULT now()
         )
        """)
        for oid,cat,amt,st in SEED_ORDERS:
            await conn.execute(
                "INSERT INTO orders(order_id,category,amount,status)"
                "VALUES(%s,%s,%s,%s) ON CONFLICT (order_id) DO NOTHING",
                (oid,cat,amt,st)
            )
        await conn.commit()

async def fetch_order(order_id:str)->dict|None:
    async with _pool.connection() as conn:
        cur=await conn.execute(
          "SELECT order_id,category,amount,status FROM orders WHERE order_id=%s",
            (order_id,),
        )
        row=await cur.fetchone()
        await conn.commit()
        return dict(row) if row else None

async def record_refund(order_id:str,thread_id:str,amount:float,decision:str)->bool:
    async with _pool.connection() as conn:
        cur=await conn.execute(
            "INSERT INTO refund_events(order_id,thread_id,amount,decision)"
            "VALUES(%s,%s,%s,%s) ON CONFLICT (order_id) DO NOTHING RETURNING order_id",
            (order_id,thread_id,amount,decision),
        )
        row=await cur.fetchone()
        await conn.commit()
        return row is not None


