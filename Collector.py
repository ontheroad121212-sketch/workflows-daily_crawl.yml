import firebase_admin
from firebase_admin import credentials, firestore
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

# [시스템 로그]
print("🚀 [시스템] 엠버 AI 지배인 엔진 v11.0 (잡초 제거 강화판)", flush=True)

# 1. 파이어베이스 초기화 (GitHub Secrets 사용)
def init_firebase():
    try:
        fb_key_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        if not fb_key_json:
            print("🚨 [에러] FIREBASE_SERVICE_ACCOUNT 설정이 없습니다.", flush=True)
            return None
        
        fb_key_dict = json.loads(fb_key_json)
        cred = credentials.Certificate(fb_key_dict)
        
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        
        return firestore.client()
    except Exception as e:
        print(f"🚨 [DB 연결 실패] {e}", flush=True)
        return None

# 2. 파이어베이스 저장 함수
def save_to_firebase(db, all_data):
    if not db or not all_data: return
    try:
        batch = db.batch()
        for data in all_data:
            # 중복 방지 ID (날짜_호텔_방_채널)
            doc_id = f"{data['target_date']}_{data['hotel_name']}_{data['room_name']}_{data['channel']}".replace(" ", "").replace("/", "_")
            doc_ref = db.collection("Hotel_Prices").document(doc_id)
            batch.set(doc_ref, data)
        
        batch.commit()
        print(f"✅ Firebase DB 저장 완료! ({len(all_data)}행)", flush=True)
    except Exception as e:
        print(f"🚨 [DB 저장 에러] {e}", flush=True)

# 3. 날짜 계산 함수 (지배인님 원본 유지)
def get_dynamic_target_dates():
    today = datetime.now()
    target_dates = set()
    
    for i in range(7, 22):
        future_date = today + timedelta(days=i)
        if future_date.weekday() in [2, 5]: 
            target_dates.add(future_date.strftime("%Y-%m-%d"))
            
    current_month, current_year = today.month, today.year
    for i in range(1, 4):
        month = (current_month + i - 1) % 12 + 1
        year = current_year + (current_month + i - 1) // 12
        cal = calendar.monthcalendar(year, month)
        
        weds = [w[calendar.WEDNESDAY] for w in cal if w[calendar.WEDNESDAY] != 0]
        if len(weds) >= 2: target_dates.add(f"{year}-{month:02d}-{weds[1]:02d}")
        
        sats = [s[calendar.SATURDAY] for s in cal if s[calendar.SATURDAY] != 0]
        if len(sats) >= 3: target_dates.add(f"{year}-{month:02d}-{sats[2]:02d}")
        
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

