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
print("🚀 [시스템] 엠버 & 경쟁사 통합 모니터링 엔진 v13.3 (최종 무삭제 정밀조사판)", flush=True)

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

# 2. 파이어베이스 저장 (고유 ID 생성으로 데이터 무결성 유지)
def save_to_firebase(db, all_data):
    if not db or not all_data: return
    try:
        batch = db.batch()
        for data in all_data:
            # 날짜_호텔_방_채널 조합 ID (중복 방지 핵심)
            doc_id = f"{data['target_date']}_{data['hotel_name']}_{data['room_name']}_{data['channel']}".replace(" ", "").replace("/", "_")
            doc_ref = db.collection("Hotel_Prices").document(doc_id)
            batch.set(doc_ref, data)
        batch.commit()
        print(f"      ✅ {len(all_data)}개 데이터 전송 완료!", flush=True)
    except Exception as e:
        print(f"🚨 [DB 저장 에러] {e}", flush=True)

# 3. 날짜 계산 함수 (지배인님 원본 로직 100% 동일)
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
    # [공휴일] 2026년 주요 연휴
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

# 4. 데이터 수집 함수 (무삭제 잡초 제거 + 엠버 정밀 필터링)
def collect_hotel_data(driver, hotel_name, hotel_id, target_date, is_precision_mode):
    print(f"    📅 {target_date} 분석 시도...", flush=True) 
    try:
        driver.delete_all_cookies()
        driver.set_page_load_timeout(60) # 타임아웃 넉넉히
        checkout_date = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        url = f"https://hotels.naver.com/detail/hotels/{hotel_id}/rates?checkIn={target_date}&checkOut={checkout_date}&adultCnt=2"
        
        driver.get(url)
        time.sleep(random.uniform(6.0, 9.0)) # 차단 회피용 충분한 대기

        try:
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '원')]")))
        except:
            print(f"      ⚠️ 데이터 로딩 지연/실패 (건너뜀)", flush=True)
            return []

        # 스크롤 및 판매처 더보기 (지배인님 원본 로직)
        driver.execute_script("window.scrollTo(0, 1500);")
        time.sleep(1.5)
        try:
            more_btns = driver.find_elements(By.XPATH, "//*[contains(text(), '판매처') and contains(text(), '더보기')]")
            for btn in more_btns[:10]:
                try: driver.execute_script("arguments[0].click();", btn); time.sleep(0.3)
                except: continue
        except: pass

        items = driver.find_elements(By.XPATH, "//li[descendant::*[contains(text(), '원')]] | //div[contains(@class, 'item')][descendant::*[contains(text(), '원')]]")
        
        collected_data = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # 플랫폼 맵핑
        target_map = {"아고다": ["agoda", "아고다"], "트립닷컴": ["trip.com", "트립닷컴"], "트립비토즈": ["tripbtoz"], "부킹닷컴": ["booking.com"], "야놀자": ["yanolja", "놀"], "여기어때": ["goodchoice"], "익스피디아": ["expedia"], "호텔스닷컴": ["hotels.com"], "시크릿몰": ["secretmall"], "호텔패스": ["hotelpass"], "네이버": ["naver", "npay", "호텔에서 결제"]}
        
        # [무삭제] 엠버 고유 키워드 및 잡초 리스트
        amber_must_have = ["그린밸리", "포레스트", "힐파인", "힐엠버", "힐루나", "프라이빗"]
        garbage_keywords = ["아이미", "노블레스", "오션스위츠", "모텔", "게스트하우스", "비치", "관광호텔", "리조트텔"]

        per_room_channels = {}
        for item in items:
            try:
                raw_text = driver.execute_script("return arguments[0].innerText;", item).strip()
                if "원" not in raw_text: continue
                parts = [p.strip() for p in raw_text.split("\n") if p.strip()]
                room_name = parts[0]

                raw_text = driver.execute_script("return arguments[0].innerText;", item).strip()
                # [강화된 필터] 텍스트 전체에서 타 호텔명이 감지되면 즉시 제외
                if any(trash in raw_text for trash in garbage_keywords):
                    continue 

                parts = [p.strip() for p in raw_text.split("\n") if p.strip()]
                room_name = parts[0]

                # [추가 보안] 경쟁사 수집 시에도 '추천', '비슷한' 문구가 보이면 차단
                if hotel_name != "엠버퓨어힐":
                    if any(bad in raw_text for bad in ["추천", "비슷한", "주변", "다른 호텔"]):

                # 잡초 제거 (원본 보존)
                if any(trash in room_name for trash in garbage_keywords): continue

                # 엠버 정밀 필터 (원본 보존)
                if hotel_name == "엠버퓨어힐":
                    clean_name = room_name.replace(" ", "")
                    if not any(kw in clean_name for kw in amber_must_have): continue

                # 타 호텔 추천 방지
                if any(bad in room_name for bad in ["추천", "비슷한", "주변", "거리"]): continue

                # 조식 제외
                if any(kw in raw_text.lower() for kw in ["조식", "패키지", "라운지", "와인"]): continue

                if not is_precision_mode and len(per_room_channels) >= 1 and room_name not in per_room_channels:
                    break
                
                html_content = item.get_attribute('innerHTML').lower()
                found_channel = "네이버"
                for ch, kws in target_map.items():
                    if any(kw in html_content for kw in kws): found_channel = ch; break

                if room_name not in per_room_channels: per_room_channels[room_name] = []
                if found_channel in per_room_channels[room_name]: continue

                prices = [int(re.sub(r'[^0-9]', '', p)) for p in parts if "원" in p and re.sub(r'[^0-9]', '', p)]
                if not prices: continue
                real_price = max(prices)
                
                if real_price > 100000:
                    collected_data.append({"collected_at": now, "hotel_name": hotel_name, "room_name": room_name, "channel": found_channel, "price": real_price, "target_date": target_date})
                    per_room_channels[room_name].append(found_channel)
                    print(f"      🔎 [{found_channel}] {room_name}: {real_price:,}원", flush=True)
            except: continue
        return collected_data
    except Exception as e:
        print(f"❌ {hotel_name} 에러: {e}", flush=True); return []

