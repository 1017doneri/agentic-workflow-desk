async def test_register_then_login(client,unique_user):
    r=await client.post("/auth/register",json={
        "username":unique_user,
        "password":"pass123"
    })
    assert r.status_code==200,r.text
    assert r.json()["user_id"]==unique_user

    r=await client.post("/auth/login",data={
        "username":unique_user,
        "password":"pass123"
    })
    assert r.status_code==200,r.text
    body=r.json()
    assert "access_token" in body
    assert body["user_id"]==unique_user

async def test_duplicate_register_returns_400(client,unique_user):
    await client.post("/auth/register",json={
        "username":unique_user,
        "password":"x"
    })
    r=await client.post("/auth/register",json={
        "username":unique_user,
        "password":"y"
    })
    assert r.status_code==400

async def test_wrong_password_returns_401(client,unique_user):
    await client.post("/auth/register",json={
        "username":unique_user,
        "password":"1"
    })
    r=await client.post("/auth/login",data={
        "username":unique_user,
        "password":"2"
    })
    assert r.status_code==401

async def test_login_unknown_user_returns_401(client,unique_user):
    r=await client.post("/auth/login",data={
        "username":"alice",
        "password":"3"
    })
    assert r.status_code==401
