import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
from datetime import datetime, timedelta
import sys
import calendar

# [로그 출력]
print("🚀 [시스템] 엠버 AI 지배인 지능형 날짜 엔진 가동...", flush=True)

# 1. 구글 시트 저장 함수 (원본 유지)
def save_to_google_sheet(all_data):
    if not all_data: return
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name('key.json', scope)
        client = gspread.authorize(creds)
        sheet = client.open("Amber_Price_DB").sheet1 
        sheet.append_rows(all_data)
        print(f"✅ 구글 시트 데이터 저장 완료! ({len(all_data)}행)", flush=True)
    except Exception as e:
        print(f"🚨 저장 에러: {e}", flush=True)

# 2. [업데이트] 스마트 날짜 계산 함수
def get_dynamic_target_dates():
    today = datetime.now()
    target_dates = set()

    # --- 1. 당월: 차주 및 차차주 수요일, 토요일 ---
    # 오늘로부터 7일 뒤(차주)부터 21일 뒤 사이의 수, 토 추출
    for i in range(7, 21):
        future_date = today + timedelta(days=i)
        if future_date.weekday() == 2: # 수요일
            target_dates.add(future_date.strftime("%Y-%m-%d"))
        if future_date.weekday() == 5: # 토요일
            target_dates.add(future_date.strftime("%Y-%m-%d"))

    # --- 2. 익월부터 +3개월: 2주차 수요일, 3주차 토요일 ---
    current_month = today.month
    current_year = today.year
    
    for i in range(1, 4):
        month = (current_month + i - 1) % 12 + 1
        year = current_year + (current_month + i - 1) // 12
        
        cal = calendar.monthcalendar(year, month)
        
        # 2주차 수요일 (2번째 리스트의 index 2) - 첫주가 수요일을 포함하지 않을 경우 대응
        wednesdays = [w[calendar.WEDNESDAY] for w in cal if w[calendar.WEDNESDAY] != 0]
        if len(wednesdays) >= 2:
            target_dates.add(f"{year}-{month:02d}-{wednesdays[1]:02d}")
            
        # 3주차 토요일 (3번째 리스트의 index 5)
        saturdays = [s[calendar.SATURDAY] for s in cal if s[calendar.SATURDAY] != 0]
        if len(saturdays) >= 3:
            target_dates.add(f"{year}-{month:02d}-{saturdays[2]:02d}")

    # --- 3. 한국 주요 공휴일 및 연휴 (앞뒤 조사) ---
    # 2026년 주요 공휴일 리스트 (지배인님 요청: 무조건 앞뒤 조사)
    holidays_2026 = [
        "2026-02-14", "2026-02-16", "2026-02-20", # 설날 연휴
        "2026-03-01", # 삼일절
        "2026-05-05", # 어린이날
        "2026-05-24", # 부처님오신날
        "2026-06-06", # 현충일
        "2026-08-15", # 광복절
        "2026-09-24", "2026-09-25", "2026-09-26", # 추석 연휴
        "2026-10-03", "2026-10-09", # 개천절, 한글날
        "2026-12-24"  # 크리스마스
    ]
    
    for h in holidays_2026:
        h_date = datetime.strptime(h, "%Y-%m-%d")
        if h_date >= today:
            target_dates.add((h_date - timedelta(days=1)).strftime("%Y-%m-%d")) # 전날
            target_dates.add(h) # 당일
            target_dates.add((h_date + timedelta(days=1)).strftime("%Y-%m-%d")) # 다음날

    # --- 4. 7월말~8월초 극성수기 (주중 1일, 주말 1일) ---
    target_dates.add("2026-07-29") # 7월 마지막 수요일(주중)
    target_dates.add("2026-08-01") # 8월 첫 토요일(주말)

    final_list = sorted([d for d in target_dates if d >= today.strftime("%Y-%m-%d")])
    print(f"📅 [지능형타겟팅] 분석 대상 날짜 (총 {len(final_list)}일): {final_list}", flush=True)
    return final_list

