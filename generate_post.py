"""
생기부추월차선 블로그 글 자동 생성기
키워드를 입력하면 2500~3500자 분량의 블로그 글을 생성합니다.
"""

import os
import sys
import re
import time
import random
import requests
from bs4 import BeautifulSoup
import anthropic

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 보이지 않는 유니코드 문자 제거용 패턴
_INVISIBLE_CHARS = re.compile(
    "["
    "\u00a0"    # Non-breaking space
    "\u00ad"    # Soft hyphen
    "\u034f"    # Combining grapheme joiner
    "\u061c"    # Arabic letter mark
    "\u115f"    # Hangul choseong filler
    "\u1160"    # Hangul jungseong filler
    "\u17b4"    # Khmer vowel inherent aq
    "\u17b5"    # Khmer vowel inherent aa
    "\u180e"    # Mongolian vowel separator
    "\u200b"    # Zero-width space
    "\u200c"    # Zero-width non-joiner
    "\u200d"    # Zero-width joiner
    "\u200e"    # Left-to-right mark
    "\u200f"    # Right-to-left mark
    "\u202a-\u202e"  # Directional formatting
    "\u2060"    # Word joiner
    "\u2066-\u2069"  # Directional isolates
    "\u2028"    # Line separator
    "\u2029"    # Paragraph separator
    "\u205f"    # Medium mathematical space
    "\u3000"    # Ideographic space
    "\u3164"    # Hangul filler
    "\ufeff"    # BOM / Zero-width no-break space
    "\uffa0"    # Halfwidth Hangul filler
    "\ufff9-\ufffb"  # Interlinear annotation
    "]"
)


def clean_invisible_chars(text):
    """보이지 않는 유니코드 문자를 제거하고 일반 공백(ASCII space)만 남깁니다."""
    text = _INVISIBLE_CHARS.sub("", text)
    return text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STYLE_GUIDE_PATH = os.path.join(BASE_DIR, "style_guide.txt")
POSTS_DIRS = [
    os.path.join(BASE_DIR, "posts_sobutab7"),
    os.path.join(BASE_DIR, "posts_gmm0301"),
]
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SEARCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}


def load_style_guide():
    with open(STYLE_GUIDE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def load_sample_posts(keyword, n=3):
    """키워드와 관련된 기존 글을 n개 찾아 few-shot 예시로 로드합니다."""
    all_files = []
    for d in POSTS_DIRS:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".txt"):
                    all_files.append((d, f))

    scored = []
    kw_parts = keyword.split()

    for d, fname in all_files:
        title_part = fname[5:].replace(".txt", "")
        score = 0
        for part in kw_parts:
            if part in title_part:
                score += 2
        if keyword in title_part:
            score += 3
        if score > 0:
            scored.append((score, d, fname))

    scored.sort(key=lambda x: -x[0])

    if not scored:
        selected = random.sample(all_files, min(n, len(all_files)))
    else:
        selected = [(s[1], s[2]) for s in scored[:n]]

    samples = []
    for d, fname in selected:
        path = os.path.join(d, fname)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        parts = text.split("-" * 50, 1)
        body = parts[1].strip() if len(parts) >= 2 else text
        if len(body) > 4000:
            body = body[:4000] + "\n...(이하 생략)"
        samples.append(body)

    return samples


