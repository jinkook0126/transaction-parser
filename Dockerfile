# 1. 가볍고 안정적인 파이썬 3.11 슬림 이미지를 사용합니다.
FROM python:3.11-slim

# 2. 컨테이너 내 작업 디렉토리 설정
WORKDIR /app

# 3. 필요한 시스템 의존성 설치 (pdfplumber 등의 원활한 동작을 위해 빌드 도구 최소 설치)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 4. 의존성 파일 복사 및 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 소스 코드 전체 복사 (main.py, parser.py, transformer.py)
COPY . .

# 6. Cloud Run은 기본적으로 8080 포트를 요구합니다.
ENV PORT=8080
EXPOSE 8080

# 7. FastAPI 구동 (Cloud Run 스펙에 맞게 호스트와 포트 바인딩)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]