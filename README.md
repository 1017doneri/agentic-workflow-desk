# [这里填入你选的名字，比如 Aegis-Agent]

一个基于 **LangGraph 多 Agent 协作** 的企业级智能客服与退款审批系统。采用 **Supervisor 架构**，内置 Agentic RAG 知识库检索、MCP 工具动态发现、以及**三层安全纵深防御**。包含完整的 CI/CD 流水线与依赖隔离测试。

[![CI/CD](https://github.com/1017doneri/customer_with_refund_agent/actions/workflows/ci.yml/badge.svg)](https://github.com/1017doneri/customer_with_refund_agent/actions/workflows/ci.yml)

## ✨ 核心特性

- **Supervisor 多 Agent 路由**：用户无需区分接口，主管（Supervisor）Agent 根据语义自动将请求分派给“客服专员”或“退款专员”。
- **跨子图中断穿透**：在嵌套多 Agent 架构下，退款子图触发 `interrupt` 人工审批时，挂起信号能正确穿透回主图，并通过 `Command(resume)` 完美恢复执行。
- **Agentic RAG 检索**：查询改写 → 向量召回 → BGE-Reranker 重排序 → 自我反思，保障复杂提问的召回率（RAGAS 评估 Faithfulness 0.92）。
- **三层安全纵深防御**：
  1. 输入拦截：语义分类拦截 Prompt 注入。
  2. 执行控制：金额超标强制人工审批，杜绝 Prompt 绕过。
  3. 输出脱敏：确定性正则剥离手机号、身份证等 PII。
- **完全隔离的 CI/CD**：基于 GitHub Actions，通过 `Mock` 拦截外部大模型 API 和 HuggingFace 模型下载，实现 **30 秒极速且零成本** 的单元测试。测试通过后自动构建 Docker 镜像并推送至 `ghcr.io`。

## 🏗️ 架构设计

```text
用户请求 (统一入口 /agent)
   ↓
【Supervisor Agent】意图识别与任务分派
   ├── customer 意图 → 【客服专员子图】(Agentic RAG + MCP工具)
   └── refund 意图   → 【退款专员子图】(Planner→Policy→Approval→Executor)
          ↓
      (高风险触发挂起) → 返回 needs_approval 信号
          ↓
    调用 /agent/approve (resume="y")
          ↓
      (穿透主图恢复) → 返回最终结果
   ↓
【基础支撑】
  ├── MCP Server（独立进程，自动发现工具）
  ├── ChromaDB（向量库）
  ├── PostgreSQL（LangGraph Checkpointer 状态记忆）
  └── LangFuse（全链路可观测性）
```

## 🚀 快速开始

### 环境要求
- Python 3.14+
- Docker & Docker Compose
- DeepSeek API Key（或任何兼容 OpenAI 的 API）

### 1. 启动基础设施
```bash
# 启动 PostgreSQL
docker run -d --name postgres-agent \
  -e POSTGRES_PASSWORD=agent123 \
  -e POSTGRES_DB=agentdb \
  -p 5432:5432 \
  -v pgdata_agent:/var/lib/postgresql/data \
  postgres:16
```

### 2. 配置与运行
```bash
# 安装依赖
uv sync

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY 等真实信息

# 启动应用
uv run uvicorn app.api:app --reload
```
接口文档请访问：`http://127.0.0.1:8000/docs`

## 🧪 测试与评估

### 自动化测试（CI 环境）
```bash
uv run pytest tests/ -v
```
- **隔离策略**：测试用例中通过 `conftest.py` 和 `@patch` 拦截了所有的网络请求与模型加载。无需真实 API Key，无需下载任何模型，毫秒级完成。
- **覆盖范围**：PII 脱敏、Prompt 注入拦截、小额直退、大额中断恢复、人工拒绝分支。

### RAGAS 评估结果
在 20 题人工测试集上：
- **Faithfulness**: 0.92
- **Answer Relevancy**: 0.84
- **Context Recall**: 1.00

## 🧠 关键技术决策

### 1. 为什么从“单 Agent”升级为“Supervisor 多 Agent”？
单 Agent 在面临“退款、咨询、查单”混合意图时，Prompt 会极度膨胀且容易出错。采用 Supervisor 模式后，主管只负责分发，专员只负责本领域业务，实现了**职责隔离**和**上下文减负**。

### 2. 为什么用 `interrupt` 而不是让 Prompt 自己判断？
输入护栏（LLM 语义判断）存在被对抗性输入（多语言、编码变体）绕过的风险。涉及资金变动的退款操作，其最后一道防线**绝不能是概率性的**，必须是代码逻辑 + 人类 `y/n` 决策的双重把控。

### 3. 为什么 CI 里要彻底 Mock 外部依赖？
如果不 Mock，CI 每次运行都需要下载数 GB 的模型并调用真实的 LLM API。这会导致 CI 耗时数十分钟、极易因网络波动产生“假阳性”失败，且每次提交都在烧真实的 Token。Mock 让测试回归了本质：**验证代码逻辑，而非验证网络连通性**。

## 📁 项目结构
```text
.
├── app/
│   ├── api.py                  # FastAPI 统一入口
│   ├── core/
│   │   ├── supervisor_agent.py # 主管 Agent 与大图编排
│   │   ├── customer_agent.py   # 客服专员子图
│   │   ├── refund_agent.py     # 退款专员子图
│   │   └── rag.py              # 两阶段 Agentic RAG
│   ├── safety/                 # 三层安全护栏
│   └── mcp/                    # MCP 工具 Server
├── tests/                      # 隔离外部网络的单元测试
├── .github/workflows/ci.yml    # CI/CD 流水线
├── Dockerfile                  # 多阶段构建，剥离 GPU 依赖
└── pyproject.toml
```

## 🛣️ Roadmap
- [ ] 引入 Context-Aware RAG（在查询改写阶段引入历史对话，解决“这个怎么弄”的代词指代问题）
- [ ] 接入人工审批的 Webhook 通知（例如审批通过后飞书/钉钉提醒）
- [ ] 支持基于 Redis 的高并发会话限流