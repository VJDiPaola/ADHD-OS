FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY adhd_os/ adhd_os/
COPY README.md .

# Create sessions directory
RUN mkdir sessions

# Set environment variables (defaults, should be overridden)
ENV ADHD_OS_MODEL_MODE=production
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "-m", "adhd_os.main"]
