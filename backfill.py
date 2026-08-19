"""최근 30일 KAIT 조간스크랩 일괄 다운로드(백필). 기사일(제목 날짜) 폴더로 정리.

- 이미 있는 파일은 건너뜀(중복 방지).
- 각 메일의 mailbox 용량(sizeEstimate) 합계도 출력(삭제 효과 판단용).
"""

import os
import re
from googleapiclient.discovery import build
from download_newsletter import (
    get_creds, get_html_body, find_largefile_links,
    save_largefile_links, SENDER, SUBJECT, OUTDIR, log,
)

QUERY = f"from:{SENDER} subject:{SUBJECT} newer_than:30d"


def subject_date(subj):
    m = re.search(r"(\d{8})", subj or "")
    return m.group(1) if m else "unknown"


def main():
    g = build("gmail", "v1", credentials=get_creds())
    msgs = g.users().messages().list(userId="me", q=QUERY).execute().get("messages", [])
    log(f"백필 대상 {len(msgs)}건")
    total_files = 0
    total_bytes_mailbox = 0
    for m in msgs:
        full = g.users().messages().get(userId="me", id=m["id"], format="full").execute()
        total_bytes_mailbox += full.get("sizeEstimate", 0)
        hs = {h["name"]: h["value"] for h in full["payload"].get("headers", [])}
        date = subject_date(hs.get("Subject"))
        outdir = os.path.join(OUTDIR, date)
        os.makedirs(outdir, exist_ok=True)
        html = get_html_body(full["payload"])
        links = find_largefile_links(html)
        # 이미 받은 파일 스킵: save 전에 outdir 파일수로 판단(3개면 완료로 간주)
        existing = len([f for f in os.listdir(outdir) if f.lower().endswith(".pdf")])
        if existing >= len(links) and existing > 0:
            log(f"  {date}: 이미 {existing}개 있음 → 스킵")
            continue
        log(f"  {date}: 링크 {len(links)}개 다운로드")
        total_files += save_largefile_links(links, outdir)
    log(f"백필 완료: 신규 {total_files}개 파일")
    log(f"메일 mailbox 용량 합계(sizeEstimate): {total_bytes_mailbox/1024:.0f} KB "
        f"({total_bytes_mailbox/1024/1024:.2f} MB) — 21건 전체")


if __name__ == "__main__":
    main()
