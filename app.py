"""
생기부추월차선 블로그 글 생성기 - 웹 버전
Flask 서버로 팀원들과 공유하여 사용할 수 있습니다.
"""

import os
import sys
import json
import time
import re
import queue
import threading
import base64

from flask import Flask, render_template, request, jsonify, Response, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_post import (
    load_style_guide,
    load_sample_posts,
    search_naver,
    save_output,
    clean_invisible_chars,
)
import anthropic

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB


def get_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("ANTHROPIC_API_KEY="):
                    return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return ""


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    keywords_raw = request.json.get("keywords", "").strip()
    if not keywords_raw:
        return jsonify({"error": "키워드를 입력해주세요."}), 400

    keywords = [kw.strip() for kw in keywords_raw.split("\n") if kw.strip()]
    if not keywords:
        return jsonify({"error": "키워드를 입력해주세요."}), 400
    if len(keywords) > 50:
        return jsonify({"error": "키워드는 최대 50개까지 입력 가능합니다."}), 400

    api_key = get_api_key()
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY가 설정되지 않았습니다."}), 500

    progress_q = queue.Queue()

    def worker():
        total = len(keywords)
        client = anthropic.Anthropic(api_key=api_key)

        # 스타일 가이드는 한 번만 로딩
        try:
            style_guide = load_style_guide()
        except Exception as e:
            progress_q.put({"error": True, "msg": f"스타일 가이드 로딩 실패: {str(e)}"})
            return

        for idx, keyword in enumerate(keywords):
            kw_num = idx + 1
            progress_q.put({
                "type": "keyword_start",
                "keyword": keyword,
                "current": kw_num,
                "total": total,
                "step": 1,
                "msg": f"[{kw_num}/{total}] '{keyword}' - 참고 글 로딩 중...",
            })

            try:
                samples = load_sample_posts(keyword, n=3)

                progress_q.put({
                    "type": "step",
                    "keyword": keyword,
                    "current": kw_num,
                    "total": total,
                    "step": 2,
                    "msg": f"[{kw_num}/{total}] '{keyword}' - 네이버 검색 중...",
                })
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

                system_prompt = (
                    f"{style_guide}\n\n"
                    "═══════════════════════════════════════\n"
                    "[참고 예시 글]\n"
                    "═══════════════════════════════════════\n"
                    f"{sample_text}"
                )

                user_prompt = (
                    f'키워드: "{keyword}"\n\n'
                    f"{web_info}\n"
                    "위 키워드로 블로그 글을 작성해주세요.\n\n"
                    "작성 규칙:\n"
                    "1. 반드시 4단계 구조를 따르세요: 도입/공감(10%) → 정보/분석(35%) → 결핍 만들기(40%) → CTA/마무리(15%)\n"
                    "2. 본문 약 2000~2600자 (공백 포함, 빈 줄 제외) 분량으로 작성\n"
                    "3. 웹 검색에서 얻은 최신 정보(2025~2026년)를 자연스럽게 반영\n"
                    '4. 제목은 "키워드, 호기심 유발 문구" 패턴으로 작성 (제목 끝에 "..."을 자주 붙임)\n'
                    "5. 네이버 블로그에 바로 붙여넣기 할 수 있도록 순수 텍스트로 작성 (마크다운 금지)\n"
                    "6. 글 끝에 생기부 연구소 CTA 블록을 반드시 포함\n"
                    "7. 문단은 1~3문장으로 짧게 끊고, 문단 사이에 빈 줄을 넣으세요 (평균 18.5개 문단)\n"
                    "8. 격식체(-합니다, -입니다) 위주로 작성하세요\n"
                    "9. 한 문장은 50자 이내로 짧게 작성\n"
                    "10. 3단계 '결핍 만들기'에서는 합격생 생기부를 모르면 불합격한다는 긴박감을 조성하고, 생기부 자료집이 그 해답임을 자연스럽게 연결하세요\n"
                    "11. 마무리 인사: '감사합니다. 대학 심사관 출신들과 서울대 출신 연구진들의, 생기부 연구소였습니다.'\n"
                    "12. 이모지/이모티콘 사용 금지, AI가 쓴 티가 나는 기계적 전환 표현 금지\n\n"
                    "출력 형식:\n"
                    "[제목]\n(제목만 한 줄)\n\n"
                    "[본문]\n(본문 전체)\n"
                )

                progress_q.put({
                    "type": "step",
                    "keyword": keyword,
                    "current": kw_num,
                    "total": total,
                    "step": 3,
                    "msg": f"[{kw_num}/{total}] '{keyword}' - Claude API 생성 중...",
                })

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

                content_lines = [l for l in body.split("\n") if l.strip()]
                char_count = sum(len(l) for l in content_lines)

                filepath = save_output(keyword, title, body)
                filename = os.path.basename(filepath)

                progress_q.put({
                    "type": "keyword_done",
                    "keyword": keyword,
                    "current": kw_num,
                    "total": total,
                    "title": title,
                    "body": body,
                    "char_count": char_count,
                    "filename": filename,
                    "web_count": len(web_results),
                })

            except anthropic.AuthenticationError:
                progress_q.put({
                    "type": "keyword_error",
                    "keyword": keyword,
                    "current": kw_num,
                    "total": total,
                    "msg": f"[{kw_num}/{total}] '{keyword}' - API 키가 유효하지 않습니다.",
                })
                break
            except anthropic.RateLimitError:
                progress_q.put({
                    "type": "keyword_error",
                    "keyword": keyword,
                    "current": kw_num,
                    "total": total,
                    "msg": f"[{kw_num}/{total}] '{keyword}' - API 요청 한도 초과. 잠시 후 재시도...",
                })
                time.sleep(30)
                # 재시도하지 않고 다음 키워드로 진행
                continue
            except Exception as e:
                progress_q.put({
                    "type": "keyword_error",
                    "keyword": keyword,
                    "current": kw_num,
                    "total": total,
                    "msg": f"[{kw_num}/{total}] '{keyword}' - 오류: {str(e)}",
                })
                continue

        progress_q.put({"type": "all_done", "total": total})

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    def stream():
        while True:
            try:
                data = progress_q.get(timeout=180)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                if data.get("type") == "all_done" or (data.get("error") and data.get("type") != "keyword_error"):
                    break
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat', 'msg': '처리 중...'}, ensure_ascii=False)}\n\n"

    return Response(stream(), mimetype="text/event-stream")


