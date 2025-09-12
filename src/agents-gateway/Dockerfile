FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY src/agents-gateway/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src/agents-gateway /app

EXPOSE 8085

CMD ["uvicorn", "src.agents-gateway.app.server:app", "--host", "0.0.0.0", "--port", "8085"]


