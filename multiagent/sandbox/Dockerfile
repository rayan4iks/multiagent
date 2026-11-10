FROM python:3.12-slim

# непривилегированный пользователь без shell и домашней папки
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY runner.py /app/runner.py

USER 10001
WORKDIR /app
# -I: изолированный режим Python (без PYTHONPATH и пользовательских site-packages)
ENTRYPOINT ["python", "-I", "/app/runner.py"]
