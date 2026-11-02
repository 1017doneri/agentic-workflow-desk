import requests

r = requests.post(
    "http://127.0.0.1:8000/chat",
    json={"question": "退款怎么弄", "user_id": "test"},
)
print("状态码:", r.status_code)
print("返回:", r.json())