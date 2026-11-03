FROM node:24-alpine@sha256:8a32c8cf649a49915a66e81e7a609223c708d0adabf288ee3f4077d765542f85 AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/workspace:/workspace/backend
WORKDIR /workspace/backend
COPY backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
RUN useradd --create-home app && mkdir -p /workspace/runtime/media && chown -R app:app /workspace
COPY --chown=app:app backend/ ./
COPY --chown=app:app demo/ /workspace/demo/
COPY --from=web --chown=app:app /web/dist/ /workspace/frontend/dist/
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
