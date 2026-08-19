# -*- coding: utf-8 -*-
"""완전 무인 원샷: 다운로드 → 헤드라인 추출 → claude -p 요약 → 메일 발송.
사용: python oneshot.py            (오늘 다운로드 후 전 과정)
      python oneshot.py 20260720   (해당 날짜 폴더로, 다운로드 생략)
      python oneshot.py 20260720 --no-send   (발송 없이 md만 생성·검토용)
요약은 Claude Code CLI 헤드리스(`claude -p`)로 생성 → 별도 API 키 불필요.
"""
import os, re, sys, glob, subprocess, shutil, datetime
import prep
import gauth

HERE = os.path.dirname(os.path.abspath(__file__))
DL = gauth.outdir()

PROMPT_TMPL = """다음은 오늘({date}) KAIT 조간·방송 스크랩에서 기계 추출한 국내 IT 뉴스 헤드라인 목록이다.
이걸로 국문 뉴스레터 본문(v3 형식)을 작성하라.

형식 규칙(엄수):
- 첫 줄: `제목: [국내 IT 트렌드] {date}`
- 그 아래 인트로 2~3문장(오늘 축이 되는 흐름 요약)
- 구분선 `────────────────────────────`
- 주요 뉴스 5~6건. 각 항목은 아래 3줄 구조:
    `N. 헤드라인 — 2~3문장 설명.`
    `   출처: 매체 면수 「원문 헤드라인」` (헤드라인 목록에 있는 매체·면수·제목 그대로. 여러 개면 ` / `로 구분)
    `   [검색] 원문검색 키워드 5~8단어` (매체명+핵심어. URL 아님, 키워드만)
- 마지막 구분선 뒤 `관통 흐름:` 한 문단으로 마무리.
- 국문. 수치·고유명사는 헤드라인에 있는 사실만 사용(없는 사실 지어내지 말 것).
- AI 티 금지: 이모지·화살표·과한 em-dash·마크다운 굵게 쓰지 말 것. 담백한 실무 문체.

출력은 뉴스레터 본문 텍스트만. 설명·머리말·코드블록 없이 `제목:`부터 바로 시작하라.

[헤드라인 목록]
{headlines}
"""

CONF_NOTICE = "※ 본 자료는 대외비 자료입니다. 외부 공유를 삼가 주시기 바랍니다."


def to_v3(body):
    """claude 출력의 `[검색] 키워드` 줄을 네이버 뉴스 검색 URL로 치환 + 대외비 문구 첨부."""
    from urllib.parse import quote

    def repl(m):
        kw = m.group(1).strip()
        return "   원문 검색: https://search.naver.com/search.naver?where=news&query=" + quote(kw)

    body = re.sub(r"^\s*\[검색\]\s*(.+)$", repl, body, flags=re.MULTILINE)
    if "대외비" not in body:
        body = body.rstrip() + "\n\n────────────────────────────\n\n" + CONF_NOTICE
    return body

STATUS = os.path.join(HERE, "LAST_STATUS.txt")


def write_status(state, date, msg=""):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(STATUS, "w", encoding="utf-8") as f:
        f.write(f"{state} {date} {ts} {msg}".rstrip() + "\n")


def alert(date, reason):
    """실패 경고를 RECIPIENTS 첫 주소로 발송. 대부분 실패는 Gmail 발송 이전 단계라 알림이 도달.
    Gmail 자체가 고장이면 경고도 실패 → LAST_STATUS.txt·run.log가 최종 기록."""
    to_addr = (os.environ.get("RECIPIENTS") or "").split(",")[0].strip()
    if not to_addr:
        print("경고메일 수신자 미설정(RECIPIENTS) — 발송 생략")
        return
    try:
        import base64
        from email.mime.text import MIMEText
        from googleapiclient.discovery import build
        import send_mail
        creds = send_mail.get_creds()
        gmail = build("gmail", "v1", credentials=creds)
        text = (f"IT뉴스레터 자동발송 실패\n\n날짜: {date}\n원인: {reason}\n"
                f"로그: {os.path.join(HERE, 'run.log')}\n상태: {STATUS}")
        msg = MIMEText(text, "plain", "utf-8")
        msg["To"] = to_addr
        msg["Subject"] = f"[IT뉴스레터 경고] {date} 자동발송 실패 — {reason[:40]}"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"경고메일 발송됨 → {to_addr}")
    except Exception as e:
        print("경고메일 발송 실패(상태파일로 대체):", e)


