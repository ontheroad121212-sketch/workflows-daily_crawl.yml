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
print("🚀 [시스템] 엠버 AI 지배인 하이브리드 수집 엔진 가동...", flush=True)

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

# 2. 스마트 날짜 계산 함수 (지배인님 요청 로직 정밀 반영)
def get_dynamic_target_dates():
    today = datetime.now()
    target_dates = set()
    
    # [당월] 차주 및 차차주 수, 토
    # 오늘 기준으로 다음주(7일 뒤)부터 다다음주(21일 뒤)까지의 모든 수요일(2), 토요일(5) 추출
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
        
        # 2주차 수요일 계산
        weds = [w[calendar.WEDNESDAY] for w in cal if w[calendar.WEDNESDAY] != 0]
        if len(weds) >= 2: target_dates.add(f"{year}-{month:02d}-{weds[1]:02d}")
        
        # 3주차 토요일 계산
        sats = [s[calendar.SATURDAY] for s in cal if s[calendar.SATURDAY] != 0]
        if len(sats) >= 3: target_dates.add(f"{year}-{month:02d}-{sats[2]:02d}")
        
    # [공휴일] 2026년 주요 연휴 앞뒤 전수 조사 (날짜 정밀 보강)
    holidays_2026 = [
        "2026-02-13", "2026-02-16", "2026-02-21", # 설날 연휴
        "2026-03-01", # 삼일절
        "2026-05-05", # 어린이날
        "2026-05-24", # 부처님오신날
        "2026-06-06", # 현충일
        "2026-08-15", # 광복절
        "2026-09-24", "2026-09-25", "2026-09-26", # 추석 연휴
        "2026-10-03", "2026-10-09", # 개천절, 한글날
        "2026-12-25"  # 크리스마스
    ]
    
    for h in holidays_2026:
        h_date = datetime.strptime(h, "%Y-%m-%d")
        if h_date >= today:
            # 지배인님 요청: 무조건 앞뒤로 다 조사
            target_dates.add((h_date - timedelta(days=1)).strftime("%Y-%m-%d")) # 전날
            target_dates.add(h) # 당일
            target_dates.add((h_date + timedelta(days=1)).strftime("%Y-%m-%d")) # 다음날
            
    # [여름성수기] 7월말 주중1, 8월초 주말1 고정 타겟
    target_dates.add("2026-07-29")
    target_dates.add("2026-08-01")
    
    # 중복 제거 및 정렬 후 오늘 이후 날짜만 반환
    final_list = sorted([d for d in target_dates if d >= today.strftime("%Y-%m-%d")])
    print(f"📅 [지능형타겟팅] 분석 대상 날짜 (총 {len(final_list)}일): {final_list}", flush=True)
    return final_list

