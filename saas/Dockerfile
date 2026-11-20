FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY . /app/saas
ENV PYTHONUNBUFFERED=1 REGION=in REPLICA_ID=1 PORT=8000
RUN useradd --create-home appuser
USER appuser
EXPOSE 8000 8001
CMD ["sh", "-c", "uvicorn saas.main:app --host 0.0.0.0 --port $PORT"]
