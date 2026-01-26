import firebase_admin
from firebase_admin import credentials, firestore
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time, re, json, random, os
from datetime import datetime, timedelta

print("🏨 [v14.3] 엠버 AI 마스터 키 (로컬 가동 최적화 버전)", flush=True)

# 1. 파이어베이스 초기화 (환경변수가 없으면 로컬 파일 참조하도록 보강)
def init_firebase():
    try:
        fb_key_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        if fb_key_json:
            fb_key_dict = json.loads(fb_key_json)
            cred = credentials.Certificate(fb_key_dict)
        else:
            # 로컬에서 돌릴 때 key.json 파일이 있다면 사용
            cred = credentials.Certificate("key.json") 
        
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        print(f"🚨 DB 연결 안 됨 (로그만 출력): {e}")
        return None

# 2. 데이터 수집 함수 (눈에 보이게 가동)
def collect_hotel_data(driver, hotel_name, hotel_id, target_date):
    print(f"    📅 {target_date} 분석 중...", flush=True)
    try:
        url = f"https://hotels.naver.com/detail/hotels/{hotel_id}/rates?checkIn={target_date}&checkOut={(datetime.strptime(target_date, '%Y-%m-%d')+timedelta(days=1)).strftime('%Y-%m-%d')}&adultCnt=2"
        driver.get(url)
        
        # [핵심] 요금표가 뜰 때까지 실제 브라우저처럼 대기
        wait = WebDriverWait(driver, 30)
        wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '원')]")))
        
        # 로딩 유도를 위해 살짝 스크롤
        driver.execute_script("window.scrollTo(0, 1000);")
        time.sleep(random.uniform(3, 5))

        items = driver.find_elements(By.XPATH, "//li[descendant::*[contains(text(), '원')]] | //div[contains(@class, 'item') and descendant::*[contains(text(), '원')]]")
        
        temp_storage = {}
        logo_map = {"agoda": "아고다", "trip.com": "트립닷컴", "tripbtoz": "트립비토즈", "booking": "부킹닷컴", "yanolja": "야놀자", "goodchoice": "여기어때", "expedia": "익스피디아"}

        check_kw = hotel_name.replace("그랜드", "").replace("제주", "").replace("호텔", "").strip()[:2]
        
        for item in items:
            try:
                raw_text = item.text.strip()
                if "원" not in raw_text or check_kw not in raw_text: continue
                if any(bad in raw_text for bad in ["추천", "연관", "비슷한"]): continue

                # 채널명 판별 (이미지 URL 분석 강화)
                html = item.get_attribute('innerHTML').lower()
                found_channel = "네이버"
                for k, v in logo_map.items():
                    if k in html or v in raw_text:
                        found_channel = v; break

                prices = [int(p.replace(',', '')) for p in re.findall(r'(\d{1,3}(?:,\d{3})+)', raw_text)]
                if not prices: continue
                
                if found_channel not in temp_storage: temp_storage[found_channel] = []
                temp_storage[found_channel].append({
                    "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "hotel_name": hotel_name, "room_name": raw_text.split('\n')[0][:25],
                    "channel": found_channel, "price": max(prices), "target_date": target_date
                })
            except: continue

        final_data = []
        if temp_storage:
            # 채널 5개 x 객실 3개 선발
            for ch in sorted(temp_storage.keys(), key=lambda x: min([d['price'] for d in temp_storage[x]]))[:5]:
                rooms = sorted(temp_storage[ch], key=lambda x: x['price'])[:3]
                final_data.extend(rooms)
                for r in rooms: print(f"      🎯 [{r['channel']}] {r['room_name']}: {r['price']:,}원")
        return final_data
    except Exception as e:
        print(f"      ⚠️ 실패: {e}")
        return []

def main():
    db = init_firebase()
    hotels = {
        "엠버퓨어힐": "N5302461", "그랜드하얏트": "N5281539", "파르나스": "N5287649",
        "신라호텔": "N1496601", "롯데호텔": "N1053569", "그랜드조선제주": "N5279751",
        "해비치": "N1053576", "신화메리어트": "N3610024", "히든클리프": "N2982178", "더시에나": "N2662081"
    }
    
    # 향후 2주간의 주요 수/토요일만 타겟팅
    dates = []
    for i in range(1, 15):
        d = (datetime.now() + timedelta(days=i))
        if d.weekday() in [2, 5]: dates.append(d.strftime("%Y-%m-%d"))

    options = Options()
    # 🚨 [중요] 로컬에서 돌릴 때는 Headless를 끄고 창을 보면서 돌리는 게 안전합니다.
    # options.add_argument("--headless=new") 
    options.add_argument("--start-maximized")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        for name, hid in hotels.items():
            print(f"\n🏨 {name} 분석 가동")
            for date in dates:
                data = collect_hotel_data(driver, name, hid, date)
                if data and db: 
                    batch = db.batch()
                    for d in data:
                        doc_id = f"{d['target_date']}_{d['hotel_name']}_{d['room_name']}_{d['channel']}".replace(" ","")
                        batch.set(db.collection("Hotel_Prices").document(doc_id), d)
                    batch.commit()
                time.sleep(random.uniform(2, 4))
    finally:
        driver.quit()
        print("\n🏁 조사 완료")

if __name__ == "__main__": main()
