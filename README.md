name: 엠버 일일 요금 자동 수집

on:
  schedule:
    - cron: '21 22 * * *' # 한국 시간 기준 매일 오전 7시 21분 실행 (UTC 22:21)
  workflow_dispatch: # 필요할 때 수동으로도 실행 가능

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: 코드 체크아웃
        uses: actions/checkout@v3

      - name: 파이썬 환경 설정
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'

      - name: 필수 라이브러리 설치
        run: |
          pip install pandas gspread oauth2client selenium webdriver-manager

      - name: 수집기 실행
        run: python scraper.py  # Collector.py
