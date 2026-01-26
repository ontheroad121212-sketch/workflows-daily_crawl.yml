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
import random

# [시스템 로그]
print("🚀 [시스템] 엠버 AI 통합 모니터링 엔진 v13.9 (정예 수집 보장판)", flush=True)

# 1. 파이어베이스 초기화 (원본 유지)
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

# 2. 파이어베이스 저장 (원본 유지)
def save_to_firebase(db, all_data):
    if not db or not all_data: return
    try:
        batch = db.batch()
        for data in all_data:
            doc_id = f"{data['target_date']}_{data['hotel_name']}_{data['room_name']}_{data['channel']}".replace(" ", "").replace("/", "_")
            doc_ref = db.collection("Hotel_Prices").document(doc_id)
            batch.set(doc_ref, data)
        batch.commit()
        print(f"      ✅ {len(all_data)}개 정예 데이터 전송 완료!", flush=True)
    except Exception as e:
        print(f"🚨 [DB 저장 에러] {e}", flush=True)

# 3. 날짜 계산 함수 (원본 유지)
def get_dynamic_target_dates():
    today = datetime.now()
    target_dates = set()
    for i in range(7, 22):
        future_date = today + timedelta(days=i)
        if future_date.weekday() in [2, 5]: target_dates.add(future_date.strftime("%Y-%m-%d"))
    current_month, current_year = today.month, today.year
    for i in range(1, 4):
        month = (current_month + i - 1) % 12 + 1
        year = current_year + (current_month + i - 1) // 12
        cal = calendar.monthcalendar(year, month)
        weds = [w[calendar.WEDNESDAY] for w in cal if w[calendar.WEDNESDAY] != 0]
        if len(weds) >= 2: target_dates.add(f"{year}-{month:02d}-{weds[1]:02d}")
        sats = [s[calendar.SATURDAY] for s in cal if s[calendar.SATURDAY] != 0]
        if len(sats) >= 3: target_dates.add(f"{year}-{month:02d}-{sats[2]:02d}")
    holidays_2026 = ["2026-02-13", "2026-02-16", "2026-02-21", "2026-03-01", "2026-05-05", "2026-05-24", "2026-06-06", "2026-08-15", "2026-09-24", "2026-09-25", "2026-09-26", "2026-10-03", "2026-10-09", "2026-12-25"]
    for h in holidays_2026:
        h_date = datetime.strptime(h, "%Y-%m-%d")
        if h_date >= today:
            target_dates.add((h_date - timedelta(days=1)).strftime("%Y-%m-%d"))
            target_dates.add(h)
            target_dates.add((h_date + timedelta(days=1)).strftime("%Y-%m-%d"))
    target_dates.add("2026-07-29"); target_dates.add("2026-08-01")
    final_list = sorted([d for d in target_dates if d >= today.strftime("%Y-%m-%d")])
    print(f"📅 [분석대상] 총 {len(final_list)}일 타겟팅 가동", flush=True)
    return final_list

