import sys
import os
import time
import datetime
import json
import urllib.request
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
CANCEL_MAX_LOOP = 130

TMA_ID = os.environ.get("TMA_ID", "")
# PWは定期的にmode1/mode2で切り替わるため、実行時にpw_modeで指定する
PW_TABLE = {
    "mode1": os.environ.get("TMA_PW_MODE1", ""),
    "mode2": os.environ.get("TMA_PW_MODE2", ""),
}
EVIDENCE_DIR = "evidence"

# ==========================================
# 共通関数群
# ==========================================
def get_chrome_driver():
    # TMA-Auto-Input / yoyakuLong と同じ、実績のあるオプション構成に統一
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

def save_page_source(driver, name):
    """診断用: 現在のページHTMLをevidenceに保存"""
    if not os.path.exists(EVIDENCE_DIR):
        os.makedirs(EVIDENCE_DIR)
    timestamp = datetime.datetime.now().strftime('%H%M%S')
    filename = f"{EVIDENCE_DIR}/{name}_{timestamp}.html"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"   [HTML] 保存: {filename}")
    except Exception as e:
        print(f"   [HTML] 保存失敗: {e}")

def xpath_literal(s):
    """XPath用の文字列リテラル化（ステーション名に ' や " が含まれても壊れないようにする）"""
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = s.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"

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

def login_(driver, password):
    """ログイン処理"""
    print("\n--- [1] ログイン ---")
    driver.get(DEFAULT_LOGIN_URL)
    id_parts = TMA_ID.split("-")
    input_strict(driver, "#cardNo1", id_parts[0])
    input_strict(driver, "#cardNo2", id_parts[1])
    input_strict(driver, "#password", password)
    click_strict(driver, ".btn-primary")

    # ログイン成功判定: <main>タグの有無だけでは認証エラー画面でも素通りしてしまうため、
    # ログイン後の共通ヘッダーにしか存在しない「ログアウト」ボタンの存在で判定する
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='submit' and @value='ログアウト']"))
        )
        print("   ログインに成功しました。")
    except:
        take_screenshot(driver, "ERROR_LoginFailed")
        raise Exception("ログインに失敗しました（PASS/pw_modeが正しくない可能性があります）")

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
        station_links = driver.find_elements(By.XPATH, f"//a[.//span[contains(@class, 'assignStationNm') and contains(text(), {xpath_literal(station)})]]")
        
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

    print("   [STEP 2-a] 車両一覧ページのHTMLを保存します（検索処理を行う前）。")
    save_page_source(driver, "STEP2_VehicleListPage")

    # 対象の車両ナンバーが画面内に表示されるまで待機
    print("   [STEP 2-b] 対象車両ナンバーの出現を待機中...")
    # 画面表示は「多摩 503 ワ 1661」のようにスペース区切りのため、
    # DOM側のテキストからスペース（半角・全角）を除去してから比較する
    plate_xpath = f"//*[contains(translate(text(), ' 　', ''), {xpath_literal(plate)})]"
    wait.until(EC.presence_of_element_located((By.XPATH, plate_xpath)))
    print("   [STEP 2-c] 対象車両ナンバーを検出しました。")

    # 対象車両を囲む「car-list-box」（1台分の情報だけを含む最小単位）を直接特定する。
    # 以前は ancestor::*[position()<=3] で祖先3階層をまとめて取得していたが、
    # Seleniumが返す順序は外側の要素が先になるため、3階層目（最も外側）が
    # 「STの全車両を含むリスト全体」に達してしまい、その中の最初の予約リンク
    # （＝ドキュメント順で先に出現する別車両のリンク）を誤ってクリックする不具合があった。
    # car-list-box要素はちょうど1台分のみを囲むため、これをピンポイントに取得する。
    print("   [STEP 2-d] 対象車両を囲む car-list-box を特定中...")
    reserve_button = None
    try:
        car_block = driver.find_element(By.XPATH, f"({plate_xpath}/ancestor::div[contains(@class, 'car-list-box')])[1]")
        btns = car_block.find_elements(By.XPATH, ".//span[contains(@class, 'link-btn')]/a[contains(., '予約')] | .//button[contains(., '予約')]")
        if btns:
            reserve_button = btns[0]
            print("   [STEP 2-e] 対象車両の予約ボタンを発見しました。")
    except Exception as e:
        print(f"   [STEP 2-f] car-list-box特定中にエラー: {e}")

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
        print(f"   [STEP 3-a] 日付プルダウンを選択します: {date_part}")
        select_date = Select(use_date_element)
        select_date.select_by_value(date_part)

        # TMA側は日付選択直後、まだ元の時刻（現在時刻付近）のタイムラインを表示しており、
        # 時刻プルダウンの選択肢がJSで非同期に再生成される可能性があるため、
        # 実際の反映内容をHTMLで記録した上で少し待機してから時刻を操作する
        print("   [STEP 3-b] 日付選択直後のHTMLを保存します（時刻プルダウン操作前）。")
        save_page_source(driver, "STEP3_AfterDateSelect")
        time.sleep(1.5)

        # 2. 時間(時)
        print(f"   [STEP 3-c] 時プルダウンを選択します: {hour_part}")
        select_hour = Select(driver.find_element(By.XPATH, "//select[contains(@name, 'Hour') or contains(@id, 'Hour') or contains(@name, 'hour')]"))
        select_hour.select_by_value(hour_part)

        print("   [STEP 3-d] 時選択後のHTMLを保存します（分プルダウン操作前）。")
        save_page_source(driver, "STEP3_AfterHourSelect")
        time.sleep(1.0)

        # 3. 時間(分)
        print(f"   [STEP 3-e] 分プルダウンを選択します: {minute_part}")
        select_minute = Select(driver.find_element(By.XPATH, "//select[contains(@name, 'Minute') or contains(@id, 'Minute') or contains(@name, 'minute')]"))
        select_minute.select_by_value(minute_part)
        
        # 4. 【超重要】予約時間を15分に変更
        print("   【重要】予約時間をデフォルトの30分から15分に変更します。")
        select_duration = Select(driver.find_element(By.XPATH, "//select[contains(@name, 'Time') or contains(@id, 'Time') or contains(@name, 'duration') or contains(@name, 'useTime') or contains(@name, 'Priod') or contains(@id, 'Priod')]"))
        try:
            select_duration.select_by_value("15")
        except:
            select_duration.select_by_visible_text("15分")
        
        # 5. 確定ボタンのクリック
        print("   予約内容を確定します。")
        submit_button = driver.find_element(By.XPATH, "//button[contains(text(), '確認') or contains(text(), '確定') or contains(text(), '登録')] | //input[@type='submit' and (contains(@value, '確認') or contains(@value, '確定') or contains(@value, '登録'))]")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_button)
        time.sleep(0.5)
        submit_button.click()
        
        time.sleep(3)
        handle_popups(driver) # モーダルが出る場合に対応

        # 成功判定: エラー時（例: 「予約できない時間帯が含まれています」）は
        # 送信前と同じ「登録」ボタンが残った確認画面のまま留まる。これまでは
        # 例外が起きないため無条件に成功と判定していたが、実際には登録されて
        # いないケースがあったため、送信後も同じボタンが残っているかで判定する。
        still_on_form = driver.find_elements(By.XPATH, "//input[@type='submit' and contains(@value, '登録')] | //button[contains(text(), '登録')]")
        if still_on_form:
            save_page_source(driver, "ERROR_StillOnReservationForm")
            take_screenshot(driver, "ERROR_ReservationRejected")
            raise Exception("送信後も予約フォームの「登録」ボタンが残っています。画面上にエラーメッセージが出ている可能性があります（evidence参照）。")

        print("   [OK] 予約処理が完了しました。")
        take_screenshot(driver, "SUCCESS_ReservationCompleted")

    except Exception as e:
        print(f"   [エラー] 予約入力中の処理に失敗しました: {e}")
        take_screenshot(driver, "ERROR_ReservationInput")
        raise e