def search_naver(keyword, num_results=8):
    """네이버 검색으로 최신 입시 정보를 수집합니다."""
    results = []
    base_url = "https://search.naver.com/search.naver"

    # VIEW 탭
    query_view = f"{keyword} 입시 2025 2026"
    print(f"  네이버 VIEW 검색: '{query_view}'")
    try:
        resp = requests.get(
            base_url,
            params={"where": "view", "query": query_view, "sm": "tab_jum"},
            headers=SEARCH_HEADERS, timeout=10,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        for a_tag in soup.select('a[href*="blog.naver.com"], a[href*="post.naver.com"]'):
            title = a_tag.get_text(strip=True)
            if title and len(title) > 15 and len(results) < num_results:
                parent = a_tag.find_parent()
                snippet = ""
                if parent:
                    grandparent = parent.find_parent()
                    if grandparent:
                        all_text = grandparent.get_text(separator="|", strip=True)
                        parts = [p.strip() for p in all_text.split("|") if len(p.strip()) > 20]
                        if len(parts) > 1:
                            snippet = parts[1][:200]
                if not any(r["title"] == title for r in results):
                    results.append({"title": title, "snippet": snippet})
    except Exception as e:
        print(f"  [경고] VIEW 검색 실패: {e}")

    # 뉴스 탭
    query_news = f"{keyword} 입시 2025"
    print(f"  네이버 뉴스 검색: '{query_news}'")
    try:
        resp2 = requests.get(
            base_url,
            params={"where": "news", "query": query_news, "sm": "tab_jum"},
            headers=SEARCH_HEADERS, timeout=10,
        )
        soup2 = BeautifulSoup(resp2.text, "html.parser")
        for a_tag in soup2.select("a.news_tit"):
            title = a_tag.get_text(strip=True)
            if title and len(title) > 10:
                parent = a_tag.find_parent("div") or a_tag.find_parent("li")
                snippet = ""
                if parent:
                    desc_tag = parent.select_one(".news_dsc, .dsc_wrap, .api_txt_lines.dsc_txt")
                    if desc_tag:
                        snippet = desc_tag.get_text(strip=True)[:200]
                if not any(r["title"] == f"[뉴스] {title}" for r in results):
                    results.append({"title": f"[뉴스] {title}", "snippet": snippet})
                if len(results) >= num_results + 3:
                    break
    except Exception as e:
        print(f"  [경고] 뉴스 검색 실패: {e}")

    # 통합검색 fallback
    if len(results) < 3:
        print(f"  네이버 통합검색 (fallback)...")
        try:
            resp3 = requests.get(
                base_url,
                params={"where": "nexearch", "query": f"{keyword} 대입 2026", "sm": "tab_jum"},
                headers=SEARCH_HEADERS, timeout=10,
            )
            soup3 = BeautifulSoup(resp3.text, "html.parser")
            for a_tag in soup3.select("a"):
                href = a_tag.get("href", "")
                title = a_tag.get_text(strip=True)
                if title and len(title) > 15 and ("blog" in href or "news" in href or "post" in href):
                    if not any(r["title"] == title for r in results):
                        results.append({"title": title, "snippet": ""})
                    if len(results) >= num_results:
                        break
        except Exception:
            pass

    print(f"  검색 결과 {len(results)}건 수집 완료")
    return results


def generate_article(keyword, api_key):
    """Claude API를 호출하여 블로그 글을 생성합니다."""
    print("\n[1/3] 스타일 가이드 및 샘플 글 로딩...")
    style_guide = load_style_guide()
    samples = load_sample_posts(keyword, n=3)

    print("[2/3] 최신 입시 정보 웹 검색...")
    web_results = search_naver(keyword)

    web_info = ""
    if web_results:
        web_info = "아래는 최신 웹 검색 결과입니다. 이 중 신뢰할 만한 정보를 활용하세요:\n\n"
        for i, r in enumerate(web_results, 1):
            web_info += f"[{i}] {r['title']}\n{r['snippet']}\n\n"
    else:
        web_info = "(웹 검색 결과가 없습니다. 일반적인 입시 지식을 활용하세요.)\n"

    sample_text = ""
    if samples:
        sample_text = "아래는 기존에 작성된 블로그 글의 예시입니다. 문체와 구조를 참고하세요:\n\n"
        for i, s in enumerate(samples, 1):
            sample_text += f"--- 예시 {i} ---\n{s}\n\n"

    system_prompt = f"""{style_guide}

═══════════════════════════════════════
[참고 예시 글]
═══════════════════════════════════════
{sample_text}
"""

    user_prompt = f"""키워드: "{keyword}"

{web_info}

위 키워드로 블로그 글을 작성해주세요.

작성 규칙:
1. 반드시 4단계 구조를 따르세요: 도입/공감(10%) → 정보/분석(35%) → 결핍 만들기(40%) → CTA/마무리(15%)
2. 본문 약 2000~2600자 (공백 포함, 빈 줄 제외) 분량으로 작성
3. 웹 검색에서 얻은 최신 정보(2025~2026년)를 자연스럽게 반영
4. 제목은 "키워드, 호기심 유발 문구" 패턴으로 작성 (제목 끝에 "..."을 자주 붙임)
5. 네이버 블로그에 바로 붙여넣기 할 수 있도록 순수 텍스트로 작성 (마크다운 금지)
6. 글 끝에 생기부 연구소 CTA 블록을 반드시 포함
7. 문단은 1~3문장으로 짧게 끊고, 문단 사이에 빈 줄을 넣으세요 (평균 18.5개 문단)
8. 격식체(-합니다, -입니다) 위주로 작성하세요
9. 한 문장은 50자 이내로 짧게 작성
10. 3단계 '결핍 만들기'에서는 합격생 생기부를 모르면 불합격한다는 긴박감을 조성하고, 생기부 자료집이 그 해답임을 자연스럽게 연결하세요
11. 마무리 인사: '감사합니다. 대학 심사관 출신들과 서울대 출신 연구진들의, 생기부 연구소였습니다.'
12. 이모지/이모티콘 사용 금지, AI가 쓴 티가 나는 기계적 전환 표현 금지

출력 형식:
[제목]
(제목만 한 줄)

[본문]
(본문 전체)
"""

    print("[3/3] Claude API로 글 생성 중...")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=6000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    response_text = message.content[0].text

    title = ""
    body = response_text

    title_match = re.search(r"\[제목\]\s*\n(.+)", response_text)
    body_match = re.search(r"\[본문\]\s*\n([\s\S]+)", response_text)

    if title_match:
        title = title_match.group(1).strip()
    if body_match:
        body = body_match.group(1).strip()

    if not title_match and not body_match:
        lines = response_text.strip().split("\n")
        if lines:
            title = lines[0].strip()
            body = "\n".join(lines[1:]).strip()

    # 보이지 않는 유니코드 문자 제거
    title = clean_invisible_chars(title)
    body = clean_invisible_chars(body)

    content_lines = [l for l in body.split("\n") if l.strip()]
    char_count = sum(len(l) for l in content_lines)

    return title, body, char_count


def save_output(keyword, title, body):
    safe_keyword = re.sub(r'[\\/:*?"<>|]', "", keyword)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_keyword}_{timestamp}.txt"
    filepath = os.path.join(OUTPUT_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"제목: {title}\n")
        f.write(f"키워드: {keyword}\n")
        f.write(f"생성일: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("-" * 50 + "\n\n")
        f.write(body)

    return filepath


def get_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if key:
                        return key
    return ""


def main():
    print("=" * 60)
    print("  생기부 연구소 - 블로그 글 자동 생성기")
    print("=" * 60)
    print()

    api_key = get_api_key()
    if not api_key:
        print("[오류] API 키가 필요합니다.")
        return

    while True:
        print()
        keyword = input("키워드를 입력하세요 (종료: q): ").strip()
        if not keyword or keyword.lower() == "q":
            print("프로그램을 종료합니다.")
            break

        try:
            title, body, char_count = generate_article(keyword, api_key)
            print(f"\n{'=' * 60}")
            print(f"  제목: {title}")
            print(f"  본문 글자 수: {char_count}자")
            print(f"{'=' * 60}")
            print()
            print(body)
            print()
            filepath = save_output(keyword, title, body)
            print(f"\n저장 완료: {filepath}")
        except anthropic.AuthenticationError:
            print("\n[오류] API 키가 유효하지 않습니다.")
        except anthropic.RateLimitError:
            print("\n[오류] API 요청 한도 초과.")
        except Exception as e:
            print(f"\n[오류] 글 생성 실패: {e}")


if __name__ == "__main__":
    main()