# 4. 데이터 수집 함수 (잡초 제거 로직 추가됨)
def collect_hotel_data(driver, hotel_name, hotel_id, target_date, is_precision_mode):
    print(f"    📅 {target_date} 조회 시도 중...", flush=True) 
    try:
        driver.set_page_load_timeout(30)
        checkout_date = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        url = f"https://hotels.naver.com/detail/hotels/{hotel_id}/rates?checkIn={target_date}&checkOut={checkout_date}&adultCnt=2"
        
        driver.get(url)
        
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '원')]")))
        except:
            print(f"      ⚠️ {target_date}: 가격 정보 로딩 실패", flush=True)
            return []

        # 스크롤
        for s in range(3):
            driver.execute_script(f"window.scrollTo(0, {(s+1)*1200});")
            time.sleep(1)

        # 더보기 버튼 클릭
        try:
            more_buttons = driver.find_elements(By.XPATH, "//*[contains(text(), '판매처') and contains(text(), '더보기')]")
            for btn in more_buttons:
                try:
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(0.2)
                except: continue
        except: pass

        items = driver.find_elements(By.XPATH, "//li[descendant::*[contains(text(), '원')]] | //div[contains(@class, 'item')][descendant::*[contains(text(), '원')]]")
        
        collected_data = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        target_map = {
            "아고다": ["agoda", "아고다"], "트립닷컴": ["trip.com", "트립닷컴", "tripcom"],
            "트립비토즈": ["tripbtoz", "트립비토즈"], "부킹닷컴": ["booking.com", "부킹닷컴"],
            "야놀자": ["yanolja", "nol", "놀", "야놀자"], "여기어때": ["goodchoice", "여기어때"],
            "익스피디아": ["expedia", "익스피디아"], "호텔스닷컴": ["hotels.com", "호텔스닷컴"],
            "시크릿몰": ["secretmall", "시크릿몰"], "호텔패스": ["hotelpass", "호텔패스"],
            "네이버": ["naver", "네이버", "npay", "호텔에서 결제"]
        }
        
        # [필터 1] 엠버 전용 필수 포함 키워드
        amber_must_have = ["그린밸리", "포레스트", "힐파인", "힐엠버", "힐루나", "힐 파인", "힐 엠버", "힐 루나", "프라이빗"]
        
        # [필터 2] 🔥 잡초 제거 리스트 (이 단어가 보이면 무조건 버림)
        garbage_keywords = ["아이미", "노블레스", "오션스위츠", "모텔", "게스트하우스", "통나무", "비치", "관광호텔", "리조트텔"]

        per_room_channels = {}

        for item in items:
            try:
                raw_text = driver.execute_script("return arguments[0].innerText;", item).strip()
            except: continue
            
            if "원" not in raw_text: continue
            parts = [p.strip() for p in raw_text.split("\n") if p.strip()]
            if not parts: continue
            room_name = parts[0]

            # 🚨 [잡초 제거 로직] 이름에 이상한 호텔명이 섞여있으면 즉시 폐기
            if any(trash in room_name for trash in garbage_keywords):
                continue

            # 🚨 [엠버 전용 필터] 엠버인데 엠버 방 이름이 없으면 폐기 (타 호텔 추천 방지)
            if hotel_name == "엠버퓨어힐":
                is_amber = False
                for kw in amber_must_have:
                    if kw.replace(" ", "") in room_name.replace(" ", ""):
                        is_amber = True; break
                if not is_amber: continue 

            # [경쟁사 타 호텔 방지] 
            if hotel_name != "엠버퓨어힐":
                if any(bad in room_name for bad in ["추천", "비슷한", "주변", "거리"]): continue

            # 조식/패키지 제외
            if any(kw in raw_text.lower() for kw in ["조식", "패키지", "라운지", "와인"]): continue

            # 쾌속 모드 중복 방지
            if not is_precision_mode and len(per_room_channels) >= 1 and room_name not in per_room_channels:
                break
            
            # 채널 매핑
            html_content = ""
            try: html_content = item.get_attribute('innerHTML').lower()
            except: pass
            
            found_channel = "네이버"
            for channel, keywords in target_map.items():
                if any(key in html_content for key in keywords):
                    found_channel = channel; break 

            if room_name not in per_room_channels: per_room_channels[room_name] = []
            if found_channel in per_room_channels[room_name]: continue

            prices = [int(re.sub(r'[^0-9]', '', p)) for p in parts if "원" in p and re.sub(r'[^0-9]', '', p)]
            if not prices: continue
            real_price = max(prices)
            
            if real_price > 100000:
                collected_data.append({
                    "collected_at": now,
                    "hotel_name": hotel_name,
                    "room_name": room_name,
                    "channel": found_channel,
                    "price": real_price,
                    "target_date": target_date
                })
                per_room_channels[room_name].append(found_channel)
                print(f"    🔎 [{found_channel}] {room_name}: {real_price:,}원", flush=True)
        
        return collected_data
    except Exception as e:
        print(f"❌ {hotel_name} 수집 오류: {e}", flush=True); return []

# 5. 메인 실행 함수
def main():
    db = init_firebase()
    if not db: return

    vip_hotels = ["엠버퓨어힐", "파르나스", "그랜드조선제주", "그랜드하얏트", "신라호텔", "롯데호텔"]
    hotels = {
        "엠버퓨어힐": "N5302461", "그랜드하얏트": "N5281539", "파르나스": "N5287649",
        "신라호텔": "N1496601", "롯데호텔": "N1053569", "그랜드조선제주": "N5279751",
        "신라스테이": "N5305249", "해비치": "N1053576", "신화메리어트": "N3610024", 
        "히든클리프": "N2982178", "더시에나": "N2662081", "조선힐스위트": "KYK10391783", "메종글래드": "N1053566"
    }

    is_monday = datetime.now().weekday() == 0
    is_even_week = (datetime.now().isocalendar()[1]) % 2 == 0
    is_full_scan_day = is_monday and is_even_week

    print("\n" + "="*50, flush=True)
    print(f"🏨 엠버 & 경쟁사 통합 엔진 v11.0 (잡초 제거 가동)", flush=True)
    
    test_dates = get_dynamic_target_dates()
    
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=ko_KR")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
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
                    save_to_firebase(db, data)
                    print(f"📍 {date} 데이터 DB 전송 완료", flush=True)
    except Exception as e:
        print(f"🚨 메인 루프 실행 에러: {e}", flush=True)
    finally:
        driver.quit()
        print("\n🏁 모든 수집 및 저장이 완료되었습니다!", flush=True)

if __name__ == "__main__":
    main()
