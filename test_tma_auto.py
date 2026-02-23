import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select

# ==========================================
# TMA予約自動化 テスト用スクリプト
# ==========================================

def cancel_reservation(driver, wait, plate):
    """
    1. 予約履歴画面で指定の車両（plate）を検索し、キャンセルする
    """
    print(f"【キャンセル処理開始】対象車両: {plate}")
    
    # TODO: 予約履歴画面のURLを指定してください
    reserve_history_url = "https://dailycheck.tc-extsys.jp/tcrappsweb/web/reserveHistory.html"
    driver.get(reserve_history_url)
    
    while True:
        # テーブルが読み込まれるのを待機 (IDやクラス名は実際のHTMLに合わせて調整してください)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        
        # 画面内の全行（tr）を取得
        rows = driver.find_elements(By.XPATH, "//table//tr")
        found = False
        
        for row in rows:
            if plate in row.text:
                print(f"対象車両 {plate} を発見しました。キャンセルを実行します。")
                # 白い「× 取消」ボタンをクリック (クラス名やテキストは実際のHTMLに合わせる)
                # 例: class="submit-btn" や テキストが "取消" を含むボタン
                cancel_button = row.find_element(By.XPATH, ".//*[contains(text(), '取消') or contains(@class, 'submit-btn')]")
                cancel_button.click()
                found = True
                break
        
        if found:
            # モーダル（確認ダイアログ）の出現を待機して「OK」をクリック
            # id="posupMessageConfirm_OK" や モーダル内のOKボタンを指定
            ok_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'OK') or contains(text(), 'はい')]")))
            ok_button.click()
            print("キャンセル確認ダイアログの「OK」をクリックしました。")
            time.sleep(2) # 処理完了待ち
            break
        else:
            # 現在のページに見つからない場合、「次へ」ボタンを探してクリック
            # ※「次へ」ボタンが無い、または非活性の場合はループ終了
            next_buttons = driver.find_elements(By.XPATH, "//a[contains(text(), '次へ') or contains(text(), '＞')]")
            if next_buttons and next_buttons[0].is_displayed():
                print("現在のページに対象車両がないため、次のページへ遷移します。")
                next_buttons[0].click()
                time.sleep(2) # ページ遷移待ち
            else:
                print(f"エラー: キャンセル対象の車両 {plate} が見つかりませんでした。")
                break


def reserve_vehicle(driver, wait, station, plate, reservation_time):
    """
    2. 巡回ST管理画面で指定のステーション・車両を検索し、予約を入れる
    reservation_time 例: "2026-02-24 10:30"
    """
    print(f"【予約処理開始】ステーション: {station}, 車両: {plate}, 予約日時: {reservation_time}")
    
    # 予約日時を 分割 (YYYY-MM-DD と HH, MM)
    # ※フォーマットが違う場合はここのパース処理を変更してください
    date_part, time_part = reservation_time.split(" ")
    hour_part, minute_part = time_part.split(":")
    
    # TODO: 巡回ST管理画面のURLを指定してください
    routine_station_url = "https://dailycheck.tc-extsys.jp/tcrappsweb/web/routineStation.html"
    driver.get(routine_station_url)
    
    while True:
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        rows = driver.find_elements(By.XPATH, "//table//tr")
        found = False
        
        for row in rows:
            # ステーション名と車両ナンバーが両方含まれている行を探す
            if station in row.text and plate in row.text:
                print(f"対象ステーション {station} / 車両 {plate} を発見しました。予約画面へ遷移します。")
                # 黄色い「予約」ボタンをクリック
                reserve_button = row.find_element(By.XPATH, ".//*[contains(text(), '予約')]")
                reserve_button.click()
                found = True
                break
        
        if found:
            break
        else:
            # 「次へ」ボタンでページ送り (1ページ50件、最大3ページ想定)
            next_buttons = driver.find_elements(By.XPATH, "//a[contains(text(), '次へ') or contains(text(), '＞')]")
            if next_buttons and next_buttons[0].is_displayed():
                print("現在のページに対象が見つからないため、次のページへ遷移します。")
                next_buttons[0].click()
                time.sleep(2)
            else:
                print(f"エラー: 予約対象のステーション {station} / 車両 {plate} が見つかりませんでした。")
                return

    # --- 巡回予約画面 (リロード後) ---
    print("予約画面の読み込みを待機しています...")
    # 予約画面特有の要素（例えば日付のプルダウン）が出るまで待機
    # 以下の name 属性は仮のものです。実際のHTMLに合わせて変更してください。
    use_date_element = wait.until(EC.presence_of_element_located((By.XPATH, "//select[contains(@name, 'Date') or contains(@id, 'Date')]")))
    
    # 1. 利用開始日の入力（プルダウン）
    select_date = Select(use_date_element)
    select_date.select_by_value(date_part) # 例: "2026-02-24"
    
    # 2. 利用開始 時間(時) の入力（プルダウン）
    select_hour = Select(driver.find_element(By.XPATH, "//select[contains(@name, 'Hour') or contains(@id, 'Hour')]"))
    select_hour.select_by_value(hour_part)
    
    # 3. 利用開始 時間(分) の入力（プルダウン）
    select_minute = Select(driver.find_element(By.XPATH, "//select[contains(@name, 'Minute') or contains(@id, 'Minute')]"))
    select_minute.select_by_value(minute_part)
    
    # 4. 【超重要】予約時間（利用時間）を 30分 から 15分 に変更する
    print("【重要】予約時間をデフォルトの30分から15分に変更します。")
    select_duration = Select(driver.find_element(By.XPATH, "//select[contains(@name, 'Time') or contains(@id, 'Time') or contains(@name, 'duration')]"))
    # value="15" なのか、テキストが "15分" なのかは要確認
    try:
        select_duration.select_by_value("15")
    except:
        select_duration.select_by_visible_text("15分")
    
    # 5. 確定ボタンのクリック
    print("予約内容を確定します。")
    submit_button = driver.find_element(By.XPATH, "//button[contains(text(), '確認') or contains(text(), '確定') or contains(text(), '登録')]")
    submit_button.click()
    
    # 完了画面または完了ダイアログの待機 (必要に応じて)
    time.sleep(3)
    print("予約処理が完了しました。")


def main():
    # テスト用データ (GASから受け取る想定のデータ)
    test_station = "大和テストステーション"
    test_plate = "品川500あ1234"
    test_reservation_time = "2026-02-24 10:30"
    
    # WebDriverの初期化 (Chromeを想定)
    options = webdriver.ChromeOptions()
    # options.add_argument('--headless') # 動作確認中はheadlessを外して目視確認するのを推奨
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 10) # 最大10秒待機
    
    try:
        # TODO: ここに既存の login_to_tma(driver, wait) のようなログイン処理を入れる
        # login_to_tma(driver, wait)
        print("ログイン処理をスキップまたは実行しました。")
        
        # 1. キャンセルのテスト
        cancel_reservation(driver, wait, test_plate)
        
        # 2. 予約のテスト
        reserve_vehicle(driver, wait, test_station, test_plate, test_reservation_time)
        
    finally:
        print("テスト終了。ブラウザを閉じます。")
        driver.quit()

if __name__ == "__main__":
    main()