def validate(body):
    """발송 전 claude 출력 sanity check. (통과 여부, 사유)."""
    items = len(re.findall(r"^\s*\d+\.\s", body, flags=re.MULTILINE))
    src = len(re.findall(r"^\s*출처:", body, flags=re.MULTILINE))
    if len(body) < 400:
        return False, "본문 과소(<400자)"
    if "관통 흐름" not in body:
        return False, "관통 흐름 누락"
    if items < 5:
        return False, f"항목 부족({items}건, 5건 미만)"
    if src < 3:
        return False, f"출처 부족({src}건, 3건 미만)"
    return True, ""


def run_claude(prompt):
    exe = shutil.which("claude") or "claude"
    p = subprocess.run([exe, "-p", "--output-format", "text"],
                       input=prompt, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError(f"claude -p 실패(rc={p.returncode}): {p.stderr[:300]}")
    return p.stdout.strip()


DEFAULT_GREETING = "안녕하세요, 오늘의 IT 뉴스레터를 보내드립니다."


def _parse_external(raw):
    """"email" 또는 "email|인사말"을 ';'로 여러 개. (email, greeting) 리스트."""
    out = []
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if "|" in entry:
            e, g = entry.split("|", 1)
            out.append((e.strip(), g.strip()))
        else:
            out.append((entry, os.environ.get("NEWSLETTER_GREETING") or DEFAULT_GREETING))
    return out


def _send_one_external(md_path, date, email, greeting):
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "send_mail.py"), md_path,
         "--to", email, "--greeting", greeting]
    )
    if r.returncode != 0:
        print(f"외부 발송 실패(rc={r.returncode}) → {email}")
        alert(date, f"외부 발송 실패(rc={r.returncode}, to={email})")


def send_external(md_path, date):
    """외부 수신자 발송(수신자별 인사말 HTML). 내부 발송 성공 후에만 호출.

    - env NEWSLETTER_EXTERNAL_TO: 상시 수신자. ';'로 여러 명, 각 "email" 또는 "email|인사말".
    - env NEWSLETTER_EXTERNAL_ONCE: 하루짜리 수신자 "YYYYMMDD|email|인사말". 오늘(date) 일치할 때만 발송 → 다음날 자동 제외(자기소멸).
    미설정이면 건너뜀. 외부 실패는 내부 발송 안 되돌리고 경고만.
    """
    entries = _parse_external((os.environ.get("NEWSLETTER_EXTERNAL_TO") or "").strip())
    once = (os.environ.get("NEWSLETTER_EXTERNAL_ONCE") or "").strip()
    if once:
        p = once.split("|", 2)
        if len(p) == 3 and p[0].strip() == date:
            entries.append((p[1].strip(), p[2].strip()))
    for email, greeting in entries:
        _send_one_external(md_path, date, email, greeting)


