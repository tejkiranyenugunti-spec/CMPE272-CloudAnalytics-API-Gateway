# Use a stable, small Python base
FROM python:3.13-slim

# Create workdir
WORKDIR /app

# (Optional) basic build deps, then clean
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

# Install deps first (better layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the whole project
COPY . .

# Expose the port your app and K8s Service use
EXPOSE 8000

# Start FastAPI (module path is app.main:app; bind to 0.0.0.0:8000)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
