# import os
# import time
# from dotenv import load_dotenv
# from google import genai
# from google.genai import errors

# load_dotenv()

# api_key = os.getenv("GEMINI_API_KEY")

# if not api_key or api_key == "여기에_API_키를_입력하세요":
#     raise ValueError(".env 파일의 GEMINI_API_KEY를 확인해 주세요.")

# client = genai.Client(api_key=api_key)
# model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
# # model = "gemini-3.5-flash-lite"

# response = client.models.generate_content(
#     model=model,
#     contents="안녕! 너는 기찾이의 AI 분석 도우미야. 한국어로 짧게 인사해 줘."
# )
# print("Gemini 응답:")
# print(response.text)

# # for attempt in range(3):
# #     try:
# #         response = client.models.generate_content(
# #             model=model,
# #             contents="안녕! 너는 기찾이의 AI 분석 도우미야. 한국어로 짧게 인사해 줘."
# #         )
# #         print("Gemini 응답:")
# #         print(response.text)
# #         break
# #     except errors.ServerError as e:
# #         print(f"서버 혼잡, 재시도 {attempt + 1}/3: {e}")
# #         time.sleep(2 ** attempt)

import os

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError(".env 파일의 GEMINI_API_KEY를 확인해 주세요.")

client = genai.Client(api_key=api_key)
model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

TOPIC = "러시아-우크라이나 전쟁의 현재 상황"

config = types.GenerateContentConfig(
    system_instruction=(
        "너는 청소년을 위한 뉴스 분석 도우미 '기찾이'야. "
        "검색 결과를 바탕으로 중학생도 이해할 수 있게 쉬운 한국어로 설명해. "
        "확인된 사실과 아직 확인되지 않은 주장은 구분해서 써. "
        "특정 편을 들지 말고, 날짜가 있는 정보는 날짜를 함께 적어."
    ),
    tools=[types.Tool(google_search=types.GoogleSearch())],  # 내장 구글 검색
    temperature=0.3,
)

prompt = f"{TOPIC}을 최신 기준으로 5문장 이내로 요약해 줘."

try:
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=config,
    )
except errors.ClientError as e:
    # 429(한도 초과)는 재시도해도 소용없으니 바로 멈춘다
    if e.code == 429:
        print("무료 한도를 초과했어요. 한도가 초기화된 뒤에 다시 시도하세요.")
    else:
        print(f"요청 실패 ({e.code}): {e}")
    raise SystemExit(1)

print("=== 답변 ===")
print(response.text)

# 검색에 쓰인 정보 확인 (모델이 검색을 안 했으면 비어 있을 수 있음)
candidate = response.candidates[0] if response.candidates else None
meta = getattr(candidate, "grounding_metadata", None)

if meta:
    queries = getattr(meta, "web_search_queries", None) or []
    print("\n=== 모델이 실제로 검색한 질의 ===")
    for q in queries:
        print("-", q)

    print("\n=== 참고한 출처 ===")
    seen = set()
    for chunk in getattr(meta, "grounding_chunks", None) or []:
        web = getattr(chunk, "web", None)
        if web and web.uri not in seen:
            seen.add(web.uri)
            print(f"- {web.title}: {web.uri}")
else:
    print("\n(검색 메타데이터 없음: 모델이 검색 없이 답했거나, 이 모델에서 검색 도구가 동작하지 않았을 수 있어요.)")