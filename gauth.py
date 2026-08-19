# -*- coding: utf-8 -*-
"""Gmail 자격증명 공용 로더 + 중복 발송 판정.

로컬(PC)과 클라우드(GitHub Actions) 양쪽에서 동작한다.
- 클라우드: 환경변수 GMAIL_TOKEN_JSON(token.json 전문)로 메모리에서 구성. 파일·브라우저 불필요.
- 로컬: 기존 token.json 파일 사용(동작 변경 없음).
"""

import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.path.join(BASE, "token.json")

ENV_TOKEN = "GMAIL_TOKEN_JSON"


def is_cloud():
    return bool(os.environ.get(ENV_TOKEN))


def creds_from_env():
    """환경변수에 토큰이 있으면 그걸로 자격증명 생성. 없으면 None."""
    raw = os.environ.get(ENV_TOKEN)
    if not raw:
        return None
    info = json.loads(raw)
    # 스코프 인자 없이 로드 → 실제 승인된 스코프가 유지됨(send 누락 오판 방지)
    creds = Credentials.from_authorized_user_info(info)
    if not creds.valid:
        # refresh token은 장기 유효(OAuth 앱 프로덕션 게시). 액세스 토큰만 매 실행 갱신.
        creds.refresh(Request())
    return creds


def outdir():
    """산출물 저장 루트. 클라우드는 러너 임시 경로를 env로 받는다."""
    return os.environ.get("NEWSLETTER_OUT") or os.path.join(
        os.path.expanduser("~"), "Downloads", "IT뉴스레터"
    )


def already_sent(creds, date):
    """Gmail 보낸편지함으로 당일 발송 여부 판정.

    러너가 매번 새로 뜨는 클라우드에서는 .sent_* 파일 표식이 남지 않으므로,
    발송 이력 자체를 상태 저장소로 쓴다. 로컬에서도 동일하게 동작한다.
    """
    try:
        from googleapiclient.discovery import build

        gmail = build("gmail", "v1", credentials=creds)
        q = f'in:sent subject:"[국내 IT 트렌드] {date}" newer_than:2d'
        res = gmail.users().messages().list(userId="me", q=q).execute()
        return bool(res.get("messages"))
    except Exception as e:
        # 판정 실패 시 발송을 막지 않는다(미발송이 중복발송보다 나쁨).
        print("발송이력 조회 실패(무시):", e)
        return False
