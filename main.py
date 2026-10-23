"""기찾이 실행 스크립트: Google 뉴스에서 기사를 모아 Gemini 로 분석하고 결과를 보여준다.

실행:
    python main.py                    # 키워드와 개수를 물어봄
    python main.py 인공지능            # 키워드 지정
    python main.py 인공지능 5 --days 3 # 최근 3일, 5건
    python main.py 인공지능 --no-body  # 원문 본문 안 가져오고 제목만으로 분석

흐름:
    google_news.search_news  ->  (원문 본문 추출)  ->  news_analyzer.analyze_news  ->  출력 + JSON 저장
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from article_text import fetch_article_text
from google_news import resolve_original_link, search_news
from news_analyzer import analyze_news

RESULT_DIR = Path(__file__).parent / "results"
GEMINI_CALL_INTERVAL = 2.0     # 무료 한도 보호용 호출 간격(초)


# ---------------------------------------------------------------- 출력
def _fmt_date(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "-"


def print_result(index: int, article: dict, analysis: dict | None, error: str | None) -> None:
    print(f"\n[{index}] {article['title']}")
    print(f"    언론사: {article['source'] or '-'}   날짜: {_fmt_date(article['pub_date'])}")
    print(f"    링크: {article.get('original_link') or article['link']}")

    if error:
        print(f"    분석 실패: {error}")
        return
    if not analysis:
        return

    keywords = analysis.get("keywords") or []
    if isinstance(keywords, list):
        keywords = ", ".join(str(k) for k in keywords)

    summary = analysis.get("summary") or []
    if isinstance(summary, list):
        summary = " ".join(str(s) for s in summary)

    print(f"    요약: {summary or '-'}")
    print(f"    분야: {analysis.get('category', '-')}   주제: {analysis.get('topic', '-')}")
    print(f"    키워드: {keywords or '-'}")
    print(f"    감정: {analysis.get('sentiment', '-')}   중요도: {analysis.get('importance', '-')}/5"
          f"   난이도: {analysis.get('difficulty', '-')}")


def save_results(keyword: str, rows: list[dict]) -> Path:
    RESULT_DIR.mkdir(exist_ok=True)
    safe = re.sub(r"[^\w가-힣]+", "_", keyword).strip("_") or "news"
    path = RESULT_DIR / f"{safe}_{datetime.now():%Y%m%d_%H%M%S}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2, default=str)
    return path


# ---------------------------------------------------------------- 메인
def run(keyword: str, count: int, days: int | None, use_body: bool) -> list[dict]:
    print(f"\n'{keyword}' 뉴스 검색 중... (최근 {days}일, 최대 {count}건)" if days
          else f"\n'{keyword}' 뉴스 검색 중... (최대 {count}건)")

    articles = search_news(keyword, max_count=count, days=days)
    if not articles:
        print("검색된 기사가 없습니다.")
        return []
    print(f"{len(articles)}건 찾음. Gemini 분석을 시작합니다.\n")

    rows: list[dict] = []
    for i, article in enumerate(articles, 1):
        content = ""
        if use_body:
            original = resolve_original_link(article["link"], interval=1)
            article["original_link"] = original
            if original:
                content = fetch_article_text(original)

        if not content:
            # 본문을 못 얻으면 제목과 언론사만으로 분석 (품질은 떨어짐)
            content = f"(본문을 가져오지 못했습니다. 제목만으로 분석하세요.) 언론사: {article['source']}"

        analysis, error = None, None
        try:
            analysis = analyze_news(article["title"], content)
        except Exception as e:  # 429 등 어떤 오류든 다음 기사로 넘어간다
            error = f"{type(e).__name__}: {str(e)[:120]}"

        print_result(i, article, analysis, error)
        rows.append({**article, "content_chars": len(content), "analysis": analysis, "error": error})

        if i < len(articles):
            time.sleep(GEMINI_CALL_INTERVAL)

    return rows


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="기찾이: Google 뉴스 수집 + Gemini 분석")
    parser.add_argument("keyword", nargs="?", help="검색 키워드")
    parser.add_argument("count", nargs="?", type=int, help="분석할 기사 수 (기본 5)")
    parser.add_argument("--days", type=int, default=7, help="최근 N일 기사만 (기본 7, 0이면 제한 없음)")
    parser.add_argument("--no-body", action="store_true", help="원문 본문을 가져오지 않고 제목만으로 분석")
    parser.add_argument("--no-save", action="store_true", help="결과 JSON 저장 안 함")
    args = parser.parse_args()

    keyword = (args.keyword or input("검색할 뉴스 키워드를 입력하세요: ")).strip().lstrip("﻿")
    if not keyword:
        print("검색어를 입력해 주세요.")
        raise SystemExit(1)

    count = args.count
    if count is None:
        raw = input("분석할 기사 수를 입력하세요 (기본 5): ").strip()
        count = int(raw) if raw.isdigit() else 5
    count = max(1, min(count, 30))  # Gemini 무료 한도를 생각해 30건으로 제한

    days = args.days if args.days and args.days > 0 else None

    try:
        rows = run(keyword, count, days, use_body=not args.no_body)
    except KeyboardInterrupt:
        print("\n중단했습니다.")
        raise SystemExit(130)
    except Exception as e:
        print("실행 실패:", type(e).__name__, str(e))
        raise SystemExit(1)

    if rows:
        ok = sum(1 for r in rows if r["analysis"])
        print(f"\n===== 완료: {ok}/{len(rows)}건 분석 성공 =====")
        if not args.no_save:
            path = save_results(keyword, rows)
            print(f"결과 저장: {path}")


if __name__ == "__main__":
    main()
