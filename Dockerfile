FROM python:3.14-slim

WORKDIR /app

# 加这两行：让 uv 走阿里云源，且强制只下载 CPU 版 Torch
ENV UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/
ENV UV_TORCH_BACKEND=cpu

RUN pip install uv

# 复制依赖清单
COPY pyproject.toml uv.lock ./

# 这次 sync 会秒过，只下轻量级的 CPU 包
RUN uv sync --frozen --no-dev --no-install-project

COPY app/ ./app/
COPY data/knowledge/ ./data/knowledge/

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]