FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HOME=/app
WORKDIR /app
COPY pyproject.toml LICENSE requirements.lock ./
RUN pip install --require-hashes -r requirements.lock
COPY src ./src
RUN pip install --no-deps . && mkdir -p /app/demo_workspace /app/.agent \
    && chown -R 10001:10001 /app
USER 10001:10001
RUN agent init-demo --workspace demo_workspace
ENTRYPOINT ["agent"]
CMD ["run", "查找 RAG 笔记并生成 study_plan.md", "--workspace", "demo_workspace", "--approve-writes"]
