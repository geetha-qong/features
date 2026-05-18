FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y gcc libgl1 libglib2.0-0 libxcb1 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-webapp.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-webapp.txt

COPY . .
RUN mkdir -p uploads job_outputs

EXPOSE 8000
CMD ["uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "8000"]
