# backend/Dockerfile
FROM python:3.10-slim

WORKDIR /app

# Using requirements.txt for this project as it's already set up
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application using Uvicorn with reload for development
# The backend code will be mounted as a volume in docker-compose, so reload will work.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