# 5. 메인 실행 (13개 호텔 리스트 및 격주 점검 로직 복구)
def main():
    db = init_firebase()
    if not db: return
    
    # [무삭제] 13개 호텔 리스트 완벽 복구
    vip_hotels = ["엠버퓨어힐", "파르나스", "그랜드조선제주", "그랜드하얏트", "신라호텔", "롯데호텔"]
    hotels = {
        "엠버퓨어힐": "N5302461", "그랜드하얏트": "N5281539", "파르나스": "N5287649",
        "신라호텔": "N1496601", "롯데호텔": "N1053569", "그랜드조선제주": "N5279751",
        "신라스테이": "N5305249", "해비치": "N1053576", "신화메리어트": "N3610024", 
        "히든클리프": "N2982178", "더시에나": "N2662081", "조선힐스위트": "KYK10391783", "메종글래드": "N1053566"
    }

    # [무삭제] 격주 점검 로직
    today = datetime.now()
    is_monday = today.weekday() == 0
    is_even_week = (today.isocalendar()[1]) % 2 == 0
    is_full_scan_day = is_monday and is_even_week

    print("\n" + "="*50, flush=True)
    print(f"🏨 엠버 AI 통합 분석기 v13.3 가동", flush=True)
    if is_full_scan_day: print("📢 격주 정기 정밀 점검일입니다.", flush=True)
    
    dates = get_dynamic_target_dates()
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.set_page_load_timeout(60)

    try:
        for hotel_name, hotel_id in hotels.items():
            is_precision = (hotel_name in vip_hotels) or is_full_scan_day
            print(f"\n🏨 {hotel_name} 분석 시작 (모드: {'정밀' if is_precision else '쾌속'})", flush=True)
            for date in dates:
                data = collect_hotel_data(driver, hotel_name, hotel_id, date, is_precision)
                if data: save_to_firebase(db, data)
                time.sleep(random.uniform(4.0, 7.0))
    finally:
        driver.quit()
        print("\n🏁 모든 수집 완료", flush=True)

if __name__ == "__main__":
    main()