@app.route("/generate-single", methods=["POST"])
def generate_single():
    keyword = request.form.get("keyword", "").strip()
    title = request.form.get("title", "").strip()

    if not keyword:
        return jsonify({"error": "키워드를 입력해주세요."}), 400
    if not title:
        return jsonify({"error": "제목을 입력해주세요."}), 400

    images = []
    files = request.files.getlist("images")
    for f in files:
        if f and f.filename:
            data = f.read()
            b64 = base64.b64encode(data).decode("utf-8")
            media_type = f.content_type or "image/jpeg"
            images.append({"data": b64, "media_type": media_type})

    if not images:
        return jsonify({"error": "세특 사진을 최소 1장 업로드해주세요."}), 400

    api_key = get_api_key()
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY가 설정되지 않았습니다."}), 500

    progress_q = queue.Queue()

    def worker():
        client = anthropic.Anthropic(api_key=api_key)

        try:
            progress_q.put({"type": "step", "step": 1, "msg": "스타일 가이드 및 참고 글 로딩 중..."})
            style_guide = load_style_guide()
            samples = load_sample_posts(keyword, n=3)

            progress_q.put({"type": "step", "step": 2, "msg": "네이버 검색 중..."})
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

            system_prompt = (
                f"{style_guide}\n\n"
                "═══════════════════════════════════════\n"
                "[참고 예시 글]\n"
                "═══════════════════════════════════════\n"
                f"{sample_text}"
            )

            user_prompt = (
                f'키워드: "{keyword}"\n'
                f'제목: "{title}"\n\n'
                "위 사진들은 실제 합격생의 세부특기사항(세특) 이미지입니다.\n"
                "사진 속 세특 내용을 꼼꼼히 읽고, 이를 바탕으로 블로그 글을 작성해주세요.\n\n"
                f"{web_info}\n"
                "작성 규칙:\n"
                "1. 반드시 4단계 구조를 따르세요: 도입/공감(10%) → 정보/분석(35%) → 결핍 만들기(40%) → CTA/마무리(15%)\n"
                "2. 본문 약 2000~2600자 (공백 포함, 빈 줄 제외) 분량으로 작성\n"
                "3. 웹 검색에서 얻은 최신 정보(2025~2026년)를 자연스럽게 반영\n"
                f'4. 제목은 반드시 "{title}"을 그대로 사용하세요\n'
                "5. 사진 속 세특 내용(과목, 활동, 탐구 주제, 선생님 코멘트 등)을 2단계 정보/분석 파트에서 구체적으로 인용하고 분석하세요\n"
                "6. 네이버 블로그에 바로 붙여넣기 할 수 있도록 순수 텍스트로 작성 (마크다운 금지)\n"
                "7. 글 끝에 생기부 연구소 CTA 블록을 반드시 포함\n"
                "8. 문단은 1~3문장으로 짧게 끊고, 문단 사이에 빈 줄을 넣으세요 (평균 18.5개 문단)\n"
                "9. 격식체(-합니다, -입니다) 위주로 작성하세요\n"
                "10. 한 문장은 50자 이내로 짧게 작성\n"
                "11. 3단계 '결핍 만들기'에서는 합격생 생기부를 모르면 불합격한다는 긴박감을 조성하고, 생기부 자료집이 그 해답임을 자연스럽게 연결하세요\n"
                "12. 마무리 인사: '감사합니다. 대학 심사관 출신들과 서울대 출신 연구진들의, 생기부 연구소였습니다.'\n"
                "13. 이모지/이모티콘 사용 금지, AI가 쓴 티가 나는 기계적 전환 표현 금지\n\n"
                "출력 형식:\n"
                "[본문]\n(본문 전체)\n"
            )

            msg_content = []
            for img in images:
                msg_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img["media_type"],
                        "data": img["data"],
                    },
                })
            msg_content.append({"type": "text", "text": user_prompt})

            progress_q.put({
                "type": "step", "step": 3,
                "msg": f"Claude API로 글 생성 중... (사진 {len(images)}장 분석)",
            })

            message = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=6000,
                system=system_prompt,
                messages=[{"role": "user", "content": msg_content}],
            )

            response_text = message.content[0].text

            body = response_text
            body_match = re.search(r"\[본문\]\s*\n([\s\S]+)", response_text)
            if body_match:
                body = body_match.group(1).strip()

            body = clean_invisible_chars(body)

            content_lines = [l for l in body.split("\n") if l.strip()]
            char_count = sum(len(l) for l in content_lines)

            filepath = save_output(keyword, title, body)
            filename = os.path.basename(filepath)

            progress_q.put({
                "type": "done",
                "title": title,
                "body": body,
                "char_count": char_count,
                "filename": filename,
                "web_count": len(web_results),
                "image_count": len(images),
            })

        except anthropic.AuthenticationError:
            progress_q.put({"type": "error", "msg": "API 키가 유효하지 않습니다."})
        except anthropic.RateLimitError:
            progress_q.put({"type": "error", "msg": "API 요청 한도 초과. 잠시 후 재시도해주세요."})
        except Exception as e:
            progress_q.put({"type": "error", "msg": f"오류: {str(e)}"})

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    def stream():
        while True:
            try:
                data = progress_q.get(timeout=30)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                if data.get("type") in ("done", "error"):
                    break
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat', 'msg': '처리 중...'}, ensure_ascii=False)}\n\n"

    return Response(stream(), mimetype="text/event-stream")


@app.route("/history")
def history():
    files = []
    if os.path.isdir(OUTPUT_DIR):
        for fname in sorted(os.listdir(OUTPUT_DIR), reverse=True):
            if not fname.endswith(".txt"):
                continue
            fpath = os.path.join(OUTPUT_DIR, fname)
            title = keyword = created = ""
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("제목:"):
                            title = line[3:].strip()
                        elif line.startswith("키워드:"):
                            keyword = line[4:].strip()
                        elif line.startswith("생성일:"):
                            created = line[4:].strip()
                        elif line.startswith("---"):
                            break
            except Exception:
                pass
            files.append({
                "filename": fname,
                "title": title,
                "keyword": keyword,
                "created": created,
            })
    return jsonify(files)


@app.route("/download/<path:filename>")
def download(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    print()
    print("=" * 55)
    print("  생기부 연구소 - 블로그 글 생성기 (웹 버전)")
    print("=" * 55)
    print()

    key = get_api_key()
    if key:
        print(f"  API Key: {key[:12]}...{key[-4:]}")
    else:
        print("  [경고] ANTHROPIC_API_KEY 미설정!")

    print(f"  로컬 접속: http://localhost:5000")
    print()
    print("  종료: Ctrl+C")
    print("=" * 55)
    print()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
