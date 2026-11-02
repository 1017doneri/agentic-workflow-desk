import json
from datetime import datetime

AUDIT_PATH = "audit.jsonl"


def audit_log(
    thread_id: str,
    node: str,
    user_input: str = "",
    refund_type: str = "",
    amount: float = 0,
    policy_result: str = "",
    needs_approval: bool = False,
    approval: bool | None = None,
    final_result: str = "",
):
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "thread_id": thread_id,
        "node": node,
        "user_input": user_input[:200],
        "refund_type": refund_type,
        "amount": amount,
        "policy_result": policy_result[:200],
        "needs_approval": needs_approval,
        "approval": approval,
        "final_result": final_result[:200],
    }
    with open(AUDIT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")