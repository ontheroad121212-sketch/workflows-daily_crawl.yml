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

# 1. 구글 시트 저장 함수 (원본 유지)
def save_to_google_sheet(all_data):
    if not all_data: return
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name('key.json', scope)
        client = gspread.authorize(creds)
        sheet = client.open("Amber_Price_DB").sheet1 
        sheet.append_rows(all_data)
        print(f"✅ 구글 시트 데이터 저장 완료! ({len(all_data)}행)")
    except Exception as e:
        print(f"🚨 저장 에러: {e}")

# 2. 날짜 관리 함수 (1월~4월 모든 주중/주말 날짜 박제 - 원본 유지)
def get_fixed_target_dates():
    fixed_dates = [
        # 1월
        "2026-01-21", "2026-01-24", "2026-01-28", "2026-01-31",
        # 2월
        "2026-02-07", "2026-02-11", "2026-02-14", "2026-02-18", "2026-02-28",
        # 3월
        "2026-03-11", "2026-03-21", 
        # 4월
        "2026-04-15", "2026-04-18"
    ]
    today_str = datetime.now().strftime("%Y-%m-%d")
    target_dates = [d for d in fixed_dates if d >= today_str]
    print(f"📅 자동 타겟팅된 1~4월 분석 날짜 (총 {len(target_dates)}일): {target_dates}")
    print("\n➕ 위 날짜 외에 추가로 분석할 날짜가 있다면 입력하세요 (없으면 엔터)")
    extra_input = input("추가 날짜 (예: 2026-05-01, 2026-05-05): ")
    if extra_input.strip():
        extra_list = [d.strip() for d in extra_input.split(",")]
        target_dates.extend(extra_list)
    return sorted(list(set(target_dates)))

# 3. 개별 호텔 데이터 수집 함수 (소스 레벨 직접 해독 + [업데이트] 기본상품 필터 로직)
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
            
            # ---------------------------------------------------------
            # 🚀 [지배인님 요청 업데이트] 기본 상품(Room Only) 필터 로직
            # ---------------------------------------------------------
            # 조식, 패키지 등 부가 서비스가 포함된 상품명 키워드 제외
            exclude_keywords = ["조식", "패키지", "package", "포함", "연박", "long", "stay", "라운지", "특전", "무료증정", "wine", "와인"]
            
            if "원" in text and "\n" in text:
                # 상품 설명 텍스트에 제외 키워드가 있으면 수집하지 않고 넘어감
                if any(kw in text.lower() for kw in exclude_keywords):
                    continue

                parts = text.split("\n")
                room_name = parts[0].strip()

                if hotel_name == "엠버퓨어힐":
                    target_keywords = ["그린밸리 디럭스 더블", "힐 엠버 트윈", "힐 파인 더블"]
                    if not any(kw in room_name for kw in target_keywords):
                        continue
                
                found_channel = None
                # 야놀자/놀 키워드 통합 대응
                priority_order = ["아고다", "트립닷컴", "트립비토즈", "부킹닷컴", "야놀자", "여기어때", "익스피디아", "호텔스닷컴", "시크릿몰", "호텔패스", "네이버"]
                for channel in priority_order:
                    keywords = target_map.get(channel, [])
                    if any(key in html_content for key in keywords):
                        found_channel = channel
                        break 
                
                if not found_channel: found_channel = "플랫폼원본"

                if room_name not in collected_rooms_channels:
                    collected_rooms_channels[room_name] = []
                
                # 채널별 최저가(기본상품) 하나만 확보
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
                        print(f"   🔎 [기본상품확보] {room_name} | {found_channel}: {price_val:,}원")
        
        return rows
    except Exception as e:
        print(f"❌ {hotel_name} 수집 오류: {e}")
        return []

# 4. 메인 실행 함수 (원본 유지)
def main():
    # 13개 경쟁군 호텔 고정 리스트 (원본 유지)
    hotels = {
        "엠버퓨어힐": "N5302461", "그랜드하얏트": "N5281539", "파르나스": "N5287649",
        "신라호텔": "N1496601", "롯데호텔": "N1053569", "신라스테이": "N5305249",
        "해비치": "N1053576", "신화메리어트": "N3610024", "히든클리프": "N2982178",
        "더시에나": "N2662081", "조선힐스위트": "KYK10391783", "메종글래드": "N1053566",
        "그랜드조선제주": "N5279751"
    }

    print("\n" + "="*50)
    print("🏨 엠버 AI 지배인 전수 수집 엔진 v2.8 (서버 자동화 대응)")
    
    # 박제된 날짜 로드 (원본 함수 유지)
    test_dates = get_fixed_target_dates()
    
    options = Options()
    
    # --- [서버 자동화 필수 옵션 추가] ---
    options.add_argument("--headless")  # 서버(화면 없는 환경)에서 실행 필수
    options.add_argument("--no-sandbox") # 보안 제한 해제
    options.add_argument("--disable-dev-shm-usage") # 메모리 부족 에러 방지
    options.add_argument("--disable-gpu") # GPU 가속 비활성화
    # ----------------------------------
    
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # 드라이버 설치 및 실행
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    try:
        for hotel_name, hotel_id in hotels.items():
            print(f"\n🏨 {hotel_name} (ID: {hotel_id}) 분석 시작...")
            hotel_total_data = []
            for date in test_dates:
                print(f"   📅 {date} 수집 중...")
                # 기존 collect_hotel_data 함수 호출
                data = collect_hotel_data(driver, hotel_name, hotel_id, date)
                hotel_total_data.extend(data)
            
            if hotel_total_data:
                # 기존 save_to_google_sheet 함수 호출
                save_to_google_sheet(hotel_total_data)
                print(f"✨ {hotel_name} 전송 완료!")

    except Exception as e:
        print(f"🚨 메인 루프 실행 에러: {e}")

    finally:
        driver.quit()
        print("\n🏁 서버 환경에서 모든 수집 및 저장이 완료되었습니다!")

if __name__ == "__main__":
    main()
