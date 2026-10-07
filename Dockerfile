FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY scraper ./scraper

RUN useradd --create-home app \
    && mkdir -p /app/data /app/state \
    && chown -R app:app /app

USER app

ENTRYPOINT ["python"]
CMD ["main.py"]
