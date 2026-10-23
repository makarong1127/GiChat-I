"""기찾이 FastAPI 백엔드.

실행:
    .\\.venv\\Scripts\\python.exe -m uvicorn app:app --port 8000 --reload
    → http://localhost:8000  (frontend/ 의 HTML 을 그대로 서빙)

API:
    GET /api/news/search?q=검색어&days=7&count=30   기사 목록 (Google 뉴스)
    GET /api/articles/{id}                          기사 상세 + Gemini 분석 (결과는 SQLite 에 캐시)
    GET    /api/saved                               저장한 기사 목록 (익명 쿠키 기준)
    GET    /api/saved/ids                           저장한 기사 ID 목록 (버튼 상태 표시용)
    POST   /api/saved/{id}                          저장
    DELETE /api/saved/{id}                          저장 취소

사용자 식별:
    로그인이 없으므로 서버가 처음 방문 때 'gichati_guest' 쿠키(랜덤 ID)를 발급하고,
    저장 데이터는 그 ID 에 묶인다. 나중에 로그인이 생기면 이 ID 의 데이터를 계정으로 옮기면 된다.
"""

import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from article_text import fetch_article_text
from google_news import resolve_original_link, search_news
from news_analyzer import analyze_news

BASE_DIR = Path(__file__).parent
FRONTEND_DIR = BASE_DIR / "frontend"
DB_PATH = BASE_DIR / "gichati.db"

app = FastAPI(title="기찾이 API", version="0.2.0")

GUEST_COOKIE = "gichati_guest"
GUEST_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1년

# 같은 기사를 동시에 두 번 분석하지 않도록 기사별 잠금
_analysis_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


# ---------------------------------------------------------------- 익명 사용자 쿠키
@app.middleware("http")
async def guest_cookie_middleware(request: Request, call_next):
    guest_id = request.cookies.get(GUEST_COOKIE, "")
    is_new = not (guest_id.isalnum() and len(guest_id) == 32)
    if is_new:
        guest_id = uuid.uuid4().hex
    request.state.guest_id = guest_id

    response = await call_next(request)
    if is_new:
        response.set_cookie(
            GUEST_COOKIE, guest_id, max_age=GUEST_COOKIE_MAX_AGE, httponly=True, samesite="lax"
        )
    return response


