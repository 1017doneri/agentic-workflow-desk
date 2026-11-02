import requests

BASE = "http://127.0.0.1:8000"

# 测试 1：小额
r = requests.post(f"{BASE}/refund", json={
    "question": "我买的衣服 200 块，还没发货，想退款",
    "user_id": "alice",
})
print("小额:", r.json())

# 测试 2：大额（走审批）
r = requests.post(f"{BASE}/refund", json={
    "question": "我买的手机 3000 块，已发货，想退款",
    "user_id": "bob",
})
print("大额:", r.json())

# 审批
if r.json().get("needs_approval"):
    r = requests.post(f"{BASE}/refund/approve", json={
        "user_id": "bob",
        "decision": "y",
    })
    print("审批后:", r.json())