# 4. 데이터 수집 함수 (지배인님 로직 보강판)
def collect_hotel_data(driver, hotel_name, hotel_id, target_date, is_precision_mode):
    print(f"    📅 {target_date} 분석 시도...", flush=True) 
    try:
        driver.delete_all_cookies()
        checkout_date = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        url = f"https://hotels.naver.com/detail/hotels/{hotel_id}/rates?checkIn={target_date}&checkOut={checkout_date}&adultCnt=2"
        
        driver.get(url)
        
        # [패치] 가격표 리스트가 뜰 때까지 정밀 대기 (최대 25초)
        try:
            WebDriverWait(driver, 25).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='PriceList_list']"))
            )
        except:
            print(f"      ⚠️ 요금표 로딩 실패", flush=True)
            return []

        # [패치] 하단 추천 광고 로딩 방지를 위해 절반만 스크롤
        driver.execute_script("window.scrollTo(0, 800);")
        time.sleep(2)

        items = driver.find_elements(By.XPATH, "//li[descendant::*[contains(text(), '원')]]")
        
        temp_storage = {} 
        logo_map = {
            "agoda": "아고다", "trip.com": "트립닷컴", "tripbtoz": "트립비토즈",
            "booking.com": "부킹닷컴", "yanolja": "야놀자", "nol": "야놀자", "goodchoice": "여기어때",
            "expedia": "익스피디아", "hotels.com": "호텔스닷컴", "secret_mall": "시크릿몰"
        }

        # 호텔 실명제 키워드
        check_kw = hotel_name.replace("그랜드", "").replace("제주", "").replace("호텔", "").strip()[:2]
        amber_rooms = ["그린", "포레스트", "힐파인", "힐엠버", "힐루나", "프라이빗"]

        for item in items:
            try:
                raw_text = item.text.strip()
                if "원" not in raw_text: continue
                
                # 🚨 [보안] 광고 필터링
                is_valid = False
                if hotel_name == "엠버퓨어힐":
                    if any(kw in raw_text for kw in amber_rooms): is_valid = True
                elif check_kw in raw_text:
                    is_valid = True

                if not is_valid: continue
                if any(bad in raw_text for bad in ["추천", "연관", "비슷한", "다른 호텔"]): continue

                # 채널명 판별 로직
                found_channel = "네이버"
                html_content = item.get_attribute('innerHTML').lower()
                for k, v in logo_map.items():
                    if v in raw_text: found_channel = v; break
                if found_channel == "네이버":
                    for k, v in logo_map.items():
                        if k in html_content: found_channel = v; break

                parts = [p.strip() for p in raw_text.split("\n") if p.strip()]
                room_name = parts[0]
                
                prices = [int(re.sub(r'[^0-9]', '', p)) for p in parts if "원" in p and re.sub(r'[^0-9]', '', p)]
                if not prices: continue
                current_price = max(prices)

                if found_channel not in temp_storage: temp_storage[found_channel] = []
                temp_storage[found_channel].append({
                    "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "hotel_name": hotel_name, "room_name": room_name,
                    "channel": found_channel, "price": current_price, "target_date": target_date
                })
            except: continue

        # 🚨 [정예 선발 로직 가동]
        if not temp_storage: 
            print(f"      ❌ 검색된 실객실 데이터 없음", flush=True)
            return []

        # 1. 채널별 최저가 기준 상위 5개 채널 선정
        sorted_channels = sorted(
            temp_storage.keys(), 
            key=lambda x: min([d['price'] for d in temp_storage[x]])
        )[:5]

        final_data = []
        for ch in sorted_channels:
            # 2. 각 채널별 가격 낮은 순 상위 3개 객실 선발
            sorted_rooms = sorted(temp_storage[ch], key=lambda x: x['price'])[:3]
            final_data.extend(sorted_rooms)
            for d in sorted_rooms:
                print(f"      🎯 [{d['channel']}] {d['room_name']}: {d['price']:,}원", flush=True)

        return final_data
    except Exception as e:
        print(f"❌ {hotel_name} 에러: {e}", flush=True)
        return []

# 5. 메인 실행 (원본 유지)
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

    today = datetime.now()
    is_full_scan_day = (today.weekday() == 0) and ((today.isocalendar()[1]) % 2 == 0)

    print("\n" + "="*50, flush=True)
    print(f"🏨 엠버 AI 통합 분석기 v13.9 가동", flush=True)
    
    dates = get_dynamic_target_dates()
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        for hotel_name, hotel_id in hotels.items():
            is_precision = (hotel_name in vip_hotels) or is_full_scan_day
            print(f"\n🏨 {hotel_name} 분석 가동 (모드: 정예 수집)", flush=True)
            for date in dates:
                data = collect_hotel_data(driver, hotel_name, hotel_id, date, is_precision)
                if data: save_to_firebase(db, data)
                # 정예 수집이므로 대기 시간 살짝 단축
                time.sleep(random.uniform(4.0, 7.0))
    finally:
        driver.quit()
        print("\n🏁 모든 정예 데이터 수집 완료", flush=True)

if __name__ == "__main__":
    main()
