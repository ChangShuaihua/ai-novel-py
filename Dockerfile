FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[llm]"

EXPOSE 8765
CMD ["python", "-m", "ainovel.entry.headless", "web", "--host", "0.0.0.0", "--port", "8765"]
