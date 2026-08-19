# Cloud Run Job 컨테이너 — 기존 파이프라인(oneshot.py) 그대로 실행.
# python + node + claude CLI(요약용). 리전 asia-northeast3(서울)로 배포해 KAIT 다운로드 IP를 국내로.
FROM python:3.11-slim

# node(claude CLI 구동용) 설치
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# claude CLI(헤드리스 요약, CLAUDE_CODE_OAUTH_TOKEN으로 인증)
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# 산출물은 컨테이너 임시경로, 타임존 서울(oneshot의 오늘날짜 판정에 필요)
ENV NEWSLETTER_OUT=/tmp/out \
    TZ=Asia/Seoul \
    PYTHONUTF8=1 \
    NEWSLETTER_NONINTERACTIVE=1

# Cloud Run Job은 이 명령을 1회 실행하고 종료. 무인 모드(인자 없음).
CMD ["python", "oneshot.py"]
