# Build from the repo root:  docker build -f collector/Dockerfile -t signal-collector .
FROM python:3.11-slim
WORKDIR /app
COPY collector/requirements.txt collector/requirements.txt
RUN pip install --no-cache-dir -r collector/requirements.txt
COPY collector collector
ENV DATA_DIR=/data
VOLUME /data
EXPOSE 8101
CMD ["uvicorn", "collector.main:app", "--host", "0.0.0.0", "--port", "8101"]
