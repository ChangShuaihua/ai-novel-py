FROM python:3.12-slim

WORKDIR /app

# 依赖层只受 pyproject.toml 影响。普通业务代码更新不再重新解析和下载 LiteLLM。
COPY pyproject.toml README.md ./
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --index-url "$PIP_INDEX_URL" \
    "pydantic>=2.6" \
    "pymysql>=1.1" \
    "redis>=5" \
    "litellm>=1.74" \
    "mcp>=2.2,<3"

COPY src ./src
RUN pip install --no-deps --no-build-isolation .
COPY docs/mysql-schema.sql ./docs/mysql-schema.sql

EXPOSE 8765
CMD ["python", "-m", "ainovel.entry.headless", "web", "--host", "0.0.0.0", "--port", "8765"]
