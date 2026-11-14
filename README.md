# Agentic Workflow Desk

基于 LangGraph 的多 Agent 智能客服与退款审批系统。Supervisor 统一路由，客服与退款专员分工处理，高风险操作强制人工审批。

## 功能

- **Supervisor 路由**：统一入口 `/agent`，按意图分派给客服或退款专员
- **Agentic RAG**：查询改写 → 向量召回 → 重排序 → 反思，两阶段检索
- **HITL 审批**：退款触发 `interrupt`，UI 弹出审批卡，批准后 `Command(resume=...)` 恢复执行
- **SSE 流式**：`/agent/stream` 逐 token 推送，前端打字机效果
- **三层安全**：输入拦截（防注入）→ 执行控制（金额超标强制审批）→ 输出脱敏
- **持久化**：LangGraph checkpointer 存 PostgreSQL，审批挂起状态跨重启存活

## 技术栈

| 层 | 技术 |
|---|---|
| Agent 编排 | LangGraph |
| 后端 | FastAPI + Uvicorn |
| 前端 | Streamlit |
| 存储 | PostgreSQL（LangGraph checkpointer） |
| 部署 | Docker Compose |
| 依赖管理 | uv |

## 快速开始

### 前置条件

- Docker Desktop
- 本地已有模型缓存（`~/.cache/huggingface`），或容器内能访问 `hf-mirror.com`

### 启动

```bash
# 1. 配置环境变量
copy .env.example .env
# 编辑 .env，填入数据库密码

# 2. 启动所有服务
docker compose up -d --build

# 3. 确认三个容器都 Up
docker compose ps