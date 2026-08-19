"""오늘자 뉴스레터 + IT 인사이트 분석을 메일로 발송.

gmail.send 스코프 필요 → 최초 1회 브라우저 재동의(token.json에 send 추가).
사용: python send_mail.py <본문.md> [--to EMAIL] [--greeting "인사말"]
  --to      수신자 지정(미지정 시 환경변수 RECIPIENTS)
  --greeting 본문 맨 위에 넣을 인사말 한 줄(외부 수신자용)
"""

import argparse
import base64
import os
from email.mime.text import MIMEText

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import gauth

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
BASE = os.path.dirname(os.path.abspath(__file__))
CRED = os.path.join(BASE, "credentials.json")
TOKEN = os.path.join(BASE, "token.json")

# 기본 수신자. 환경변수 RECIPIENTS로 지정(쉼표로 다중 수신자). 미설정이면 빈 값.
TO = os.environ.get("RECIPIENTS", "")
SUBJECT = "[IT 인사이트] 한국 IT 뉴스 분석"


def get_creds():
    # 클라우드(GitHub Actions): 환경변수 토큰 → 파일·브라우저 불필요
    env_creds = gauth.creds_from_env()
    if env_creds:
        return env_creds
    creds = None
    if os.path.exists(TOKEN):
        # 스코프 인자 없이 로드 → creds.scopes가 '실제 승인된' 스코프를 반영
        creds = Credentials.from_authorized_user_file(TOKEN)
    need_new = (
        not creds
        or not creds.has_scopes(SCOPES)
        or (not creds.valid and not creds.refresh_token)
    )
    if need_new:
        refreshed = False
        if creds and creds.expired and creds.refresh_token and creds.has_scopes(SCOPES):
            try:
                creds.refresh(Request())
                refreshed = True
            except RefreshError:
                # refresh token 만료·취소(테스팅 모드 7일) → 브라우저 재동의로 폴백
                refreshed = False
        if not refreshed:
            if os.environ.get("NEWSLETTER_NONINTERACTIVE"):
                # 무인 모드: 브라우저 재동의(무한 대기) 금지 → 즉시 실패
                raise RefreshError("무인 모드 — 브라우저 재동의 불가. 재인증 필요.")
            flow = InstalledAppFlow.from_client_secrets_file(CRED, SCOPES)
            # 브라우저가 다른 구글 계정으로 붙는 것 방지 → SENDER_EMAIL로 계정 강제 선택
            creds = flow.run_local_server(
                port=0,
                login_hint=os.environ.get("SENDER_EMAIL", ""),
                prompt="select_account consent",
            )
        with open(TOKEN, "w") as f:
            f.write(creds.to_json())
    return creds


def subject_from(text):
    for line in text.splitlines():
        if line.startswith("제목:"):
            return line.split("제목:", 1)[1].strip()
    return SUBJECT


def strip_subject_line(text):
    """본문 표시용: 맨 앞 '제목:' 줄과 뒤따르는 빈 줄 제거."""
    lines = text.splitlines()
    out, dropped = [], False
    for l in lines:
        if not dropped and l.startswith("제목:"):
            dropped = True
            continue
        out.append(l)
    return "\n".join(out).lstrip("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="본문 md 경로")
    ap.add_argument("--to", default=TO, help="수신자 이메일")
    ap.add_argument("--greeting", default="", help="본문 상단 인사말")
    args = ap.parse_args()

    raw_text = open(args.path, encoding="utf-8").read()
    subject = subject_from(raw_text)
    body_text = strip_subject_line(raw_text)

    if args.greeting:
        # 인사말만 bold → HTML 메일. 본문은 서식·줄바꿈 보존(pre-wrap).
        import html as _html
        greet = _html.escape(args.greeting.strip())
        body_html = _html.escape(body_text)
        html = (
            '<div style="font-family:\'Malgun Gothic\',sans-serif;font-size:14px;'
            'line-height:1.6;color:#222">'
            f'<p><strong>{greet}</strong></p>'
            f'<pre style="font-family:inherit;font-size:14px;white-space:pre-wrap;'
            f'margin:0">{body_html}</pre></div>'
        )
        msg = MIMEText(html, "html", "utf-8")
    else:
        msg = MIMEText(body_text, "plain", "utf-8")
    msg["To"] = args.to
    msg["Subject"] = subject

    creds = get_creds()
    gmail = build("gmail", "v1", credentials=creds)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
    print("발송 완료 id:", sent.get("id"), "→", args.to)


if __name__ == "__main__":
    main()
