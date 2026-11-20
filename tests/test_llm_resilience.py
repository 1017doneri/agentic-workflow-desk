import asyncio

import pytest

from app.llm import LLMUnavailable, ResilientLLM


class FlakyBase:
    """前 fail_times 次抛超时，之后成功。"""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    async def ainvoke(self, messages, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise asyncio.TimeoutError()
        return "ok"


async def test_retry_then_success():
    base = FlakyBase(fail_times=2)
    llm = ResilientLLM(base, timeout=1, max_attempts=3, deadline=5)
    assert await llm.ainvoke([]) == "ok"
    assert base.calls == 3          # 失败两次，第三次成功


async def test_retry_exhausted_raises():
    base = FlakyBase(fail_times=99)
    llm = ResilientLLM(base, timeout=1, max_attempts=2, deadline=5)
    with pytest.raises(LLMUnavailable):
        await llm.ainvoke([])
    assert base.calls == 2          # 不会无限重试