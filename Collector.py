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
print("🚀 [시스템] 엠버 & 경쟁사 통합 모니터링 엔진 v13.0 (최종 무삭제 정밀판)", flush=True)

# 1. 파이어베이스 초기화 (원본 로직 유지)
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

# 2. 파이어베이스 저장 함수 (고유 ID 생성 및 중복 방지)
def save_to_firebase(db, all_data):
    if not db or not all_data: return
    try:
        batch = db.batch()
        for data in all_data:
            # 날짜_호텔_방_채널 조합으로 고유 ID 생성 (무결성 유지)
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
        
    # [공휴일] 2026년 주요 연휴 전수 조사
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
            
    # [여름성수기]
    target_dates.add("2026-07-29")
    target_dates.add("2026-08-01")
    
    final_list = sorted([d for d in target_dates if d >= today.strftime("%Y-%m-%d")])
    print(f"📅 [분석대상] 총 {len(final_list)}일 타겟팅 가동", flush=True)
    return final_list

# 4. 데이터 수집 함수 (무삭제 로직 + 차단 회피 + 정밀 추출)
def collect_hotel_data(driver, hotel_name, hotel_id, target_date, is_precision_mode):
    print(f"    📅 {target_date} 조회 시작...", flush=True) 
    try:
        # [차단방지] 쿠키 삭제 및 로딩 타임아웃
        driver.delete_all_cookies()
        driver.set_page_load_timeout(40)
        
        checkout_date = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        url = f"https://hotels.naver.com/detail/hotels/{hotel_id}/rates?checkIn={target_date}&checkOut={checkout_date}&adultCnt=2"
        
        driver.get(url)
        
        # [차단방지] 사람이 보는 것처럼 랜덤 대기
        time.sleep(random.uniform(5.0, 8.0))

        # [검증] 가격표 요소 확인
        try:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '원')]")))
        except:
            print(f"      ⚠️ {target_date}: 네이버 응답 없음 (차단 의심 또는 로딩 실패)", flush=True)
            return []

        # [단계별 스크롤] 하단 데이터 활성화
        for s in range(3):
            driver.execute_script(f"window.scrollTo(0, {(s+1)*1200});")
            time.sleep(1.2)

        # [전수 수집] 판매처 더보기 버튼 클릭 로직
        try:
            more_btns = driver.find_elements(By.XPATH, "//*[contains(text(), '판매처') and contains(text(), '더보기')]")
            for btn in more_btns[:8]:
                try:
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(0.3)
                except: continue
        except: pass

        # [정밀 추출] 모든 객실 상자 획득
        items = driver.find_elements(By.XPATH, "//li[descendant::*[contains(text(), '원')]] | //div[contains(@class, 'item')][descendant::*[contains(text(), '원')]]")
        
        if not items:
            print(f"      ⚠️ {target_date}: 객실 상자 검출 실패", flush=True)
            return []
        
        collected_data = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # [원본 필터 유지] 플랫폼 맵핑
        target_map = {
            "아고다": ["agoda", "아고다"], "트립닷컴": ["trip.com", "트립닷컴", "tripcom"],
            "트립비토즈": ["tripbtoz", "트립비토즈"], "부킹닷컴": ["booking.com", "부킹닷컴"],
            "야놀자": ["yanolja", "nol", "놀", "야놀자"], "여기어때": ["goodchoice", "여기어때"],
            "익스피디아": ["expedia", "익스피디아"], "호텔스닷컴": ["hotels.com", "호텔스닷컴"],
            "시크릿몰": ["secretmall", "시크릿몰"], "호텔패스": ["hotelpass", "호텔패스"],
            "네이버": ["naver", "네이버", "npay", "호텔에서 결제"]
        }
        
        # [원본 필터 유지] 엠버 고유 키워드 및 잡초 리스트
        amber_must_have = ["그린밸리", "포레스트", "힐파인", "힐엠버", "힐루나", "프라이빗"]
        garbage_keywords = ["아이미", "노블레스", "오션스위츠", "모텔", "게스트하우스", "비치", "관광호텔", "리조트텔"]

        per_room_channels = {}

        for item in items:
            try:
                raw_text = driver.execute_script("return arguments[0].innerText;", item).strip()
                if "원" not in raw_text: continue
                
                parts = [p.strip() for p in raw_text.split("\n") if p.strip()]
                room_name = parts[0]

                # 🚨 [잡초 제거] 블랙리스트 필터
                if any(trash in room_name for trash in garbage_keywords): continue

                # 🚨 [엠버 정밀 필터]
                if hotel_name == "엠버퓨어힐":
                    clean_name = room_name.replace(" ", "")
                    if not any(kw in clean_name for kw in amber_must_have):
                        continue # 타 호텔 추천 차단

                # [경쟁사 추천 호텔 방지] 
                if hotel_name != "엠버퓨어힐":
                    if any(bad in room_name for bad in ["추천", "비슷한", "주변", "거리"]): continue

                # [원본 유지] 제외 키워드
                if any(kw in raw_text.lower() for kw in ["조식", "패키지", "라운지", "와인"]): continue

                # 쾌속 모드 중복 방지 로직
                if not is_precision_mode and len(per_room_channels) >= 1 and room_name not in per_room_channels:
                    break
                
                # 채널 찾기
                html_content = item.get_attribute('innerHTML').lower()
                found_channel = "네이버"
                for channel, keywords in target_map.items():
                    if any(key in html_content for key in keywords):
                        found_channel = channel; break 

                # 중복 체크
                if room_name not in per_room_channels: per_room_channels[room_name] = []
                if found_channel in per_room_channels[room_name]: continue

                # 가격 숫자만 추출
                prices = [int(re.sub(r'[^0-9]', '', p)) for p in parts if "원" in p and re.sub(r'[^0-9]', '', p)]
                if not prices: continue
                real_price = max(prices)
                
                if real_price > 100000:
                    collected_data.append({
                        "collected_at": now, "hotel_name": hotel_name, "room_name": room_name,
                        "channel": found_channel, "price": real_price, "target_date": target_date
                    })
                    per_room_channels[room_name].append(found_channel)
                    print(f"      🔎 [{found_channel}] {room_name}: {real_price:,}원", flush=True)
            except: continue
        
        return collected_data
    except Exception as e:
        print(f"❌ {hotel_name} 에러: {e}", flush=True); return []

