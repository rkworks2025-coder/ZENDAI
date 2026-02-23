import sys
import os
import time
import datetime
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from webdriver_manager.chrome import ChromeDriverManager

# ==========================================
# 設定エリア
# ==========================================
DEFAULT_LOGIN_URL = "https://dailycheck.tc-extsys.jp/tcrappsweb/web/login/tawLogin.html"
ROUTINE_STATION_URL = "https://dailycheck.tc-extsys.jp/tcrappsweb/web/routineStation.html"

TMA_ID = "0030-927583"
TMA_PW = "Ccj-222223"
EVIDENCE_DIR = "evidence"

# ==========================================
# 共通関数群
# ==========================================
def get_chrome_driver():
    options = Options()
    options.add_argument('--headless') # GitHub Actions上では必須
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-gpu')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36')
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def take_screenshot(driver, name):
    if not os.path.exists(EVIDENCE_DIR):
        os.makedirs(EVIDENCE_DIR)
    timestamp = datetime.datetime.now().strftime('%H%M%S')
    filename = f"{EVIDENCE_DIR}/{name}_{timestamp}.png"
    try:
        driver.save_screenshot(filename)
        print(f"   [写] 保存: {filename}")
    except:
        print("   [写] 撮影失敗")

def click_strict(driver, selector_str, timeout=30):
    """汎用クリック関数 (Timeout: 30s)"""
    by_method = By.XPATH if selector_str.startswith("/") or selector_str.startswith("(") else By.CSS_SELECTOR
    try:
        el = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by_method, selector_str)))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        time.sleep(0.5)
        el.click()
        print(f"   [OK] Click: {selector_str}")
    except Exception as e:
        take_screenshot(driver, "ERROR_ClickFailed")
        raise Exception(f"クリック不可 (Timeout): {selector_str}") from e

def input_strict(driver, selector_str, value):
    """入力関数 (Timeout: 30s)"""
    by_method = By.XPATH if selector_str.startswith("/") else By.CSS_SELECTOR
    try:
        el = WebDriverWait(driver, 30).until(EC.visibility_of_element_located((by_method, selector_str)))
        el.clear()
        el.send_keys(str(value))
        print(f"   [OK] Input: {value} -> {selector_str}")
    except Exception as e:
        take_screenshot(driver, "ERROR_InputFailed")
        raise Exception(f"入力失敗 (Timeout): {selector_str}") from e

def handle_popups(driver):
    """ボタン押下後のポップアップ処理セット（確認ダイアログ等）"""
    try:
        confirm_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.ID, "posupMessageConfirmOk"))
        )
        print("   確認ポップアップ検知 -> 「OK/完了」をクリック")
        driver.execute_script("arguments[0].click();", confirm_btn)
        time.sleep(1)
    except:
        pass 

