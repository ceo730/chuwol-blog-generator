"""
네이버 블로그 전체 글 텍스트 추출 스크립트
생기부추월차선 브랜드용 - 2개 블로그 크롤링
"""

import requests
from bs4 import BeautifulSoup
import re
import os
import time
import sys
from urllib.parse import unquote

# UTF-8 출력 설정
try:
    sys.stdout.reconfigure(encoding="utf-8")
except:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}


def get_post_list(blog_id):
    """블로그의 전체 글 목록(logNo)을 가져옵니다."""
    all_posts = []
    seen = set()
    page = 1
    count_per_page = 30

    headers = {**HEADERS, "Referer": f"https://blog.naver.com/{blog_id}"}
    print("글 목록을 수집하는 중...")

    while True:
        url = (
            f"https://blog.naver.com/PostTitleListAsync.naver"
            f"?blogId={blog_id}"
            f"&viewdate="
            f"&currentPage={page}"
            f"&categoryNo=0"
            f"&parentCategoryNo=0"
            f"&countPerPage={count_per_page}"
        )

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [오류] 페이지 {page} 요청 실패: {e}")
            break

        text = resp.text

        log_nos = re.findall(r'"logNo"\s*:\s*"(\d+)"', text)
        titles = re.findall(r'"title"\s*:\s*"([^"]*?)"', text)
        dates = re.findall(r'"addDate"\s*:\s*"([^"]*?)"', text)

        if not log_nos:
            break

        count = 0
        for i, no in enumerate(log_nos):
            if no not in seen:
                seen.add(no)
                title = unquote(titles[i].replace("+", " ")) if i < len(titles) else ""
                date = dates[i] if i < len(dates) else ""
                all_posts.append((no, title, date))
                count += 1

        print(f"  페이지 {page}: {count}개 글 발견 (누적: {len(all_posts)}개)")

        if len(log_nos) < count_per_page:
            break

        page += 1
        time.sleep(0.3)

    print(f"\n총 {len(all_posts)}개의 글을 발견했습니다.\n")
    return all_posts


def get_post_content(blog_id, log_no):
    """개별 글의 텍스트 내용을 추출합니다."""
    headers = {**HEADERS, "Referer": f"https://blog.naver.com/{blog_id}"}
    url = (
        f"https://blog.naver.com/PostView.naver"
        f"?blogId={blog_id}"
        f"&logNo={log_no}"
        f"&redirect=Dlog"
        f"&widgetTypeCall=true"
        f"&directAccess=true"
    )

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return None, None

    soup = BeautifulSoup(resp.text, "html.parser")

    # 제목 추출
    title = ""
    for sel in [".se-title-text", ".pcol1", "title"]:
        tag = soup.select_one(sel)
        if tag:
            title = tag.get_text(strip=True)
            break

    # 본문 텍스트 추출
    content_text = ""

    # SmartEditor 3 (SE3)
    se3_container = soup.select_one(".se-main-container")
    if se3_container:
        components = se3_container.select(".se-component")
        if components:
            lines = []
            for comp in components:
                text_parts = comp.select(".se-text-paragraph")
                if text_parts:
                    for p in text_parts:
                        txt = p.get_text(separator=" ", strip=True)
                        if txt:
                            lines.append(txt)
                    lines.append("")
                else:
                    quotation = comp.select_one(".se-quotation-text")
                    if quotation:
                        lines.append(quotation.get_text(strip=True))
                        lines.append("")
            content_text = "\n".join(lines)
        else:
            content_text = se3_container.get_text(separator="\n", strip=True)

    # SmartEditor 2 (SE2)
    if not content_text:
        for sel in ["#postViewArea", ".post-view", "#content-area", ".post_ct"]:
            container = soup.select_one(sel)
            if container:
                content_text = container.get_text(separator="\n", strip=True)
                break

    # 텍스트 정리
    if content_text:
        lines = content_text.split("\n")
        cleaned = []
        prev_empty = False
        for line in lines:
            line = line.strip()
            if not line:
                if not prev_empty:
                    cleaned.append("")
                prev_empty = True
            else:
                cleaned.append(line)
                prev_empty = False
        content_text = "\n".join(cleaned).strip()

    return title, content_text


def sanitize_filename(name, max_length=80):
    name = re.sub(r'[\\/:*?"<>|\r\n\t\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > max_length:
        name = name[:max_length].strip()
    return name if name else "untitled"


def crawl_blog(blog_id, output_dir):
    """한 블로그의 전체 글을 크롤링합니다."""
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print(f"  네이버 블로그 크롤러 - {blog_id}")
    print(f"  저장 위치: {output_dir}")
    print("=" * 60)
    print()

    post_list = get_post_list(blog_id)

    if not post_list:
        print("글을 찾을 수 없습니다.")
        return

    existing_files = set(os.listdir(output_dir))
    success_count = 0
    skip_count = 0
    fail_count = 0
    total = len(post_list)

    for idx, (log_no, list_title, date) in enumerate(post_list, 1):
        prefix = f"{idx:04d}_"
        already_done = any(f.startswith(prefix) for f in existing_files)
        if already_done:
            skip_count += 1
            print(f"[{idx}/{total}] 건너뜀 (이미 존재)")
            continue

        display_title = list_title[:40] if list_title else log_no
        print(f"[{idx}/{total}] {display_title}...", end=" ", flush=True)

        title, content = get_post_content(blog_id, log_no)

        if content:
            safe_title = sanitize_filename(title or list_title or "untitled")
            filename = f"{idx:04d}_{safe_title}.txt"
            filepath = os.path.join(output_dir, filename)

            full_text = ""
            if title:
                full_text += f"제목: {title}\n"
            if date:
                full_text += f"날짜: {date}\n"
            full_text += f"URL: https://blog.naver.com/{blog_id}/{log_no}\n"
            full_text += "-" * 50 + "\n\n"
            full_text += content

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(full_text)

            existing_files.add(filename)
            print("OK")
            success_count += 1
        else:
            safe_title = sanitize_filename(list_title or "untitled")
            filename = f"{idx:04d}_{safe_title}.txt"
            filepath = os.path.join(output_dir, filename)

            full_text = f"제목: {list_title or '(제목 없음)'}\n"
            if date:
                full_text += f"날짜: {date}\n"
            full_text += f"URL: https://blog.naver.com/{blog_id}/{log_no}\n"
            full_text += "-" * 50 + "\n\n"
            full_text += "(본문 추출 실패 - 비공개 글이거나 특수 형식일 수 있습니다)"

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(full_text)

            existing_files.add(filename)
            print("EMPTY (비공개/특수형식)")
            fail_count += 1

        time.sleep(0.5)

    print()
    print("=" * 60)
    print(f"  {blog_id} 크롤링 완료!")
    print(f"  성공: {success_count}개")
    print(f"  건너뜀: {skip_count}개")
    print(f"  실패/비어있음: {fail_count}개")
    print(f"  저장 위치: {output_dir}")
    print("=" * 60)
    print()


if __name__ == "__main__":
    blogs = [
        ("sobutab7", os.path.join(BASE_DIR, "posts_sobutab7")),
        ("gmm0301", os.path.join(BASE_DIR, "posts_gmm0301")),
    ]

    for blog_id, output_dir in blogs:
        crawl_blog(blog_id, output_dir)

    print("\n모든 블로그 크롤링이 완료되었습니다!")
