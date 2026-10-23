"""언론사 기사 페이지에서 본문 텍스트를 뽑아 내는 모듈."""

import re

import requests
from selectolax.lexbor import LexborHTMLParser as HTMLParser

MAX_BODY_CHARS = 3000

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) gichati-news/1.0",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
_WS_RE = re.compile(r"\s+")

# 흔한 본문 컨테이너를 구체적인 것부터 순서대로 시도한다
_CANDIDATE_SELECTORS = (
    "article p",
    "#articleBody p, #articeBody p, #article-body p, #newsct_article p",
    ".article_body p, .article-body p, .news_body p, .article_txt p, #dic_area p",
    "p",
)


def fetch_article_text(url: str, timeout: float = 10.0, max_chars: int = MAX_BODY_CHARS) -> str:
    """기사 본문 텍스트를 돌려준다. 실패하면 빈 문자열."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return ""

    # 인코딩이 잘못 잡히는 사이트가 있어 apparent_encoding 으로 보정
    if resp.encoding is None or resp.encoding.lower() in ("iso-8859-1", "ascii"):
        resp.encoding = resp.apparent_encoding

    tree = HTMLParser(resp.text)
    for tag in tree.css("script, style, noscript, nav, header, footer, aside, iframe, figure"):
        tag.decompose()

    for selector in _CANDIDATE_SELECTORS:
        paragraphs = [_WS_RE.sub(" ", p.text(strip=True)) for p in tree.css(selector)]
        paragraphs = [p for p in paragraphs if len(p) >= 30]
        text = "\n".join(paragraphs)
        if len(text) >= 300:
            return text[:max_chars]

    # 문단을 못 찾으면 메타 설명이라도 사용
    for selector in ('meta[property="og:description"]', 'meta[name="description"]'):
        node = tree.css_first(selector)
        if node and node.attributes.get("content"):
            return node.attributes["content"].strip()[:max_chars]

    return ""
