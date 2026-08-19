# -*- coding: utf-8 -*-
"""오늘치 뉴스레터 준비: 다운로드 + 헤드라인 추출 한 방.
사용: python prep.py            (오늘 다운로드 후 헤드라인 출력)
      python prep.py 20260720   (특정 날짜 폴더 헤드라인만 재출력, 다운로드 생략)
이후 Claude가 헤드라인으로 md 작성 → python send_mail.py <파일> 로 발송.
"""
import os, re, sys, glob, subprocess
from pdfminer.high_level import extract_text

import gauth

HERE = os.path.dirname(os.path.abspath(__file__))
DL = gauth.outdir()
KW = re.compile(r"AI|반도체|통신|데이터|SKT|KT|LGU|네이버|카카오|보안|해킹|개인정보|"
                r"로봇|메모리|플랫폼|디지털|5G|OTT|넷플|클라우드|양자|자율주행|칩")

def latest_folder():
    dirs = [d for d in glob.glob(os.path.join(DL, "20*")) if os.path.isdir(d)]
    return max(dirs, key=lambda d: os.path.basename(d)) if dirs else None

def collect(folder):
    """폴더 내 PDF 3종에서 IT 헤드라인을 뽑아 문자열로 반환."""
    out = [f"=== {os.path.basename(folder)} 헤드라인 ==="]
    for pdf in sorted(glob.glob(os.path.join(folder, "*.pdf"))):
        name = os.path.basename(pdf)
        small = os.path.getsize(pdf) < 3_000_000  # 방송뉴스=전체, 조간=목차만
        pages = None if small else [0, 1, 2, 3, 4, 5, 6, 7]
        try:
            txt = extract_text(pdf, page_numbers=pages)
        except Exception as e:
            out.append(f"[{name}] 추출 실패: {e}"); continue
        lines = [l.strip() for l in txt.splitlines() if l.strip()]
        hits = [l for l in lines if (small or KW.search(l)) and len(l) > 8]
        out.append(f"--- {name} ---")
        out.extend("  " + l for l in hits[:40])
    return "\n".join(out)

def dump(folder):
    print(collect(folder))

if __name__ == "__main__":
    if len(sys.argv) > 1:
        folder = os.path.join(DL, sys.argv[1])
    else:
        subprocess.run([sys.executable, os.path.join(HERE, "download_newsletter.py")])
        folder = latest_folder()
    if not folder or not os.path.isdir(folder):
        sys.exit(f"폴더 없음: {folder}")
    dump(folder)