# ==========================================
# 全件予約取消処理
# ==========================================
def cancel_all_reservations(driver):
    print("\n--- [処理開始] 全件予約取消 ---")
    count = 0

    # 最初の1回だけ、実際の「予約履歴」リンクをクリックして遷移する（直接URLアクセスはしない）。
    # このリンクは<main>の外（ヘッダーのハンバーガーメニュー内）にあり、メニュー未展開時は
    # 画面上非表示のため、通常クリックではなくJS経由でクリックする。
    reserve_link = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.XPATH, "//a[contains(@class,'nav-link') and contains(@href,'reserveHistory')]"))
    )
    driver.execute_script("arguments[0].click();", reserve_link)
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "reserveList")))

    for i in range(CANCEL_MAX_LOOP):
        boxes = driver.find_elements(By.XPATH, "//div[@id='reserveList']//div[contains(@class, 'car-list-box')]")

        if not boxes:
            print(f"   取消対象なし。処理を終了します。（合計 {count} 件取消）")
            break

        try:
            # リロード検知用に、今のreserveList要素を控えておく
            old_list_el = driver.find_element(By.ID, "reserveList")

            cancel_btn = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "(//div[@id='reserveList']//div[contains(@class, 'car-list-box')])[1]//button[contains(@class, 'submit-btn') and contains(text(), '取消')]"))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", cancel_btn)
            time.sleep(0.3)
            cancel_btn.click()
            handle_popups(driver)

            # 取消確定後はフォーム送信によりページが自動リロードされる。
            # 直接URLへ再アクセスはせず、古い要素が失われて新しい一覧が描画されるのを待つ。
            WebDriverWait(driver, 20).until(EC.staleness_of(old_list_el))
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "reserveList")))

            count += 1
            print(f"   [OK] {count}件目を取消しました。")
        except Exception as e:
            take_screenshot(driver, "ERROR_CancelFailed")
            raise Exception(f"取消処理中にエラーが発生しました（{count}件処理済み）") from e
    else:
        print(f"   [警告] ループ上限（{CANCEL_MAX_LOOP}回）に到達したため処理を終了します。（合計 {count} 件取消）")

    take_screenshot(driver, "SUCCESS_AllCancelled")
    print(f"   [OK] 全件取消処理が完了しました。（合計 {count} 件）")

