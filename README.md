#智能客服与退款审批Agent系统

一个支持退款审批的多Agent客服系统。基于langgraph编排、RAG知识库检索、
MCP工具调用，并内置三层安全护栏。包含完整的CI/CD流水线和单元测试

##核心特性

1.双Agent协作：'/chat'负责日常咨询,'/refund'负责多步退款审批

2.Agentic RAG:查询改写+向量检索+重排序，保障知识召回准确性

3.Human-in-the-loop:高风险退款（金额>500）自动触发'interrupt',暂停等待人工审批

4.三层纵深防御:(1)输入护栏：语义拦截prompt注入\
             (2)执行护栏：金额阈值强制人工审批\
             (3)输出护栏：确定性正则脱敏PII(手机号/身份证)

5.工程化：github actions自动跑pytest(Mock外部网络)，PostgreSQL checkpointer保持会话记忆

###快速开始

###1.环境要求
python 3.12-3.14

Docker

Deepseek API KEY

###2.启动数据库

'''bash
docker run -d --name postgres-agent \
  -e POSTGRES_PASSWORG=agent123 \
  -e POSTGRES_DB=agentdb \
  -p 5432:5432 \
  -v pgdata_agent:/var/lib/postgresql/data \
  postgres:16