# 5. 메인 실행 함수 (13개 호텔 전수 복구)
def main():
    db = init_firebase()
    if not db: return

    # [무삭제] VIP 호텔 및 전체 대상 리스트 100% 복구
    vip_hotels = ["엠버퓨어힐", "파르나스", "그랜드조선제주", "그랜드하얏트", "신라호텔", "롯데호텔"]
    hotels = {
        "엠버퓨어힐": "N5302461", "그랜드하얏트": "N5281539", "파르나스": "N5287649",
        "신라호텔": "N1496601", "롯데호텔": "N1053569", "그랜드조선제주": "N5279751",
        "신라스테이": "N5305249", "해비치": "N1053576", "신화메리어트": "N3610024", 
        "히든클리프": "N2982178", "더시에나": "N2662081", "조선힐스위트": "KYK10391783", "메종글래드": "N1053566"
    }

    # 격주 점검 로직 복구
    today = datetime.now()
    is_monday = today.weekday() == 0
    is_even_week = (today.isocalendar()[1]) % 2 == 0
    is_full_scan_day = is_monday and is_even_week

    print("\n" + "="*50, flush=True)
    print(f"🏨 엠버 AI 통합 분석기 v13.0 가동", flush=True)
    if is_full_scan_day: print("📢 격주 정기 정밀 점검일입니다.", flush=True)
    
    dates = get_dynamic_target_dates()
    
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
            
            for date in dates:
                data = collect_hotel_data(driver, hotel_name, hotel_id, date, is_precision)
                if data:
                    save_to_firebase(db, data)
                
                # [차단방지 핵심] 날짜 간 랜덤 대기 (3~6초)
                time.sleep(random.uniform(3.0, 6.0))
    except Exception as e:
        print(f"🚨 메인 루프 실행 에러: {e}", flush=True)
    finally:
        driver.quit()
        print("\n🏁 모든 수집 및 저장이 완료되었습니다!", flush=True)

if __name__ == "__main__":
    main()
