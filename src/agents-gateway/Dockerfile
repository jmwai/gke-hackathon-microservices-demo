FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
PYTHONUNBUFFERED=1

WORKDIR /agents-gateway

RUN apt-get update && apt-get install -y build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt /agents-gateway/requirements.txt

RUN pip install --upgrade pip

RUN pip install --no-cache-dir -r /agents-gateway/requirements.txt


RUN python -c "import google.adk"

COPY . /agents-gateway

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]