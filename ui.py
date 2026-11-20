import streamlit as st
import httpx
import  json
import os
import uuid

API_BASE=os.getenv("API_BASE","http://127.0.0.1:8000")


def call_agent(prompt:str,thread_id:str)->str:
    resp=httpx.post(
        f"{API_BASE}/agent",
        json={"question":prompt,"user_id":thread_id},
        timeout=120
    )
    if resp.status_code!=200:
        st.error(f"后端返回{resp.status_code}:{resp.text}")
        st.stop()
    data=resp.json()
    return data

def stream_agent(prompt:str,thread_id:str)->str:
    headers = {"Authorization": f"Bearer {st.session_state.token}"}
    with httpx.stream(
        "POST",
        f"{API_BASE}/agent/stream",
        json={"question":prompt,"conversation_id":st.session_state.conversation_id},
        headers=headers,
        timeout=None
    )as response:
        if response.status_code!=200:
            response.read()
            st.error(f"详情：{response.text}")
            return
        response.raise_for_status()
        current_event=None
        for line in response.iter_lines():
            if line.startswith("event:"):
                current_event=line.split(":",1)[1].strip()
                continue
            if line.startswith("data:"):
                raw=line.split(":",1)[1].strip()
                try:
                    payload=json.loads(raw)
                except json.JSONDecodeError as e:
                    print(f"PARSE FAIL:{e}")
                    continue
                if current_event == "meta":
                    cid = payload.get("conversation_id")
                    if cid:
                        st.session_state.conversation_id = cid
                elif current_event=="token":
                       yield payload.get("text","")
                elif current_event=="interrupt":
                    st.session_state.pending_interrupt={
                        **payload,
                        "conversation_id":payload.get(
                        "conversation_id",st.session_state.conversation_id
                    ),
                    }
                elif current_event=="done":
                    answer=payload.get("answer","")
                    if answer:
                        yield answer
                    return
                elif current_event=="error":
                    st.error(f"流式出错：{payload.get('message','')}")
                    return


def resume_agent(user_id:str,decision:str):
    headers = {"Authorization": f"Bearer {st.session_state.token}"}
    conv=(st.session_state.get("pending_interrupt" or {}).get("conversation_id") or st.session_state.conversation_id)
    resp=httpx.post(
        f"{API_BASE}/agent/approval",
        json={"decision":decision,"conversation_id":conv},
        headers=headers,
        timeout=120
    )
    if resp.status_code==409:
        st.warning("这笔退款已经处理过了（或会话已失效）")
        st.session_state.pending_interrupt=None
        for msg in st.session_state.messages:
            if msg.get("needs_approval"):
                msg["needs_approval"]=False
        st.rerun()
        return
    if resp.status_code!=200:
        st.error(f"审批失败：{resp.text}")
        return
    data=resp.json()
    for msg in st.session_state.messages:
         if msg.get("needs_approval"):
             msg["needs_approval"]=False

    answer=data.get("answer","")
    if answer:
        st.session_state.messages.append({
            "role": "assistant",
            "content": data["answer"],
            "needs_approval": "[需要审批]" in answer
        })
    if decision == "y":
        tip = "✅ 退款已批准，预计 24 小时内原路到账。如超时未到账或有疑问，请联系商家。"
    else:
        tip = "❌ 退款申请未通过。如有疑问，请联系商家。"

    st.session_state.messages.append({
        "role": "assistant",
        "content": tip,
        "needs_approval": False,
    })
    st.rerun()



st.set_page_config(page_title="Agent Workflow Desk",page_icon="🤖")
st.title("Agent Workflow Desk")

if"token" not in st.session_state:
    st.session_state.token=None
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id=uuid.uuid4().hex[:12]
if"user_id" not in st.session_state:
    st.session_state.user_id=None

def login_page():
    mode=st.radio("模式",["登录","注册"],horizontal=True)
    with st.form("auth_form"):
        username=st.text_input("用户名")
        password=st.text_input("密码",type="password")
        submitted=st.form_submit_button("提交")

    if submitted:
        if not username or not password:
            st.error("用户名和密码不能为空")
            return
        if mode=="登录":
            resp=httpx.post(
                f"{API_BASE}/auth/login",
                data={"username":username,"password":password},
            )
            if resp.status_code == 200:
                data = resp.json()
                st.session_state.token = data["access_token"]
                st.session_state.user_id = data["user_id"]
                st.rerun()
            else:
                st.error(resp.text)
        else:
            resp=httpx.post(
                f"{API_BASE}/auth/register",
                json={"username":username,"password":password}
            )
            if resp.status_code==200:
                st.success("注册成功，请切换到[登录]")
            else:
                st.error(f"注册失败:{resp.text}")


if not st.session_state.token:
    login_page()
    st.stop()

with st.sidebar:
    st.caption(f"当前用户:{st.session_state.user_id}")
    st.caption(f"会话：{st.session_state.conversation_id}")
    if st.button("新建会话"):
        st.session_state.messages = []
        st.session_state.pending_interrupt = None
        st.session_state.conversation_id = uuid.uuid4().hex[:12]
        st.rerun()
    if st.button("退出登录"):
        st.session_state.clear()
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages=[]


for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if not msg["content"]==None:
          st.markdown(msg["content"])
        if msg.get("needs_approval"):
            st.warning("这笔退款需要人工审批")
            col1,col2=st.columns(2)
            if col1.button("批准",key=f"approve_{id(msg)}"):
                resume_agent(st.session_state.user_id,"y")
            if col2.button("不批准",key=f"reject_{id(msg)}"):
                resume_agent(st.session_state.user_id,"n")


if prompt:=st.chat_input("输入你的问题："):
    st.session_state.messages.append({"role":"user","content":prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        full_text=st.write_stream(stream_agent(prompt,st.session_state.user_id))
    needs_approval=(
            st.session_state.get("pending_interrupt") is not None
            or "[需要审批]" in full_text
    )
    st.session_state.messages.append({
        "role":"assistant",
        "content":full_text,
        "needs_approval":needs_approval
    })
    st.session_state.pending_interrupt=None
    if needs_approval:
        st.rerun()