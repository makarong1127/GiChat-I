
import os
import json
from dotenv import load_dotenv
from google import genai

load_dotenv(override=True)

api_key = os.getenv("GEMINI_API_KEY", "").strip()
model_name = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")

if not api_key:
    raise ValueError(".env 파일에서 GEMINI_API_KEY를 찾을 수 없습니다.")

client = genai.Client(api_key=api_key)


def analyze_news(title: str, content: str) -> dict:
    """뉴스 제목과 본문을 AI로 분석한다."""

    prompt = f"""
너는 한국어 뉴스 분석 도우미야.
아래 뉴스의 제목과 본문을 읽고 분석해 줘.

[뉴스 제목]
{title}

[뉴스 본문]
{content}

다음 항목을 JSON 형식으로 작성해.
- summary: 핵심 내용을 중학생도 이해할 수 있는 쉬운 문장 3개로 요약한 배열 (각 문장은 60자 이내)
- topic: 뉴스의 주요 주제 (한 구절)
- category: 다음 중 하나로 분류 - "정치·정책", "경제", "사회", "과학·IT", "교육·진로", "문화·생활", "세계"
- keywords: 핵심 키워드 3개 (배열)
- sentiment: positive, neutral, negative 중 하나
- importance: 1부터 5까지의 중요도 (정수)
- difficulty: 중학생 기준 읽기 난이도. "하", "중", "상" 중 하나

반드시 JSON 객체만 출력해. 마크다운 코드 블록은 사용하지 마.
"""

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config={
            "response_mime_type": "application/json"
        }
    )

    result = json.loads(response.text)

    # 모델이 summary 를 문자열 하나로 줄 때를 대비해 항상 리스트로 맞춘다
    summary = result.get("summary")
    if isinstance(summary, str):
        result["summary"] = [s.strip() for s in summary.replace("\n", " ").split(". ") if s.strip()][:3]
    elif not isinstance(summary, list):
        result["summary"] = []

    return result


if __name__ == "__main__":
    title = input("뉴스 제목을 입력하세요: ").strip()
    content = input("뉴스 본문을 입력하세요: ").strip()

    if not title or not content:
        print("뉴스 제목과 본문을 모두 입력해 주세요.")
    else:
        try:
            result = analyze_news(title, content)
            print("\n===== 기찾이 AI 뉴스 분석 결과 =====")
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            print("뉴스 분석 실패:", type(e).__name__, str(e))
