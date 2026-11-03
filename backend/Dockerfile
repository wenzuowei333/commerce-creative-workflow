FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/workspace:/workspace/backend
WORKDIR /workspace/backend
COPY backend/pyproject.toml backend/requirements.lock ./
COPY backend/app/__init__.py ./app/__init__.py
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/ ./
COPY demo/ /workspace/demo/
RUN mkdir -p /workspace/runtime/media
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
