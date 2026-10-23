# import requests

# URL = "https://news.google.com/rss/articles/CBMicEFVX3lxTE5Dam5GQXFDbTJsaWVvZVNOWDhDVGk1THlKQUkyUmNwenZWZTNfSTVUdFVIZkNZdFlnUUh5VDBfR0dDQzZpV1Jmd1ZLSmwtSVlWZ081ZG51NERDLWJXX1ZLSHFETWFUT1QxVFM1allUdkw?oc=5"
# r = requests.get(URL, allow_redirects=True, timeout=10,
#                  headers={"User-Agent": "Mozilla/5.0"})
# print(r.status_code)
# print(r.url)   # 최종 도착 주소

from googlenewsdecoder import gnewsdecoder

url = "https://news.google.com/rss/articles/CBMicEFVX3lxTE5Dam5GQXFDbTJsaWVvZVNOWDhDVGk1THlKQUkyUmNwenZWZTNfSTVUdFVIZkNZdFlnUUh5VDBfR0dDQzZpV1Jmd1ZLSmwtSVlWZ081ZG51NERDLWJXX1ZLSHFETWFUT1QxVFM1allUdkw?oc=5"   # 아까 그 구글 링크 (?oc=5까지 그대로)

result = gnewsdecoder(url, interval=5)   # interval은 요청 사이 대기 시간(초)
print(result)