# 3. 개별 호텔 데이터 수집 함수 (원본 로직 100% 유지)
def collect_hotel_data(driver, hotel_name, hotel_id, target_date):
    try:
        date_obj = datetime.strptime(target_date, "%Y-%m-%d")
        checkout_date = (date_obj + timedelta(days=1)).strftime("%Y-%m-%d")
        url = f"https://hotels.naver.com/detail/hotels/{hotel_id}/rates?checkIn={target_date}&checkOut={checkout_date}&adultCnt=2"
        
        driver.get(url)
        time.sleep(12) 
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
        
        items = driver.find_elements(By.TAG_NAME, "li")
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
            text = item.text.strip()
            html_content = item.get_attribute('innerHTML').lower()
            
            exclude_keywords = ["조식", "패키지", "package", "포함", "연박", "long", "stay", "라운지", "특전", "무료증정", "wine", "와인"]
            
            if "원" in text and "\n" in text:
                if any(kw in text.lower() for kw in exclude_keywords):
                    continue

                parts = text.split("\n")
                room_name = parts[0].strip()

                if hotel_name == "엠버퓨어힐":
                    target_keywords = ["그린밸리 디럭스 더블", "힐 엠버 트윈", "힐 파인 더블"]
                    if not any(kw in room_name for kw in target_keywords):
                        continue
                
                found_channel = None
                priority_order = ["아고다", "트립닷컴", "트립비토즈", "부킹닷컴", "야놀자", "여기어때", "익스피디아", "호텔스닷컴", "시크릿몰", "호텔패스", "네이버"]
                for channel in priority_order:
                    keywords = target_map.get(channel, [])
                    if any(key in html_content for key in keywords):
                        found_channel = channel
                        break 
                
                if not found_channel: found_channel = "플랫폼원본"

                if room_name not in collected_rooms_channels:
                    collected_rooms_channels[room_name] = []
                
                if found_channel not in collected_rooms_channels[room_name]:
                    price_val = 0
                    for p in parts:
                        if "원" in p:
                            num = re.sub(r'[^0-9]', '', p)
                            if num and int(num) > 100000:
                                price_val = int(num)
                                break
                    
                    if price_val > 100000:
                        rows.append([now, hotel_name, room_name, found_channel, price_val, target_date])
                        collected_rooms_channels[room_name].append(found_channel)
                        print(f"    🔎 [기본상품확보] {room_name} | {found_channel}: {price_val:,}원", flush=True)
        
        return rows
    except Exception as e:
        print(f"❌ {hotel_name} 수집 오류: {e}", flush=True)
        return []

# 4. 메인 실행 함수 (원본 유지)
def main():
    hotels = {
        "엠버퓨어힐": "N5302461", "그랜드하얏트": "N5281539", "파르나스": "N5287649",
        "신라호텔": "N1496601", "롯데호텔": "N1053569", "신라스테이": "N5305249",
        "해비치": "N1053576", "신화메리어트": "N3610024", "히든클리프": "N2982178",
        "더시에나": "N2662081", "조선힐스위트": "KYK10391783", "메종글래드": "N1053566",
        "그랜드조선제주": "N5279751"
    }

    print("\n" + "="*50, flush=True)
    print("🏨 엠버 AI 지배인 전수 수집 엔진 v2.8 (지능형 날짜 타겟팅)", flush=True)
    
    # [업데이트] 박제된 날짜 대신 동적 계산 함수 호출
    test_dates = get_dynamic_target_dates()
    
    options = Options()
    options.add_argument("--headless")  
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    try:
        for hotel_name, hotel_id in hotels.items():
            print(f"\n🏨 {hotel_name} (ID: {hotel_id}) 분석 시작...", flush=True)
            hotel_total_data = []
            for date in test_dates:
                print(f"    📅 {date} 수집 중...", flush=True)
                data = collect_hotel_data(driver, hotel_name, hotel_id, date)
                hotel_total_data.extend(data)
            
            if hotel_total_data:
                save_to_google_sheet(hotel_total_data)
                print(f"✨ {hotel_name} 전송 완료!", flush=True)

    except Exception as e:
        print(f"🚨 메인 루프 실행 에러: {e}", flush=True)

    finally:
        driver.quit()
        print("\n🏁 지능형 자동 수집 및 저장이 완료되었습니다!", flush=True)

if __name__ == "__main__":
    main()
