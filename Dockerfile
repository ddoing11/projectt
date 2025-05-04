FROM python:3.10-slim

# 시스템 패키지 설치 (mysqlclient와 기타 의존성 해결 포함)
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    git \
    curl \
    pkg-config \            
    libffi-dev \
    libssl-dev \
    default-libmysqlclient-dev \
    libgl1 \
    ffmpeg \
    python3-dev \
    && apt-get clean

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip \
 && pip install wheel setuptools \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["gunicorn", "backend.aptitude.wsgi:application", "--bind", "0.0.0.0:8000"]
