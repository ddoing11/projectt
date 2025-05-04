# Dockerfile
FROM python:3.10-slim

# 시스템 패키지 설치 (필요한 빌드 도구 포함)
RUN apt-get update && apt-get install -y build-essential gcc libffi-dev libssl-dev default-libmysqlclient-dev


# 작업 디렉토리 설정
WORKDIR /app

# 의존성 먼저 복사 (캐싱)
COPY requirements.txt .

# Python 패키지 설치
RUN pip install --upgrade pip && pip install -r requirements.txt

# 나머지 프로젝트 파일 복사
COPY . .

# 포트 설정
EXPOSE 8000

# 실행 명령
CMD ["gunicorn", "backend.aptitude.wsgi:application", "--bind", "0.0.0.0:8000"]
