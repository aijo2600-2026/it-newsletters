"""KAIT 조간스크랩 첨부 자동 다운로드 (Gmail API + Drive API, readonly).

매일 스케줄러로 실행. 대상 메일의 일반 첨부 + 대용량첨부(Drive 링크)를 로컬에 저장.
- 소스 계정: 환경변수 SENDER_EMAIL로 지정 (첫 실행 OAuth 동의로 연결)
- 발신/제목: 아래 SENDER/SUBJECT
- 저장: OUTDIR (날짜 하위폴더)

첫 실행만 브라우저 OAuth 필요. 이후 token.json 자동 갱신으로 무인 실행.
"""

import base64
import os
import re
import sys
from datetime import datetime

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import html as htmlmod
from urllib.parse import unquote
import requests

SCOPES = [
    # send 포함 → 재인증 시 한 번에 발송 스코프까지 확보(send_mail 별도 재동의 방지)
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
BASE = os.path.dirname(os.path.abspath(__file__))
CRED = os.path.join(BASE, "credentials.json")
TOKEN = os.path.join(BASE, "token.json")

import gauth

OUTDIR = gauth.outdir()
SENDER = "kaitpr@kait.or.kr"
SUBJECT = "조간스크랩"
QUERY = f'from:{SENDER} subject:{SUBJECT} newer_than:1d'


def log(*a):
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def get_creds():
    # 클라우드(GitHub Actions): 환경변수 토큰 → 파일·브라우저 불필요
    env_creds = gauth.creds_from_env()
    if env_creds:
        return env_creds
    creds = None
    if os.path.exists(TOKEN):
        # SCOPES 인자 없이 로드 → 갱신 시 send 등 상위 스코프를 좁히지 않음
        creds = Credentials.from_authorized_user_file(TOKEN)
    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refreshed = True
            except RefreshError:
                # refresh token 만료·취소(테스팅 모드 7일) → 재동의 폴백
                log("WARN: refresh token 만료·취소. 브라우저 재동의 필요.")
                refreshed = False
        if not refreshed:
            if os.environ.get("NEWSLETTER_NONINTERACTIVE"):
                # 무인 모드: 브라우저 재동의(무한 대기) 금지 → 즉시 실패
                log("ERROR: 토큰 갱신 실패·무인 모드 — 브라우저 재동의 불가. 재인증 필요.")
                sys.exit(3)
            if not os.path.exists(CRED):
                log("ERROR: credentials.json 없음. README 참고해 OAuth 클라이언트 받기.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CRED, SCOPES)
            creds = flow.run_local_server(
                port=0,
                login_hint=os.environ.get("SENDER_EMAIL", ""),
                prompt="select_account consent",
            )
        with open(TOKEN, "w") as f:
            f.write(creds.to_json())
    return creds


def walk_parts(part, acc):
    acc.append(part)
    for p in part.get("parts", []) or []:
        walk_parts(p, acc)


def save_regular_attachments(gmail, msg_id, payload, outdir):
    parts = []
    walk_parts(payload, parts)
    saved = 0
    for p in parts:
        fn = p.get("filename")
        body = p.get("body", {})
        att_id = body.get("attachmentId")
        if fn and att_id:
            att = (
                gmail.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=msg_id, id=att_id)
                .execute()
            )
            data = base64.urlsafe_b64decode(att["data"])
            path = os.path.join(outdir, fn)
            with open(path, "wb") as f:
                f.write(data)
            log("  일반첨부 저장:", fn, f"({len(data)//1024} KB)")
            saved += 1
    return saved


def get_html_body(payload):
    parts = []
    walk_parts(payload, parts)
    html = ""
    for p in parts:
        if p.get("mimeType") == "text/html":
            data = p.get("body", {}).get("data")
            if data:
                html += base64.urlsafe_b64decode(data).decode("utf-8", "ignore")
    return html


def find_largefile_links(html):
    # KAIT 대용량첨부 서버(agw.kait.or.kr) 링크. HTML 엔티티(&amp;) 복원.
    raw = re.findall(
        r"""href=["'](https?://agw\.kait\.or\.kr/mail/[^"' ]+)""", html
    )
    links = [htmlmod.unescape(u) for u in raw]
    return list(dict.fromkeys(links))  # 순서 유지 중복 제거


def _filename_from_cd(cd, fallback):
    if not cd:
        return fallback
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
    if m:
        return unquote(m.group(1))
    m = re.search(r'filename="?([^";]+)"?', cd)
    if m:
        name = m.group(1)
        try:  # UTF-8을 latin-1로 오독한 헤더 보정
            name = name.encode("latin-1").decode("utf-8")
        except Exception:
            pass
        return name
    return fallback


def save_largefile_links(urls, outdir):
    saved = 0
    for i, u in enumerate(urls):
        try:
            r = requests.get(u, stream=True, timeout=180, allow_redirects=True)
            r.raise_for_status()
            name = _filename_from_cd(
                r.headers.get("Content-Disposition"), f"download_{i+1}.pdf"
            )
            path = os.path.join(outdir, name)
            with open(path, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    if chunk:
                        f.write(chunk)
            r.close()
            mb = os.path.getsize(path) // 1024 // 1024
            log("  대용량첨부 저장:", name, f"({mb} MB)")
            saved += 1
        except Exception as e:
            log("  대용량첨부 실패:", u[:70], repr(e))
    return saved


def find_drive_file_ids(html):
    ids = set()
    for pat in [
        r"drive\.google\.com/file/d/([A-Za-z0-9_-]{20,})",
        r"drive\.google\.com/open\?id=([A-Za-z0-9_-]{20,})",
        r"[?&]id=([A-Za-z0-9_-]{25,})",
    ]:
        ids.update(re.findall(pat, html))
    return ids


def save_drive_files(drive, file_ids, outdir):
    saved = 0
    for fid in file_ids:
        try:
            meta = drive.files().get(fileId=fid, fields="name,size").execute()
            name = meta.get("name", fid + ".bin")
            req = drive.files().get_media(fileId=fid)
            buf = io.BytesIO()
            dl = MediaIoBaseDownload(buf, req)
            done = False
            while not done:
                _, done = dl.next_chunk()
            path = os.path.join(outdir, name)
            with open(path, "wb") as f:
                f.write(buf.getvalue())
            log("  대용량첨부 저장:", name, f"({len(buf.getvalue())//1024//1024} MB)")
            saved += 1
        except Exception as e:
            log("  대용량첨부 실패:", fid, repr(e))
    return saved


def main():
    creds = get_creds()
    gmail = build("gmail", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)

    res = gmail.users().messages().list(userId="me", q=QUERY).execute()
    msgs = res.get("messages", [])
    if not msgs:
        log("대상 메일 없음:", QUERY)
        return
    log(f"대상 메일 {len(msgs)}건")

    today = datetime.now().strftime("%Y%m%d")
    outdir = os.path.join(OUTDIR, today)
    os.makedirs(outdir, exist_ok=True)

    total = 0
    for m in msgs:
        full = (
            gmail.users()
            .messages()
            .get(userId="me", id=m["id"], format="full")
            .execute()
        )
        payload = full["payload"]
        total += save_regular_attachments(gmail, m["id"], payload, outdir)
        html = get_html_body(payload)
        links = find_largefile_links(html)
        if links:
            log(f"  대용량첨부 링크 {len(links)}개")
            total += save_largefile_links(links, outdir)
    log(f"완료: {total}개 파일 저장 → {outdir}")


if __name__ == "__main__":
    main()
