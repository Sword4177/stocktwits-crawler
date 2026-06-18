FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt requirements-crawler.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-crawler.txt

COPY . .

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8001}"]