# 3. 개별 호텔 데이터 수집 함수 (엠버 10종 타입 무삭제 반영)
def collect_hotel_data(driver, hotel_name, hotel_id, target_date, is_precision_mode):
    print(f"   📅 {target_date} 조회 시도 중...", flush=True) 
    try:
        checkout_date = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        url = f"https://hotels.naver.com/detail/hotels/{hotel_id}/rates?checkIn={target_date}&checkOut={checkout_date}&adultCnt=2"
        
        driver.get(url)
        
        # [수정] 30초 동안 객실 목록이 나타날 때까지 끈질기게 대기
        wait = 0
        while wait < 30:
            items = driver.find_elements(By.CSS_SELECTOR, "li[class*='item'], div[class*='RateItem']")
            if len(items) > 5: # 최소 5개 이상 로딩되면 시작
                break
            time.sleep(1)
            wait += 1
            if wait % 5 == 0: print(f"      ⏳ 로딩 대기 중... ({wait}초)", flush=True)

        # [수정] 네이버 차단 회피를 위한 '사람다운' 스크롤링
        driver.execute_script("window.scrollTo(0, 500);")
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)

        print(f"      🔎 페이지 로드 확인 (객실 수: {len(items)}개), 분석 시작...", flush=True)

        if not items:
            print(f"      ⚠️ {target_date}: 객실 상자를 찾지 못했습니다. (차단 혹은 만실)", flush=True)
            return []

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
            if "원" not in text or "\n" not in text: continue
            
            html_content = item.get_attribute('innerHTML').lower()
            exclude_keywords = ["조식", "패키지", "package", "포함", "연박", "long", "stay", "라운지", "특전", "무료증정", "wine", "와인"]
            
            if any(kw in text.lower() for kw in exclude_keywords): continue

            parts = text.split("\n")
            room_name = parts[0].strip()

            # 🏨 엠버 10종 필터 (무삭제 + 포함 확인 방식으로 보강)
            if hotel_name == "엠버퓨어힐":
                amber_types = ["그린밸리 디럭스 더블", "그린밸리 디럭스 패밀리", "포레스트 가든 더블", "포레스트 가든 더블 eb", "포레스트 플로라 더블", "포레스트 펫 더블", "힐 파인 더블", "힐 엠버 트윈", "힐 루나 패밀리", "프라이빗 풀빌라"]
                    
            # [수정] 공백을 없애고 '포함'되어 있는지 검사 (가장 확실함)
            clean_room_name = room_name.replace(" ", "")
            match_found = False
            for target in amber_types:
                if target.replace(" ", "") in clean_room_name:
                    match_found = True
                    break
                    
            if not match_found:
                # 지배인님, 필터에 안 걸려서 버려지는 방이 뭔지 로그로 찍어볼게요.
                # print(f"(필터제외): {room_name}") 
                continue

            if hotel_name == "엠버퓨어힐":
                amber_types = ["그린밸리 디럭스 더블", "그린밸리 디럭스 패밀리", "포레스트 가든 더블", "포레스트 가든 더블 eb", "포레스트 플로라 더블", "포레스트 펫 더블", "힐 파인 더블", "힐 엠버 트윈", "힐 루나 패밀리", "프라이빗 풀빌라"]
                if not any(kw in room_name for kw in amber_types):
                    continue
            
            found_channel = "플랫폼원본"
            for channel, keywords in target_map.items():
                if any(key in html_content for key in keywords):
                    found_channel = channel
                    break 

            if room_name not in collected_rooms_channels:
                collected_rooms_channels[room_name] = []
            
            if found_channel not in collected_rooms_channels[room_name]:
                # 포인트 금액 방지 (가장 큰 금액만 추출)
                prices = [int(re.sub(r'[^0-9]', '', p)) for p in parts if "원" in p and re.sub(r'[^0-9]', '', p)]
                if not prices: continue
                
                real_price = max(prices)
                
                if real_price > 100000:
                    rows.append([now, hotel_name, room_name, found_channel, real_price, target_date])
                    collected_rooms_channels[room_name].append(found_channel)
                    print(f"    🔎 [{found_channel}] {room_name}: {real_price:,}원", flush=True)
        
        return rows
    except Exception as e:
        print(f"❌ {hotel_name} 수집 오류: {e}", flush=True)
        return []
        
# 4. 메인 실행 함수 (격주 로직 포함)
def main():
    # VIP 호텔 리스트 (매일 무조건 전수 조사)
    vip_hotels = ["엠버퓨어힐", "파르나스", "그랜드조선제주", "그랜드하얏트", "신라호텔", "롯데호텔"]
    
    hotels = {
        "엠버퓨어힐": "N5302461", "그랜드하얏트": "N5281539", "파르나스": "N5287649",
        "신라호텔": "N1496601", "롯데호텔": "N1053569", "그랜드조선제주": "N5279751",
        "신라스테이": "N5305249", "해비치": "N1053576", "신화메리어트": "N3610024", 
        "히든클리프": "N2982178", "더시에나": "N2662081", "조선힐스위트": "KYK10391783", "메종글래드": "N1053566"
    }

    # 2주에 한 번(짝수 주) 월요일 판별
    today = datetime.now()
    is_monday = today.weekday() == 0
    is_even_week = (today.isocalendar()[1]) % 2 == 0
    is_full_scan_day = is_monday and is_even_week

    print("\n" + "="*50, flush=True)
    print(f"🏨 엠버 AI 지배인 하이브리드 엔진 v3.1 (정밀대상: {len(vip_hotels)}개)", flush=True)
    if is_full_scan_day:
        print("📢 오늘은 [격주 정기 점검일]입니다. 모든 호텔을 정밀 스캔합니다!", flush=True)
    
    test_dates = get_dynamic_target_dates()
    
    # [엔진 설정] 네이버 차단 회피용 정밀 세팅
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    # 언어 설정을 한국어로 고정해서 의심을 피합니다
    options.add_argument("--lang=ko_KR")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    # 자동화 제어 신호를 아예 삭제합니다
    options.add_argument("--disable-blink-features=AutomationControlled") 
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    # [핵심] 지배인님, 이 줄이 꼭 있어야 합니다! (로봇 아니라고 거짓말하는 코드)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    try:
        for hotel_name, hotel_id in hotels.items():
            is_precision = (hotel_name in vip_hotels) or is_full_scan_day
            mode_tag = "💎 [정밀]" if is_precision else "⚡ [쾌속]"
            
            print(f"\n{mode_tag} {hotel_name} 분석 시작...", flush=True)
            
            # [최적화] 호텔 단위가 아니라 날짜 단위로 실시간 저장하도록 루프 수정
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