# ==========================================
# 予約処理 (修正版：3ステップ遷移対応)
# ==========================================
def reserve_vehicle(driver, station, plate, reservation_time):
    print(f"\n--- [処理開始] 新規予約: ST {station} / 車両 {plate} / 日時 {reservation_time} ---")
    
    date_part, time_part = reservation_time.split(" ")
    hour_part, minute_part = time_part.split(":")
    
    wait = WebDriverWait(driver, 15)
    
    # ----------------------------------------------------
    # STEP 1: 巡回ST管理画面で対象ステーションをクリック
    # ----------------------------------------------------
    driver.get(ROUTINE_STATION_URL)
    print("   [STEP 1] 巡回ST管理画面でステーションを検索中...")
    
    station_found = False
    while True:
        # aタグの中に指定のステーション名を持つspanがあるか探す
        station_links = driver.find_elements(By.XPATH, f"//a[.//span[contains(@class, 'assignStationNm') and contains(text(), '{station}')]]")
        
        if station_links:
            print(f"   対象ステーション '{station}' を発見しました。車両一覧へ遷移します。")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", station_links[0])
            time.sleep(0.5)
            station_links[0].click()
            station_found = True
            break
        else:
            # 次のページへ (id="assignNextPageBtn" をクリック)
            next_buttons = driver.find_elements(By.XPATH, "//a[@id='assignNextPageBtn']")
            if next_buttons and next_buttons[0].is_displayed():
                print("   現在のページに対象STがないため、次のページへ遷移します。")
                driver.execute_script("arguments[0].click();", next_buttons[0])
                time.sleep(2) # ページ遷移待ち
            else:
                take_screenshot(driver, "ERROR_StationNotFound")
                raise Exception(f"エラー: 対象ステーション '{station}' が見つかりませんでした。")
                
    if not station_found:
        return

    # ----------------------------------------------------
    # STEP 2: 車両一覧画面で黄色い「予約」ボタンをクリック
    # ----------------------------------------------------
    print(f"   [STEP 2] 車両一覧画面で対象車両 '{plate}' の予約ボタンを検索中...")
    time.sleep(2) # 画面遷移の確実な待機
    
    # 対象の車両ナンバーが画面内に表示されるまで待機
    wait.until(EC.presence_of_element_located((By.XPATH, f"//*[contains(text(), '{plate}')]")))
    
    # 汎用的に対象の車両を含むブロック（行やリスト）を探し、その中の予約ボタンをクリックする
    blocks = driver.find_elements(By.XPATH, f"//*[contains(text(), '{plate}')]/ancestor::*[position()<=3]")
    reserve_button = None
    
    for block in blocks:
        try:
            btns = block.find_elements(By.XPATH, ".//button[contains(text(), '予約') or contains(@class, 'btn')] | .//a[contains(text(), '予約') or contains(@class, 'btn')]")
            for btn in btns:
                if "予約" in btn.text:
                    reserve_button = btn
                    break
        except:
            continue
        if reserve_button:
            break
            
    if reserve_button:
        print(f"   対象車両 '{plate}' の予約ボタンを発見しました。予約入力画面へ遷移します。")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", reserve_button)
        time.sleep(0.5)
        reserve_button.click()
    else:
        take_screenshot(driver, "ERROR_VehicleNotFound")
        raise Exception(f"エラー: 車両 '{plate}' またはその予約ボタンが見つかりませんでした。")

    # ----------------------------------------------------
    # STEP 3: 予約入力画面 (プルダウン操作)
    # ----------------------------------------------------
    print("   [STEP 3] 予約入力画面の読み込みを待機しています...")
    try:
        # 日付選択のプルダウンが表示されるまで待機
        use_date_element = wait.until(EC.presence_of_element_located((By.XPATH, "//select[contains(@name, 'Date') or contains(@id, 'Date') or contains(@name, 'date')]")))
        
        # 1. 日付
        select_date = Select(use_date_element)
        select_date.select_by_value(date_part)
        
        # 2. 時間(時)
        select_hour = Select(driver.find_element(By.XPATH, "//select[contains(@name, 'Hour') or contains(@id, 'Hour') or contains(@name, 'hour')]"))
        select_hour.select_by_value(hour_part)
        
        # 3. 時間(分)
        select_minute = Select(driver.find_element(By.XPATH, "//select[contains(@name, 'Minute') or contains(@id, 'Minute') or contains(@name, 'minute')]"))
        select_minute.select_by_value(minute_part)
        
        # 4. 【超重要】予約時間を15分に変更
        print("   【重要】予約時間をデフォルトの30分から15分に変更します。")
        select_duration = Select(driver.find_element(By.XPATH, "//select[contains(@name, 'Time') or contains(@id, 'Time') or contains(@name, 'duration') or contains(@name, 'useTime')]"))
        try:
            select_duration.select_by_value("15")
        except:
            select_duration.select_by_visible_text("15分")
        
        # 5. 確定ボタンのクリック
        print("   予約内容を確定します。")
        submit_button = driver.find_element(By.XPATH, "//button[contains(text(), '確認') or contains(text(), '確定') or contains(text(), '登録')]")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_button)
        time.sleep(0.5)
        submit_button.click()
        
        time.sleep(3)
        handle_popups(driver) # モーダルが出る場合に対応
        print("   [OK] 予約処理が完了しました。")
        take_screenshot(driver, "SUCCESS_ReservationCompleted")

    except Exception as e:
        print(f"   [エラー] 予約入力中の処理に失敗しました: {e}")
        take_screenshot(driver, "ERROR_ReservationInput")
        raise e

# ==========================================
# メイン処理
# ==========================================
def main():
    print("=== TMA Auto Reservation System Start ===")

    if len(sys.argv) < 2:
        print("Error: No payload provided.")
        sys.exit(1)
    
    try:
        # JSON形式の引数を受け取る
        payload_str = sys.argv[1]
        data = json.loads(payload_str)
        target_station = data.get('station', '大和テストステーション')
        target_plate = data.get('plate', '品川500あ1234')
        reservation_time = data.get('reservation_time', '2026-02-24 10:30')
        print(f"Target -> ST: {target_station}, Plate: {target_plate}, Time: {reservation_time}")
    except Exception as e:
        print(f"Error parsing payload: {e}")
        sys.exit(1)

    driver = get_chrome_driver()

    try:
        # [1] ログイン (既存の堅牢なロジックをそのまま使用)
        print("\n--- [1] ログイン ---")
        driver.get(DEFAULT_LOGIN_URL)
        id_parts = TMA_ID.split("-")
        input_strict(driver, "#cardNo1", id_parts[0])
        input_strict(driver, "#cardNo2", id_parts[1])
        input_strict(driver, "#password", TMA_PW)
        click_strict(driver, ".btn-primary")
        
        # ログイン完了の待機
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "main")))
            print("   ログインに成功しました。")
        except:
            pass
            
        # [2] 予約処理の実行 (ステーション選択 → 車両選択 → 予約入力)
        reserve_vehicle(driver, target_station, target_plate, reservation_time)

        print("\n=== SUCCESS: 全工程完了 ===")
        sys.exit(0)

    except Exception as e:
        print(f"\n[!!!] CRITICAL ERROR [!!!]\n{e}")
        take_screenshot(driver, "FATAL_ERROR")
        sys.exit(1)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
