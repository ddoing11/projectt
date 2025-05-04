FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    curl \
    libffi-dev \
    libssl-dev \
    default-libmysqlclient-dev \
    python3-dev \
    git \
    ffmpeg \
    && apt-get clean

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip \
 && pip install wheel \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["gunicorn", "backend.aptitude.wsgi:application", "--bind", "0.0.0.0:8000"]
