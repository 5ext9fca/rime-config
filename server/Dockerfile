FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt \
    && mkdir /data && chown 10001:10001 /data
COPY client/ /app/client/
COPY server/app.py server/gunicorn.conf.py /app/server/
USER 10001:10001

FROM base AS test
COPY tests/ /app/tests/
COPY sync-manifest.json third-party.json remote.json paths.json native-sync.json /app/
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]

FROM base AS runtime
ENV RIME_SETTINGS=/config/settings.json
EXPOSE 8080
CMD ["gunicorn", "--chdir", "/app/server", "--config", "/app/server/gunicorn.conf.py", "app:create_app()"]
