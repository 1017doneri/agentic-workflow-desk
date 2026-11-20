from functools import lru_cache
import asyncio
import logging
import random
import time
import openai
from langchain_openai import ChatOpenAI
import os


from app.config import (
LLM_API_KEY,
LLM_DEADLINE,
LLM_MAX_ATTEMPTS,
LLM_TIMEOUT,
LLM_URL,
MODEL_NAME
)

logger=logging.getLogger(__name__)

class LLMUnavailable(RuntimeError):
    """重试耗尽或熔断：调用方必须降级，不得继续依赖模型输出。"""
#RETRIABLE=(
#       openai.APIConnectionError,
#        openai.APITimeoutError,
#        openai.RateLimitError,
#        openai.InternalServerError,
#)

FATAL=(
    openai.AuthenticationError,
    openai.BadRequestError,
    openai.PermissionDeniedError,
    openai.NotFoundError,
    TypeError,
    ValueError,
    KeyError,
    AttributeError,
    NotImplementedError,
)

_breaker={"failures":0,"open_until":0.0}
_BREAKER_THRESHOLD=5
_BREAKER_COOLDOWN=30.0


class ResilientLLM:
    def __init__(self,base,timeout=LLM_TIMEOUT,max_attempts=LLM_MAX_ATTEMPTS,deadline=LLM_DEADLINE):
        self._base=base
        self._timeout=timeout
        self._max_attempts=max_attempts
        self._deadline=deadline

    async def ainvoke(self,messages,**kwargs):
        if time.monotonic()<_breaker["open_until"]:
            raise LLMUnavailable("熔断中：近期失败过多，直接降级")
        deadline_at=time.monotonic()+self._deadline
        last=None
        for attempt in range(1,self._max_attempts+1):
            remaining=deadline_at-time.monotonic()
            if remaining<=0:
                break
            try:
                resp=await asyncio.wait_for(
                    self._base.ainvoke(messages,**kwargs),
                    timeout=min(self._timeout,remaining)
                )
                _breaker["failures"]=0
                return resp

            except FATAL:
                raise
            except Exception as e:
                last=e
                _breaker["failures"]+=1
                if _breaker["failures"]>=_BREAKER_THRESHOLD:
                    _breaker["open_until"]=time.monotonic()+_BREAKER_COOLDOEN
                    logger.error("llm.breaker.open cooldoen=%.0fs",_BREAKER_COOLDOWN)
                if attempt>=self._max_attempts:
                    break
                delay=min(2**(attempt-1)+random.uniform(0,0.4),max(remaining,0))
                logger.warning(
                        "llm.retry attempt%d/%d delay=%.2fs err=%s",
                        attempt,self._max_attempts,delay,type(e).__name__
                )
                await asyncio.sleep(delay)
        raise LLMUnavailable(
                f"重试{self._max_attempts}次仍失败({type(last).__name__ if last else 'deadline'})"
        ) from last

    def bind_tools(self,tools):
        return ResilientLLM(
            self._base.bind_tools(tools),self._timeout,self._max_attempts,self._deadline
        )

@lru_cache(maxsize=1)
def  get_llm():
    base=ChatOpenAI(
        model=MODEL_NAME,
        api_key=LLM_API_KEY,
        base_url=LLM_URL,
        temperature=0,
        timeout=LLM_TIMEOUT,
        max_retries=0
    )
    return ResilientLLM(base)

import functools

from langchain_core.messages import AIMessage


def degrade_on_llm_failure(fn):
    """模型不可用时统一降级为转人工，绝不放行。"""

    @functools.wraps(fn)
    async def wrapper(state, *args, **kwargs):
        try:
            return await fn(state, *args, **kwargs)
        except LLMUnavailable as exc:
            print(f"[{fn.__name__}] 模型不可用，转人工：{exc}")
            msg = "系统繁忙，已转人工核实，请稍后再试。"
            return {
                "final_result": msg,
                "refund_status": "degraded",
                "messages": [AIMessage(content=msg)],
            }

    return wrapper

