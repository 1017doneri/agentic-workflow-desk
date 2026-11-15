import jwt
import pytest
from datetime import datetime,timedelta,timezone
from fastapi import HTTPException

from app.api import create_access_token,get_current_user,SECRET_KEY,ALGORITHM


async def test_token_roundtrip():
    token=create_access_token("alice")
    user=await get_current_user(token)
    assert user=="alice"

async def test_expired_token_rejected():
    expired=jwt.encode(
        {"sub":"alice","exp":datetime.now(timezone.utc)-timedelta(minutes=1)},
        SECRET_KEY,
        algorithm=ALGORITHM
    )
    with pytest.raises(HTTPException) as exc:
        await get_current_user(expired)
    assert exc.value.status_code==401


async def test_invalid_signature_rejected():
    forged=jwt.encode(
        {"sub":"alice","exp":datetime.now(timezone.utc)-timedelta(hours=1)},
        "wrong-secret-key",
        algorithm=ALGORITHM
    )
    with pytest.raises(HTTPException)as exc:
        await get_current_user(forged)
    assert exc.value.status_code==401


async def test_token_without_sub_rejected():
    no_sub=jwt.encode(
        {"exp":datetime.now(timezone.utc)-timedelta(hours=1)},
        SECRET_KEY,
        algorithm=ALGORITHM
    )
    with pytest.raises(HTTPException) as exc:
        await get_current_user(no_sub)
    assert exc.value.status_code==401

