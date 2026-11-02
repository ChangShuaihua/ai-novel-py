FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" ".[llm]"
COPY docs/mysql-schema.sql ./docs/mysql-schema.sql

EXPOSE 8765
CMD ["python", "-m", "ainovel.entry.headless", "web", "--host", "0.0.0.0", "--port", "8765"]