def generate_and_send(folder, date, no_send):
    headlines = prep.collect(folder)
    print(f"헤드라인 {headlines.count(chr(10))}줄 수집. 요약 생성 중...")

    body = run_claude(PROMPT_TMPL.format(date=date, headlines=headlines))
    # 코드펜스 방어(모델이 감쌌을 경우 제거)
    body = re.sub(r"^```[a-z]*\n|\n```$", "", body.strip())
    if not body.startswith("제목:"):
        body = "제목: [국내 IT 트렌드] " + date + "\n\n" + body
    # v3 후처리: [검색] 키워드 → 네이버 검색 URL, 대외비 문구 첨부
    body = to_v3(body)

    # 발송 전 sanity check — 실패 시 발송 중단(오작동 본문 방지)
    ok, reason = validate(body)
    if not ok:
        raise RuntimeError(f"본문 검증 실패: {reason}")

    out = os.path.join(DL, f"newsletter_{date}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(body + "\n")
    print(f"본문 저장: {out}")

    if no_send:
        print("--no-send: 발송 생략. 본문 검토 후 수동 발송 가능.")
        return
    r = subprocess.run([sys.executable, os.path.join(HERE, "send_mail.py"), out])
    if r.returncode != 0:
        raise RuntimeError(f"send_mail 실패(rc={r.returncode})")
    send_external(out, date)
    # 발송 성공 표식(중복 방지용). 오래된 표식은 정리.
    open(os.path.join(HERE, f".sent_{date}"), "w").close()
    for old in glob.glob(os.path.join(HERE, ".sent_*")):
        if os.path.basename(old) != f".sent_{date}":
            try: os.remove(old)
            except OSError: pass


def run_download():
    return subprocess.run(
        [sys.executable, os.path.join(HERE, "download_newsletter.py")]
    ).returncode


def sent_today(date):
    """중복 발송 판정. 로컬 표식 → 없으면 Gmail 보낸편지함 이력으로 확인.

    클라우드 러너는 매 실행 새로 뜨므로 파일 표식이 남지 않는다. Gmail 이력이
    로컬·클라우드 공통 상태 저장소 역할을 한다(로컬 스케줄러와 이중 발송도 차단).
    """
    if os.path.exists(os.path.join(HERE, f".sent_{date}")):
        return True
    try:
        import send_mail

        return gauth.already_sent(send_mail.get_creds(), date)
    except Exception as e:
        print("발송이력 확인 실패(무시):", e)
        return False


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    no_send = "--no-send" in sys.argv
    force = "--force" in sys.argv  # dedup 우회(클라우드 실발송 검증용)
    auto = not argv  # 인자 없음 = 스케줄러 무인 모드
    if auto:
        # 무인 모드: 토큰 revoke 시 브라우저 폴백(무한 대기) 금지 → 즉시 실패+alert
        os.environ["NEWSLETTER_NONINTERACTIVE"] = "1"

    if argv:
        folder = os.path.join(DL, argv[0])
        if not os.path.isdir(folder):
            # 날짜 지정 실행인데 폴더가 없으면 먼저 받아온다(수동 만회 발송용)
            print(f"폴더 없음 → 다운로드 시도: {folder}")
            run_download()
    else:
        rc = run_download()
        today = datetime.date.today().strftime("%Y%m%d")
        if rc != 0:
            write_status("FAIL", today, f"download rc={rc}")
            alert(today, f"다운로드 실패(rc={rc})")
            sys.exit(1)
        folder = prep.latest_folder()
        # 무인 모드: 오늘 발송분이 없으면(주말·휴일 등) 이전 날짜 재발송 방지
        if not folder or os.path.basename(folder)[:8] != today:
            print(f"오늘({today}) 신규 조간 없음. 발송 생략.")
            write_status("SKIP", today, "신규 조간 없음")
            return
        # 같은 날 중복 발송 방지(스케줄 2회·로컬/클라우드 겹침 대비). --force면 우회.
        if not force and sent_today(today):
            print(f"{today} 이미 발송됨. 중복 발송 생략.")
            write_status("SKIP", today, "이미 발송됨")
            return
        if force:
            print("--force: dedup 우회(실발송 검증).")
    if not folder or not os.path.isdir(folder):
        sys.exit(f"폴더 없음: {folder}")

    date = os.path.basename(folder)[:8]
    try:
        generate_and_send(folder, date, no_send)
    except Exception as e:
        print("실패:", e)
        write_status("FAIL", date, str(e)[:120])
        if auto:
            alert(date, str(e)[:120])
        sys.exit(1)
    if not no_send:
        write_status("OK", date)


if __name__ == "__main__":
    main()
