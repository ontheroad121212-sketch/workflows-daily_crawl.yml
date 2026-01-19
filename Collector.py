import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
from datetime import datetime, timedelta
import sys
import calendar
import os
import json

# [로그 출력]
print("🚀 [시스템] 엠버 AI 지배인 하이브리드 수집 엔진 가동...", flush=True)

# 1. 구글 시트 저장 함수 (보안 통과 버전)
def save_to_google_sheet(all_data):
    if not all_data: return
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        
        # 깃허브 Secrets에서 키를 가져옵니다
        key_json = os.environ.get("GCP_SA_KEY")
        if not key_json:
            print("🚨 저장 에러: 깃허브 Secrets에 GCP_SA_KEY가 없습니다.", flush=True)
            return

        key_dict = json.loads(key_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Amber_Price_DB").sheet1 
        sheet.append_rows(all_data)
        print(f"✅ 구글 시트 데이터 저장 완료! ({len(all_data)}행)", flush=True)
    except Exception as e:
        print(f"🚨 저장 에러: {e}", flush=True)

# 2. 스마트 날짜 계산 함수 (지배인님 요청 로직 정밀 반영)
def get_dynamic_target_dates():
    today = datetime.now()
    target_dates = set()
    
    # [당월] 차주 및 차차주 수, 토
    for i in range(7, 22):
        future_date = today + timedelta(days=i)
        if future_date.weekday() in [2, 5]: 
            target_dates.add(future_date.strftime("%Y-%m-%d"))
            
    # [익월~+3개월] 매월 2주 수, 3주 토
    current_month, current_year = today.month, today.year
    for i in range(1, 4):
        month = (current_month + i - 1) % 12 + 1
        year = current_year + (current_month + i - 1) // 12
        cal = calendar.monthcalendar(year, month)
        
        weds = [w[calendar.WEDNESDAY] for w in cal if w[calendar.WEDNESDAY] != 0]
        if len(weds) >= 2: target_dates.add(f"{year}-{month:02d}-{weds[1]:02d}")
        
        sats = [s[calendar.SATURDAY] for s in cal if s[calendar.SATURDAY] != 0]
        if len(sats) >= 3: target_dates.add(f"{year}-{month:02d}-{sats[2]:02d}")
        
    # [공휴일] 2026년 주요 연휴 앞뒤 전수 조사
    holidays_2026 = [
        "2026-02-13", "2026-02-16", "2026-02-21", "2026-03-01", "2026-05-05", 
        "2026-05-24", "2026-06-06", "2026-08-15", "2026-09-24", "2026-09-25", 
        "2026-09-26", "2026-10-03", "2026-10-09", "2026-12-25"
    ]
    
    for h in holidays_2026:
        h_date = datetime.strptime(h, "%Y-%m-%d")
        if h_date >= today:
            target_dates.add((h_date - timedelta(days=1)).strftime("%Y-%m-%d"))
            target_dates.add(h)
            target_dates.add((h_date + timedelta(days=1)).strftime("%Y-%m-%d"))
            
    target_dates.add("2026-07-29")
    target_dates.add("2026-08-01")
    
    final_list = sorted([d for d in target_dates if d >= today.strftime("%Y-%m-%d")])
    print(f"📅 [지능형타겟팅] 분석 대상 날짜 (총 {len(final_list)}일): {final_list}", flush=True)
    return final_list

# 3. 개별 호텔 데이터 수집 함수 (드디어 해결된 정답 버전)
def collect_hotel_data(driver, hotel_name, hotel_id, target_date, is_precision_mode):
    print(f"    📅 {target_date} 조회 시도 중...", flush=True) 
    try:
        checkout_date = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        url = f"https://hotels.naver.com/detail/hotels/{hotel_id}/rates?checkIn={target_date}&checkOut={checkout_date}&adultCnt=2"
        
        driver.get(url)
        
        # [핵심] '원'이라는 글자가 뜰 때까지 기다립니다 (주소/전화번호 로딩 말고 진짜 가격 로딩)
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '원')]"))
            )
        except:
            print(f"      ⚠️ {target_date}: 가격 정보가 로딩되지 않았습니다. (만실 또는 차단)", flush=True)
            return []

        # 스크롤을 충분히 내려서 객실 리스트를 활성화
        driver.execute_script("window.scrollTo(0, 800);")
        time.sleep(1)
        driver.execute_script("window.scrollTo(0, 1500);")
        time.sleep(2)

        # 🚀 [수정된 선택자] 아무 'li'나 잡지 말고, 내부에 '원'이라는 글자가 있는 'li'만 잡습니다.
        # 이렇게 하면 주소, 전화번호, 평점 같은 쓸데없는 정보는 자동으로 걸러집니다.
        items = driver.find_elements(By.XPATH, "//li[descendant::*[contains(text(), '원')]]")

        print(f"      🔎 진짜 객실 상자 {len(items)}개 포착! 분석 시작...", flush=True)

        rows = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        target_map = {
            "아고다": ["agoda", "아고다"], "트립닷컴": ["trip.com", "트립닷컴", "tripcom"],
            "트립비토즈": ["tripbtoz", "트립비토즈"], "부킹닷컴": ["booking.com", "부킹닷컴"],
            "야놀자": ["yanolja", "야놀자"], "여기어때": ["goodchoice", "여기어때"],
            "익스피디아": ["expedia", "익스피디아"], "호텔스닷컴": ["hotels.com", "호텔스닷컴"],
            "시크릿몰": ["secretmall", "시크릿몰"], "호텔패스": ["hotelpass", "호텔패스"],
            "네이버": ["naver", "네이버", "npay"]
        }
        
        collected_rooms_channels = {} 

        for item in items:
            # 텍스트 추출
            raw_text = driver.execute_script("return arguments[0].innerText;", item).strip()
            
            # 더블 체크: 진짜 가격 정보가 맞는지
            if "원" not in raw_text: continue
            
            parts = [p.strip() for p in raw_text.split("\n") if p.strip()]
            if not parts: continue
            
            room_name = parts[0]
            html_content = item.get_attribute('innerHTML').lower()
            
            if any(kw in raw_text.lower() for kw in ["조식", "패키지", "라운지", "와인"]): continue

            # [엠버 필터] 공백 무시하고 포함 여부 확인
            if hotel_name == "엠버퓨어힐":
                amber_types = ["그린밸리", "포레스트", "힐", "풀빌라"] # 핵심 키워드로 더 단순화
                clean_rn = room_name.replace(" ", "")
                if not any(kw in clean_rn for kw in amber_types):
                    # print(f"      ❌ 필터 제외: {room_name}", flush=True) # 디버깅용
                    continue

            # 쾌속 모드 중복 방지
            if not is_precision_mode and len(collected_rooms_channels) >= 1 and room_name not in collected_rooms_channels:
                break
            
            found_channel = "플랫폼원본"
            priority_order = ["아고다", "트립닷컴", "트립비토즈", "부킹닷컴", "야놀자", "여기어때", "익스피디아", "호텔스닷컴", "시크릿몰", "호텔패스", "네이버"]
            for channel in priority_order:
                keywords = target_map.get(channel, [])
                if any(key in html_content for key in keywords):
                    found_channel = channel; break 

            if room_name not in collected_rooms_channels:
                collected_rooms_channels[room_name] = []
            
            if found_channel not in collected_rooms_channels[room_name]:
                prices = [int(re.sub(r'[^0-9]', '', p)) for p in parts if "원" in p and re.sub(r'[^0-9]', '', p)]
                if not prices: continue
                real_price = max(prices)
                
                if real_price > 100000:
                    rows.append([now, hotel_name, room_name, found_channel, real_price, target_date])
                    collected_rooms_channels[room_name].append(found_channel)
                    print(f"    🔎 [{found_channel}] {room_name}: {real_price:,}원", flush=True)
        
        return rows
    except Exception as e:
        print(f"❌ {hotel_name} 수집 오류: {e}", flush=True); return []
