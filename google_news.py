"""Google 뉴스 RSS 로 키워드 검색 기사 목록을 가져오는 모듈.

- 가입, API 키, 결제수단 모두 필요 없음
- 한국어(ko) / 한국(KR) 기준으로 검색
- 결과 항목: title, source, link, original_link, pub_date, description

사용 예:
    from google_news import search_news
    for n in search_news("인공지능", max_count=5, days=3):
        print(n["title"], n["source"], n["pub_date"])
"""

import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

RSS_SEARCH_URL = "https://news.google.com/rss/search"
KST = timezone(timedelta(hours=9))

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) gichati-news/1.0",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
_TAG_RE = re.compile(r"<[^>]+>")

# 같은 피드를 연속으로 너무 자주 치지 않도록 최소 간격(초)
_MIN_INTERVAL = 1.0
_last_request_at = 0.0


def _clean(text: str | None) -> str:
    """HTML 태그와 엔티티(&amp; 등)를 제거한다."""
    return html.unescape(_TAG_RE.sub("", text or "")).strip()


def _parse_date(value: str | None) -> datetime | None:
    """'Fri, 24 Oct 2026 04:33:37 GMT' 를 한국 시간 datetime 으로 바꾼다."""
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(KST)
    except (TypeError, ValueError):
        return None


def _strip_source_suffix(title: str, source: str) -> str:
    """Google 뉴스 제목은 '기사 제목 - 언론사' 형태라서 뒤쪽 언론사 부분을 떼어 낸다."""
    if source and title.endswith(f" - {source}"):
        return title[: -len(source) - 3].strip()
    # 언론사명이 비어 있거나 다를 때는 마지막 ' - ' 기준으로 자른다
    if " - " in title:
        head, _, tail = title.rpartition(" - ")
        if len(tail) <= 20:  # 짧은 꼬리만 언론사로 간주
            return head.strip()
    return title.strip()


def _throttle() -> None:
    global _last_request_at
    wait = _MIN_INTERVAL - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def resolve_original_link(google_link: str, interval: float = 1.0) -> str | None:
    """Google 중계 링크(news.google.com/rss/articles/...)를 언론사 원문 주소로 바꾼다.

    googlenewsdecoder 패키지를 사용하며, 링크 하나당 요청이 추가로 나가므로 느리다.
    실패하면 None 을 돌려준다.
    """
    try:
        from googlenewsdecoder import gnewsdecoder
    except ImportError:
        return None
    try:
        result = gnewsdecoder(google_link, interval=interval)
    except Exception:
        return None
    # 버전에 따라 'success' 또는 'status' 키로 성공 여부를 준다
    if isinstance(result, dict) and (result.get("success") or result.get("status")):
        return result.get("decoded_url")
    return None


def search_news(
    query: str,
    max_count: int = 10,
    days: int | None = None,
    lang: str = "ko",
    country: str = "KR",
    resolve_links: bool = False,
    timeout: float = 10.0,
) -> list[dict]:
    """Google 뉴스에서 키워드로 기사를 검색한다.

    Args:
        query:         검색어 (필수). 여러 단어도 가능 ("기후 변화 청소년")
        max_count:     최대 가져올 개수 (RSS 가 한 번에 주는 최대치는 100)
        days:          최근 N일 이내 기사만 (None 이면 제한 없음)
        lang/country:  언어/국가 코드 (기본 한국어/한국)
        resolve_links: True 면 언론사 원문 주소까지 풀어서 original_link 에 넣는다 (느림)

    Returns:
        [{"title", "source", "link", "original_link", "pub_date", "description"}, ...]
        pub_date 는 한국 시간 datetime (없으면 None)
    """
    if not query or not query.strip():
        raise ValueError("검색어(query)가 비어 있습니다.")
    if max_count < 1:
        raise ValueError("max_count 는 1 이상이어야 합니다.")

    q = query.strip()
    if days is not None:
        if days < 1:
            raise ValueError("days 는 1 이상이어야 합니다.")
        q = f"{q} when:{days}d"

    params = {
        "q": q,
        "hl": lang,
        "gl": country,
        "ceid": f"{country}:{lang}",
    }

    _throttle()
    resp = requests.get(RSS_SEARCH_URL, params=params, headers=_HEADERS, timeout=timeout)
    if resp.status_code == 429:
        raise RuntimeError("Google 뉴스 요청이 너무 잦습니다(429). 잠시 후 다시 시도해 주세요.")
    if not resp.ok:
        raise RuntimeError(f"Google 뉴스 RSS 요청 실패 ({resp.status_code})")

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        raise RuntimeError(f"RSS 파싱 실패: {e}") from e

    articles: list[dict] = []
    seen_links: set[str] = set()

    for item in root.findall("./channel/item"):
        link = (item.findtext("link") or "").strip()
        if not link or link in seen_links:
            continue
        seen_links.add(link)

        source_el = item.find("source")
        source = _clean(source_el.text if source_el is not None else "")
        raw_title = _clean(item.findtext("title"))

        article = {
            "title": _strip_source_suffix(raw_title, source),
            "source": source,
            "link": link,
            "original_link": None,
            "pub_date": _parse_date(item.findtext("pubDate")),
            "description": _clean(item.findtext("description")),
        }
        if resolve_links:
            article["original_link"] = resolve_original_link(link)

        articles.append(article)
        if len(articles) >= max_count:
            break

    return articles


def search_news_url(query: str, lang: str = "ko", country: str = "KR") -> str:
    """디버깅용: 실제로 요청하는 RSS 주소를 돌려준다."""
    params = {"q": query, "hl": lang, "gl": country, "ceid": f"{country}:{lang}"}
    return f"{RSS_SEARCH_URL}?{urllib.parse.urlencode(params)}"


if __name__ == "__main__":
    import sys

    # Windows 콘솔에서 한글이 깨지지 않도록
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    keyword = input("검색할 뉴스 키워드를 입력하세요: ").strip().lstrip("﻿")
    if not keyword:
        print("검색어를 입력해 주세요.")
        raise SystemExit(1)

    try:
        news = search_news(keyword, max_count=10, days=7)
    except Exception as e:
        print("뉴스 검색 실패:", type(e).__name__, str(e))
        raise SystemExit(1)

    print(f"\n===== '{keyword}' 최근 7일 Google 뉴스 {len(news)}건 =====")
    for i, n in enumerate(news, 1):
        date = n["pub_date"].strftime("%Y-%m-%d %H:%M") if n["pub_date"] else "-"
        print(f"\n[{i}] {n['title']}")
        print(f"    언론사: {n['source'] or '-'}   날짜: {date}")
        print(f"    링크: {n['link']}")
