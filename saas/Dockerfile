# Build from the repo root:  docker build -f saas/Dockerfile -t signal-saas .
FROM python:3.11-slim
WORKDIR /app
COPY saas/requirements.txt saas/requirements.txt
RUN pip install --no-cache-dir -r saas/requirements.txt
COPY saas saas
COPY contracts contracts
ENV TENANTS_FILE=/app/saas/config/tenants.json CONTRACT_PATH=/app/contracts/payload.schema.json
EXPOSE 8000
CMD ["uvicorn", "saas.main:app", "--host", "0.0.0.0", "--port", "8000"]
