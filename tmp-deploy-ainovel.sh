#!/bin/bash
set -euo pipefail
if [ ! -d /opt/ainovel/.git ]; then
  git clone https://github.com/ChangShuaihua/ai-novel-py.git /opt/ainovel
fi
install -m 644 /tmp/docker-compose.server.yml /opt/ainovel/docker-compose.server.yml
cd /opt/ainovel
docker compose -p ainovel -f docker-compose.yml -f docker-compose.server.yml up -d --build
docker compose -p ainovel -f docker-compose.yml -f docker-compose.server.yml ps
