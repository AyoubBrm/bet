FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY server.py .
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini .

# Expose the FastAPI port
EXPOSE 8002

# Run FastAPI
CMD ["python", "server.py"]
