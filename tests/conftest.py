import sys
from unittest.mock import MagicMock

# 👇 核心：在 pytest 导入任何业务代码之前，直接伪造 app.core.rag 模块
mock_rag = MagicMock()
mock_rag.search_knowledge.return_value = "[refund.txt] 模拟知识库：未发货可直接退款。"
sys.modules["app.core.rag"] = mock_rag