# ---------------------------------------------------------------- DB
def _init_db() -> None:
    with _db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id            TEXT PRIMARY KEY,
                title         TEXT NOT NULL,
                source        TEXT,
                link          TEXT NOT NULL,
                original_link TEXT,
                pub_date      TEXT,
                content       TEXT,
                analysis      TEXT,
                error         TEXT,
                created_at    TEXT NOT NULL,
                analyzed_at   TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved (
                guest_id   TEXT NOT NULL,
                article_id TEXT NOT NULL,
                saved_at   TEXT NOT NULL,
                PRIMARY KEY (guest_id, article_id)
            )
            """
        )


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _article_id(link: str) -> str:
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]


def _lock_for(article_id: str) -> threading.Lock:
    with _locks_guard:
        return _analysis_locks.setdefault(article_id, threading.Lock())


def _row_to_public(row: sqlite3.Row) -> dict:
    analysis = json.loads(row["analysis"]) if row["analysis"] else None
    content = row["content"] or ""
    return {
        "id": row["id"],
        "title": row["title"],
        "source": row["source"],
        "link": row["link"],
        "original_link": row["original_link"],
        "pub_date": row["pub_date"],
        "paragraphs": [p for p in content.split("\n") if p.strip()],
        "analysis": analysis,
        "error": row["error"],
        "analyzed_at": row["analyzed_at"],
    }


# ---------------------------------------------------------------- API
@app.get("/api/news/search")
def api_search(
    q: str = Query(..., min_length=1, description="검색어"),
    days: int = Query(7, ge=0, le=365, description="최근 N일 (0이면 제한 없음)"),
    count: int = Query(30, ge=1, le=100),
):
    try:
        articles = search_news(q, max_count=count, days=days or None)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"뉴스 검색 실패: {e}") from e

    now = datetime.now().isoformat(timespec="seconds")
    items = []
    with _db() as conn:
        for a in articles:
            aid = _article_id(a["link"])
            pub = a["pub_date"].isoformat() if a["pub_date"] else None
            # 목록에서 본 기사는 상세 페이지에서 찾을 수 있도록 저장 (분석 결과는 건드리지 않음)
            conn.execute(
                """
                INSERT INTO articles (id, title, source, link, pub_date, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    source = excluded.source,
                    pub_date = COALESCE(excluded.pub_date, articles.pub_date)
                """,
                (aid, a["title"], a["source"], a["link"], pub, now),
            )
            items.append(
                {"id": aid, "title": a["title"], "source": a["source"], "link": a["link"], "pub_date": pub}
            )

    return {"query": q, "days": days, "count": len(items), "items": items}


@app.get("/api/articles/{article_id}")
def api_article(article_id: str, refresh: bool = False):
    with _db() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="기사를 찾을 수 없습니다. 검색 결과에서 다시 들어와 주세요.")

    if row["analysis"] and not refresh:
        return _row_to_public(row)

    with _lock_for(article_id):
        # 잠금을 기다리는 동안 다른 요청이 끝냈을 수 있으니 다시 확인
        with _db() as conn:
            row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if row["analysis"] and not refresh:
            return _row_to_public(row)

        original = row["original_link"] or resolve_original_link(row["link"], interval=1)
        content = row["content"] or (fetch_article_text(original) if original else "")

        analysis, error = None, None
        try:
            prompt_content = content or f"(본문을 가져오지 못했습니다. 제목만으로 분석하세요.) 언론사: {row['source']}"
            analysis = analyze_news(row["title"], prompt_content)
        except Exception as e:
            error = f"{type(e).__name__}: {str(e)[:200]}"

        with _db() as conn:
            conn.execute(
                """
                UPDATE articles
                SET original_link = ?, content = ?, analysis = ?, error = ?, analyzed_at = ?
                WHERE id = ?
                """,
                (
                    original,
                    content,
                    json.dumps(analysis, ensure_ascii=False) if analysis else None,
                    error,
                    datetime.now().isoformat(timespec="seconds") if analysis else None,
                    article_id,
                ),
            )
            row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()

    return _row_to_public(row)


@app.get("/api/saved")
def api_saved_list(request: Request):
    """저장한 기사 목록. 분석이 끝난 기사는 분야(category)와 요약 첫 줄도 함께 준다."""
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.title, a.source, a.link, a.original_link, a.pub_date, a.analysis, s.saved_at
            FROM saved s JOIN articles a ON a.id = s.article_id
            WHERE s.guest_id = ?
            ORDER BY s.saved_at DESC
            """,
            (request.state.guest_id,),
        ).fetchall()

    items = []
    for r in rows:
        analysis = json.loads(r["analysis"]) if r["analysis"] else None
        summary = (analysis or {}).get("summary") or []
        items.append(
            {
                "id": r["id"],
                "title": r["title"],
                "source": r["source"],
                "link": r["link"],
                "original_link": r["original_link"],
                "pub_date": r["pub_date"],
                "saved_at": r["saved_at"],
                "category": (analysis or {}).get("category"),
                "importance": (analysis or {}).get("importance"),
                "summary_first": summary[0] if isinstance(summary, list) and summary else None,
            }
        )
    return {"count": len(items), "items": items}


@app.get("/api/saved/ids")
def api_saved_ids(request: Request):
    with _db() as conn:
        rows = conn.execute(
            "SELECT article_id FROM saved WHERE guest_id = ?", (request.state.guest_id,)
        ).fetchall()
    return {"ids": [r["article_id"] for r in rows]}


@app.post("/api/saved/{article_id}")
def api_save(article_id: str, request: Request):
    with _db() as conn:
        exists = conn.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="기사를 찾을 수 없습니다.")
        conn.execute(
            "INSERT OR IGNORE INTO saved (guest_id, article_id, saved_at) VALUES (?, ?, ?)",
            (request.state.guest_id, article_id, datetime.now().isoformat(timespec="seconds")),
        )
    return {"saved": True, "id": article_id}


@app.delete("/api/saved/{article_id}")
def api_unsave(article_id: str, request: Request):
    with _db() as conn:
        conn.execute(
            "DELETE FROM saved WHERE guest_id = ? AND article_id = ?",
            (request.state.guest_id, article_id),
        )
    return {"saved": False, "id": article_id}


@app.get("/api/health")
def api_health():
    return {"ok": True}


# ---------------------------------------------------------------- 정적 프론트
@app.get("/", include_in_schema=False)
def root():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

_init_db()
