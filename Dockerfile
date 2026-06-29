FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY glyphhold_client ./glyphhold_client
RUN pip install --no-cache-dir .

EXPOSE 5995

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5995"]