# ==========================================
# リスト一括予約処理
# ==========================================
def post_callback(callback_url, token, row, status, message):
    """1件ごとの結果をGAS（全台予約管理メイン）へ送り、「自動予約用」シートG列に書き込ませる。
    送信に失敗しても予約処理自体は止めない。"""
    if not callback_url:
        return
    body = json.dumps({
        "action": "reportReserveResult",
        "token": token,
        "row": row,
        "status": status,
        "message": message,
    }).encode("utf-8")
    req = urllib.request.Request(
        callback_url, data=body, method="POST",
        headers={"Content-Type": "text/plain;charset=utf-8"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            res.read()
    except Exception as e:
        print(f"   [通知] GASへの結果送信に失敗しました（行{row}）: {e}")

def is_driver_alive(driver):
    try:
        _ = driver.title
        return True
    except Exception:
        return False

def reserve_list(driver, password, items, callback_url, token):
    """items: [{"r": 行番号, "st": ステーション, "pl": ナンバー, "t": "YYYY-MM-DD HH:MM"}, ...]
    1件失敗しても止めず、次の行へ進む。ブラウザが落ちた場合は再起動して再ログインする。"""
    total = len(items)
    print(f"\n--- [処理開始] リスト一括予約: {total}件 ---")
    ok_count = 0
    ng_list = []

    for i, item in enumerate(items, start=1):
        row = item.get("r")
        station = str(item.get("st", "")).strip()
        plate = str(item.get("pl", "")).strip()
        rtime = str(item.get("t", "")).strip()
        # GitHub Actionsのログで1件ごとに折りたたみ表示にする（::group:: / ::endgroup::）
        print(f"::group::[{i}/{total}] 行{row} {rtime} {station} {plate}")
        started = time.time()
        result_ok = False
        err_msg = ""

        try:
            if not is_driver_alive(driver):
                print("   ブラウザが停止していたため再起動して再ログインします。")
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = get_chrome_driver()
                login_(driver, password)

            reserve_vehicle(driver, station, plate, rtime)
            result_ok = True
        except Exception as e:
            err_msg = str(e).split("\n")[0][:150]
            print(f"   [NG] 行{row} の予約に失敗しました: {err_msg}")
        print("::endgroup::")

        # 折りたたみの外に、1件ごとの結果・所要時間・累計を表示する
        elapsed = int(time.time() - started)
        if result_ok:
            ok_count += 1
            post_callback(callback_url, token, row, "ok", "")
        else:
            ng_list.append((row, plate, err_msg))
            post_callback(callback_url, token, row, "ng", err_msg)
        status_label = "OK" if result_ok else f"NG（{err_msg}）"
        print(f"[{i}/{total}] {status_label} {elapsed}秒 / 累計 成功{ok_count}・失敗{len(ng_list)} / 残り{total - i}件")

    print(f"\n--- リスト一括予約 完了: 成功 {ok_count}件 / 失敗 {len(ng_list)}件（全{total}件） ---")
    for row, plate, msg in ng_list:
        print(f"   NG 行{row} {plate}: {msg}")
    return driver, ok_count, ng_list

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
        target_action = data.get('action', 'reserve')
        print(f"Action -> {target_action}")
    except Exception as e:
        print(f"Error parsing payload: {e}")
        sys.exit(1)

    pw_mode = data.get('pw_mode')
    if pw_mode not in PW_TABLE:
        print(f"Error: pw_modeは 'mode1' か 'mode2' のいずれかを指定してください（受信値: {pw_mode}）")
        sys.exit(1)
    password = PW_TABLE[pw_mode]

    driver = get_chrome_driver()
    exit_code = 0

    try:
        # [1] ログイン
        login_(driver, password)

        # [2] アクションに応じた処理の実行
        if target_action == 'reserve':
            target_station = data.get('station', '大和テストステーション')
            target_plate = data.get('plate', '品川500あ1234')
            reservation_time = data.get('reservation_time', '2026-02-24 10:30')
            print(f"Target -> ST: {target_station}, Plate: {target_plate}, Time: {reservation_time}")
            reserve_vehicle(driver, target_station, target_plate, reservation_time)
        elif target_action == 'reserve_list':
            items = data.get('items') or []
            if not items:
                raise Exception("予約リスト（items）が空です")
            driver, ok_count, ng_list = reserve_list(
                driver, password, items,
                data.get('callback_url', ''), data.get('token', '')
            )
            # 1件でも失敗があればジョブを失敗扱い（赤表示）にする（成功分はTMAに登録済み）
            if ng_list:
                exit_code = 1
        elif target_action == 'cancel_all':
            cancel_all_reservations(driver)
        else:
            raise Exception(f"未対応のactionです: {target_action}")

        if exit_code == 0:
            print("\n=== SUCCESS: 全工程完了 ===")
        else:
            print("\n=== 完了（失敗あり） ===")
        sys.exit(exit_code)

    except Exception as e:
        print(f"\n[!!!] CRITICAL ERROR [!!!]\n{e}")
        take_screenshot(driver, "FATAL_ERROR")
        sys.exit(1)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
