"""로컬 보관기한 정리 — OUTDIR의 날짜폴더(YYYYMMDD) 중 RETAIN_DAYS 초과분 삭제.

날짜폴더만 대상(week 등 비(非)날짜 폴더·파일은 건드리지 않음).
원본은 KAIT 서버 30일 보관이라 재다운 가능. daily 실행 끝에 붙여 매일 자동 정돈.
"""

import datetime
import os
import re
import shutil

from download_newsletter import OUTDIR, log

RETAIN_DAYS = 30


def main():
    if not os.path.isdir(OUTDIR):
        return
    cutoff = datetime.date.today() - datetime.timedelta(days=RETAIN_DAYS)
    removed = 0
    for name in sorted(os.listdir(OUTDIR)):
        p = os.path.join(OUTDIR, name)
        if not os.path.isdir(p):
            continue
        m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", name)
        if not m:
            continue  # 날짜폴더만 정리 대상
        d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d < cutoff:
            shutil.rmtree(p)
            removed += 1
            log(f"보관기한 초과 삭제: {name}")
    log(f"정리 완료: {removed}개 폴더 삭제 (보관 {RETAIN_DAYS}일, 기준 {cutoff})")


if __name__ == "__main__":
    main()