# 4. 메인 실행 함수 (지배인님의 격주 점검 로직 포함 무삭제)
def main():
    vip_hotels = ["엠버퓨어힐", "파르나스", "그랜드조선제주", "그랜드하얏트", "신라호텔", "롯데호텔"]
    hotels = {
        "엠버퓨어힐": "N5302461", "그랜드하얏트": "N5281539", "파르나스": "N5287649",
        "신라호텔": "N1496601", "롯데호텔": "N1053569", "그랜드조선제주": "N5279751",
        "신라스테이": "N5305249", "해비치": "N1053576", "신화메리어트": "N3610024", 
        "히든클리프": "N2982178", "더시에나": "N2662081", "조선힐스위트": "KYK10391783", "메종글래드": "N1053566"
    }

    today = datetime.now()
    is_monday = today.weekday() == 0
    is_even_week = (today.isocalendar()[1]) % 2 == 0
    is_full_scan_day = is_monday and is_even_week

    print("\n" + "="*50, flush=True)
    print(f"🏨 엠버 AI 지배인 하이브리드 엔진 v3.1 (정밀대상: {len(vip_hotels)}개)", flush=True)
    if is_full_scan_day:
        print("📢 오늘은 [격주 정기 점검일]입니다. 모든 호텔을 정밀 스캔합니다!", flush=True)
    
    test_dates = get_dynamic_target_dates()
    
    options = Options()
    options.add_argument("--headless=new"); options.add_argument("--no-sandbox"); options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080"); options.add_argument("--lang=ko_KR")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("--disable-blink-features=AutomationControlled") 
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    try:
        for hotel_name, hotel_id in hotels.items():
            is_precision = (hotel_name in vip_hotels) or is_full_scan_day
            mode_tag = "💎 [정밀]" if is_precision else "⚡ [쾌속]"
            print(f"\n{mode_tag} {hotel_name} 분석 시작...", flush=True)
            for date in test_dates:
                data = collect_hotel_data(driver, hotel_name, hotel_id, date, is_precision)
                if data:
                    save_to_google_sheet(data)
                    print(f"📍 {date} 데이터 실시간 시트 전송 완료", flush=True)
    except Exception as e:
        print(f"🚨 메인 루프 실행 에러: {e}", flush=True)
    finally:
        driver.quit()
        print("\n🏁 모든 수집 및 저장이 완료되었습니다!", flush=True)

if __name__ == "__main__":
    main()


