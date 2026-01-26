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
print("🚀 [전략 모드] 엠버 AI 통합 모니터링 엔진 v14.1 (수동 가동 전용)", flush=True)

def init_firebase():
    try:
        fb_key_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        if not fb_key_json: return None
        fb_key_dict = json.loads(fb_key_json)
        cred = credentials.Certificate(fb_key_dict)
        if not firebase_admin._apps: firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e: return None

def save_to_firebase(db, all_data):
    if not db or not all_data: return
    try:
        batch = db.batch()
        for data in all_data:
            doc_id = f"{data['target_date']}_{data['hotel_name']}_{data['room_name']}_{data['channel']}".replace(" ", "").replace("/", "_")
            doc_ref = db.collection("Hotel_Prices").document(doc_id)
            batch.set(doc_ref, data)
        batch.commit()
        print(f"      ✅ {len(all_data)}개 정예 데이터 동기화 완료!", flush=True)
    except Exception as e:
        print(f"🚨 [DB 전송 실패] {e}\n📋 데이터 백업:\n{json.dumps(all_data, ensure_ascii=False)}", flush=True)

def get_dynamic_target_dates():
    today = datetime.now()
    target_dates = set()
    # 수동 모드이므로 향후 30일 이내의 주요 수/토요일 및 연휴를 집중 타겟팅
    for i in range(1, 31):
        future_date = today + timedelta(days=i)
        if future_date.weekday() in [2, 5]: 
            target_dates.add(future_date.strftime("%Y-%m-%d"))
    
    # 2026년 주요 연휴 (필요시 업데이트)
    holidays = ["2026-02-13", "2026-02-16", "2026-05-05", "2026-05-24", "2026-10-03", "2026-12-25"]
    for h in holidays:
        h_date = datetime.strptime(h, "%Y-%m-%d")
        if h_date >= today:
            target_dates.add(h)
            target_dates.add((h_date - timedelta(days=1)).strftime("%Y-%m-%d"))

    return sorted(list(target_dates))

def collect_hotel_data(driver, hotel_name, hotel_id, target_date):
    print(f"    📅 {target_date} 분석 중...", flush=True) 
    try:
        driver.delete_all_cookies()
        url = f"https://hotels.naver.com/detail/hotels/{hotel_id}/rates?checkIn={target_date}&checkOut={(datetime.strptime(target_date, '%Y-%m-%d')+timedelta(days=1)).strftime('%Y-%m-%d')}&adultCnt=2"
        
        driver.get(url)
        # 수동 모드 핵심: 페이지가 완전히 그려질 때까지 넉넉히 대기 (12~15초)
        time.sleep(random.uniform(12.0, 15.0))

        # 요금 상자 찾기
        items = driver.find_elements(By.XPATH, "//li[descendant::*[contains(text(), '원')]] | //div[contains(@class, 'item') and descendant::*[contains(text(), '원')]]")
        
        temp_storage = {} 
        logo_map = {"agoda": "아고다", "trip.com": "트립닷컴", "tripbtoz": "트립비토즈", "booking.com": "부킹닷컴", "yanolja": "야놀자", "nol": "야놀자", "goodchoice": "여기어때", "expedia": "익스피디아", "hotels.com": "호텔스닷컴"}

        # 화이트리스트 키워드 (조사 대상 호텔 이름이 포함되어야만 수집)
        core_name = hotel_name.replace("그랜드", "").replace("제주", "").replace("호텔", "").strip()[:2]
        amber_rooms = ["그린", "포레스트", "힐파인", "힐엠버", "힐루나", "프라이빗"]

        for item in items:
            try:
                raw_text = item.text.strip()
                if "원" not in raw_text: continue
                
                # 🚨 강력한 타 호텔 광고 차단 로직
                is_valid = False
                if hotel_name == "엠버퓨어힐":
                    if any(kw in raw_text for kw in amber_rooms): is_valid = True
                elif core_name in raw_text:
                    is_valid = True
                
                if not is_valid or any(bad in raw_text for bad in ["추천", "연관", "비슷한"]): continue

                # 채널 및 가격 추출
                html_source = item.get_attribute('innerHTML').lower()
                found_channel = "네이버"
                for k, v in logo_map.items():
                    if v in raw_text or k in html_source:
                        found_channel = v; break

                price_match = re.findall(r'(\d{1,3}(?:,\d{3})+)', raw_text)
                if not price_match: continue
                current_price = int(price_match[-1].replace(',', '')) # 가장 마지막(세금포함가) 선택

                if found_channel not in temp_storage: temp_storage[found_channel] = []
                temp_storage[found_channel].append({
                    "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "hotel_name": hotel_name, "room_name": raw_text.split('\n')[0],
                    "channel": found_channel, "price": current_price, "target_date": target_date
                })
            except: continue

        if not temp_storage: return []

        # 상위 5개 채널 x 하위 3개 객실타입 추출 (지배인님 전략)
        final_data = []
        sorted_channels = sorted(temp_storage.keys(), key=lambda x: min([d['price'] for d in temp_storage[x]]))[:5]
        for ch in sorted_channels:
            sorted_rooms = sorted(temp_storage[ch], key=lambda x: x['price'])[:3]
            final_data.extend(sorted_rooms)
            for d in sorted_rooms: print(f"      🎯 [{d['channel']}] {d['room_name']}: {d['price']:,}원", flush=True)

        return final_data
    except Exception as e: return []

def main():
    db = init_firebase()
    if not db: return
    hotels = {"엠버퓨어힐": "N5302461", "그랜드하얏트": "N5281539", "파르나스": "N5287649", "신라호텔": "N1496601", "롯데호텔": "N1053569", "그랜드조선제주": "N5279751"}
    
    dates = get_dynamic_target_dates()
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        for hotel_name, hotel_id in hotels.items():
            print(f"\n🏨 {hotel_name} 정예 분석 가동", flush=True)
            for date in dates:
                data = collect_hotel_data(driver, hotel_name, hotel_id, date)
                if data: save_to_firebase(db, data)
                time.sleep(random.uniform(5.0, 8.0))
    finally:
        driver.quit()
        print("\n🏁 수동 전수 조사 완료", flush=True)

if __name__ == "__main__": main()
