FROM python:3.8-slim

# Prevent Python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency list
COPY requirements-prod.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-prod.txt

# Copy project files
COPY . .

# Expose port (Render uses $PORT internally)
EXPOSE 8000

# Start the app
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]
