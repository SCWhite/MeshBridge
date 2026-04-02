import time
import config
import threading
import os
from pathlib import Path

# 可選的套件引入（如果未安裝則功能會受限）
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# 裝置 ID 對應到顏色模式與螢幕尺寸的常數
DEVICE_COLOR_MODE_MAPPING = {
    'weshare-epd7in3e': {
        'color_mode': 'full_color',
        'screen_width': 800,
        'screen_height': 480
    },
    'weshare-epd7in5_V2': {
        'color_mode': 'mono',
        'screen_width': 800,
        'screen_height': 480
    }
}

SUPPORTED_COLOR_MODES = {'mono', 'full_color', 'dual_rb'}
SUPPORTED_LAYOUTS = {'standard_qr', 'photo_qr'}
SUPPORTED_CANVAS = {'w7', 'p7'}

# ePaper 更新執行保護設定
# ❗ Waveshare 電子紙建議刷新間隔至少 180 秒，過於頻繁的刷新會損傷膜片
EPAPER_UPDATE_MIN_INTERVAL = 180  # 兩次呼叫最小間隔（秒）

# ❗ 至少每 24 小時做一次刷新，長期不刷新可能導致殘影或損傷
EPAPER_PERIODIC_REFRESH_INTERVAL = 24 * 60 * 60  # 24 小時（秒）

# ePaper 圖檔儲存路徑
EPAPER_IMAGE_DIR = './epaper_images'
EPAPER_TEMP_SCREENSHOT = 'temp_screenshot.png'
EPAPER_OUTPUT_IMAGE = 'epaper_display.png'

# ePaper 更新狀態追蹤
_epaper_last_update_time = 0
_epaper_update_lock = threading.Lock()
_epaper_is_updating = False
_epaper_periodic_timer = None
_epaper_pending_update = False
_epaper_pending_timer = None

# 照片輪播狀態追蹤
SUPPORTED_PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'}
_photo_file_list = []
_photo_current_index = 0
_photo_cycle_timer = None

def get_photo_file_list():
    """讀取 EPAPER_PHOTO_FOLDER 中的圖片檔案清單（排序後回傳）"""
    folder = getattr(config, 'EPAPER_PHOTO_FOLDER', 'photos')
    if not os.path.isabs(folder):
        basedir = os.path.dirname(os.path.realpath(__file__))
        folder = os.path.join(basedir, folder)

    files = []
    if os.path.isdir(folder):
        for f in sorted(os.listdir(folder)):
            if Path(f).suffix.lower() in SUPPORTED_PHOTO_EXTENSIONS:
                files.append(os.path.join(folder, f))
    return files

def get_current_photo_path():
    """取得目前應顯示的照片檔案路徑"""
    global _photo_file_list, _photo_current_index
    _photo_file_list = get_photo_file_list()
    if not _photo_file_list:
        return None
    _photo_current_index = _photo_current_index % len(_photo_file_list)
    return _photo_file_list[_photo_current_index]

def advance_photo_index():
    """切換到下一張照片"""
    global _photo_current_index, _photo_file_list
    _photo_file_list = get_photo_file_list()
    if _photo_file_list:
        _photo_current_index = (_photo_current_index + 1) % len(_photo_file_list)
        print(f'[ePaper] 照片輪播：切換到第 {_photo_current_index + 1}/{len(_photo_file_list)} 張')

def _photo_cycle_callback():
    """照片輪播計時器回呼：切換到下一張照片並觸發 ePaper 更新"""
    advance_photo_index()
    update_epaper_display()
    _start_photo_cycle_timer()

def _start_photo_cycle_timer():
    """啟動照片輪播計時器"""
    global _photo_cycle_timer
    duration = getattr(config, 'EPAPER_PHOTO_DURATION', 15)
    duration = max(duration, 15)  # 最少 15 分鐘
    interval_seconds = duration * 60

    if _photo_cycle_timer is not None:
        _photo_cycle_timer.cancel()

    _photo_cycle_timer = threading.Timer(interval_seconds, _photo_cycle_callback)
    _photo_cycle_timer.daemon = True
    _photo_cycle_timer.start()
    print(f'[ePaper] 照片輪播計時器已啟動（間隔 {duration} 分鐘）')

def stop_photo_cycle_timer():
    """停止照片輪播計時器"""
    global _photo_cycle_timer
    if _photo_cycle_timer is not None:
        _photo_cycle_timer.cancel()
        _photo_cycle_timer = None

def capture_epaper_screenshot(url, width, height, color_mode):
    """
    使用 chromium-browser 擷取網頁截圖並處理為 ePaper 顯示格式
    
    Args:
        url: 要截圖的網頁 URL
        width: 目標寬度
        height: 目標高度
        color_mode: 顏色模式 ('mono', 'full_color', 'dual_rb')
    
    Returns:
        str: 處理後的圖檔路徑，失敗則返回 None
    """
    # 檢查必要套件是否可用
    if not PIL_AVAILABLE:
        print('[ePaper] 錯誤：Pillow 未安裝，無法處理圖片')
        return None
    
    try:
        # 確保圖檔目錄存在
        image_dir = Path(EPAPER_IMAGE_DIR)
        image_dir.mkdir(exist_ok=True)
        
        temp_path = image_dir / EPAPER_TEMP_SCREENSHOT
        output_path = image_dir / EPAPER_OUTPUT_IMAGE
        
        
        # 使用 chromium 命令行工具擷取截圖
        import subprocess
        import shutil
        
        # 尋找可用的 Chromium 命令（支援不同系統）
        chromium_bin = None
        for cmd in ['chromium', 'chromium-browser', 'google-chrome']:
            if shutil.which(cmd):
                chromium_bin = cmd
                break
        
        if not chromium_bin:
            print(f'[ePaper] 錯誤：找不到 Chromium 瀏覽器')
            print(f'[ePaper] 請安裝: sudo apt-get install chromium')
            return None
        
        # Chromium 截圖命令
        # 超取樣：以 2x 解析度渲染，之後再 LANCZOS 縮放回目標尺寸，提升文字清晰度
        scale_factor = 2
        viewport_width = width
        viewport_height = height + 100  # 增加額外高度以避免裁切
        
        chromium_cmd = [
            chromium_bin,
            '--headless=new',  # 使用新的 headless 模式
            '--disable-gpu',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-software-rasterizer',
            f'--window-size={viewport_width},{viewport_height}',
            '--hide-scrollbars',
            f'--force-device-scale-factor={scale_factor}',  # 超取樣倍率
            '--disable-lcd-text',             # 禁用 LCD 子像素渲染（ePaper 非 LCD）
            '--font-render-hinting=medium',   # 啟用字體微調
            '--virtual-time-budget=5000',  # 給予 5 秒虛擬時間確保渲染完成
            '--screenshot=' + str(temp_path),
            url
        ]
        
        
        try:
            # 設定環境變數以支援中文字型
            import os
            env = os.environ.copy()
            env['LANG'] = 'zh_TW.UTF-8'
            env['LC_ALL'] = 'zh_TW.UTF-8'
            
            # 執行命令，設定 60 秒超時
            result = subprocess.run(
                chromium_cmd,
                timeout=60,
                capture_output=True,
                text=True,
                env=env
            )
            
            if result.returncode == 0:
                pass
            else:
                print(f'[ePaper] Chromium 返回錯誤碼: {result.returncode}')
                if result.stderr:
                    print(f'[ePaper] 錯誤輸出: {result.stderr[:500]}')
            
            # 檢查檔案是否存在
            if temp_path.exists():
                pass
            else:
                print(f'[ePaper] 錯誤：截圖檔案不存在')
                return None
                
        except subprocess.TimeoutExpired:
            print(f'[ePaper] Chromium 截圖超時（60秒）')
            return None
        except FileNotFoundError:
            print(f'[ePaper] 錯誤：找不到 chromium-browser 命令')
            print(f'[ePaper] 請安裝: sudo apt-get install chromium-browser')
            return None
        except Exception as cmd_error:
            print(f'[ePaper] Chromium 命令執行失敗: {cmd_error}')
            import traceback
            traceback.print_exc()
            return None
        
        
        # 檢查暫存檔是否存在
        if not temp_path.exists():
            raise FileNotFoundError(f'暫存截圖檔案不存在: {temp_path}')
        
        # 使用 PIL 處理圖片
        img = Image.open(temp_path)
        
        # 超取樣後縮放回目標尺寸
        if img.size != (width, height):
            # 先裁切掉多餘的高度（額外高度用於避免底部裁切）
            if img.width >= width and img.height >= height:
                img = img.crop((0, 0, img.width, int(height * (img.width / width))))
            # LANCZOS 縮放回目標尺寸，保留最佳文字邊緣品質
            img = img.resize((width, height), Image.Resampling.LANCZOS)
        
        # 根據顏色模式處理圖片
        if color_mode == 'mono':
            # 轉換為黑白（1-bit）
            # 先轉灰階，銳化後再用 Floyd-Steinberg 誤差擴散抖動，保留文字邊緣細節
            from PIL import ImageFilter
            img = img.convert('L')  # 先轉灰階
            img = img.filter(ImageFilter.SHARPEN)  # 銳化，讓文字邊緣更清晰
            img = img.convert('1')  # Floyd-Steinberg dithering（PIL 預設）
        elif color_mode == 'dual_rb':
            # 紅黑雙色模式（簡化處理：保留紅色和黑色）
            img = img.convert('RGB')
            pixels = img.load()
            for y in range(height):
                for x in range(width):
                    r, g, b = pixels[x, y]
                    # 判斷是否為紅色系
                    if r > 150 and g < 100 and b < 100:
                        pixels[x, y] = (255, 0, 0)  # 純紅
                    elif r + g + b < 384:  # 偏暗的顏色
                        pixels[x, y] = (0, 0, 0)  # 純黑
                    else:
                        pixels[x, y] = (255, 255, 255)  # 純白
        else:  # full_color
            # 保持全彩
            img = img.convert('RGB')
        
        # 儲存處理後的圖片
        img.save(output_path)
        print(f'[ePaper] 圖片處理完成，已儲存至: {output_path}')
        
        # 刪除暫存檔
        if temp_path.exists():
            temp_path.unlink()
        
        return str(output_path)
        
    except Exception as e:
        print(f'[ePaper] 截圖處理失敗: {e}')
        import traceback
        traceback.print_exc()
        return None

def parse_epaper_config():
    """
    解析 ePaper 設定參數
    
    Returns:
        dict: 包含 device_id, color_mode, screen_width, screen_height, layout, canvas 的字典
        None: 如果參數錯誤
    """
    # 讀取 EPAPER_MODULE_ID
    device_id = getattr(config, 'EPAPER_MODULE_ID', '')
    if not device_id or device_id.strip() == '':
        return None
    
    # 從 DEVICE_COLOR_MODE_MAPPING 查找對應的 color_mode
    if device_id not in DEVICE_COLOR_MODE_MAPPING:
        print(f'[ePaper] 錯誤：不支援的裝置 ID ({device_id})')
        print(f'[ePaper] 支援的裝置：{", ".join(DEVICE_COLOR_MODE_MAPPING.keys())}')
        return None
    
    device_info = DEVICE_COLOR_MODE_MAPPING[device_id]
    color_mode = device_info['color_mode']
    screen_width = device_info['screen_width']
    screen_height = device_info['screen_height']
    
    # 讀取 EPAPER_DISPLAY_MODE
    display_mode = getattr(config, 'EPAPER_DISPLAY_MODE', 'standard_qr,w10')
    
    # 解析 layout 和 canvas
    if ',' in display_mode:
        layout, canvas = display_mode.split(',', 1)
        layout = layout.strip()
        canvas = canvas.strip()
    else:
        print(f'[ePaper] 錯誤：EPAPER_DISPLAY_MODE 格式不正確 ({display_mode})，應為 "layout,canvas"')
        return None
    
    # 驗證 layout 是否支援
    if layout not in SUPPORTED_LAYOUTS:
        print(f'[ePaper] 錯誤：不支援的佈局 ({layout})')
        print(f'[ePaper] 支援的佈局：{", ".join(SUPPORTED_LAYOUTS)}')
        return None
    
    # 驗證 canvas 是否支援
    if canvas not in SUPPORTED_CANVAS:
        print(f'[ePaper] 錯誤：不支援的畫布 ({canvas})')
        print(f'[ePaper] 支援的畫布：{", ".join(SUPPORTED_CANVAS)}')
        return None
    
    # 直式（portrait）畫布：將螢幕寬高互換
    if canvas.startswith('p'):
        screen_width, screen_height = screen_height, screen_width

    return {
        'device_id': device_id,
        'color_mode': color_mode,
        'screen_width': screen_width,
        'screen_height': screen_height,
        'layout': layout,
        'canvas': canvas
    }

def display_on_epaper(image_path, device_id):
    """
    將已處理的 PNG 圖檔傳送到 ePaper 硬體模組顯示
    
    Args:
        image_path: PNG 圖檔路徑
        device_id: 裝置 ID（來自 config.EPAPER_MODULE_ID）
    
    Returns:
        bool: 成功為 True，失敗為 False
    """
    print(f'[ePaper] display_on_epaper() 開始執行，device_id={device_id}')
    
    if device_id in ('weshare-epd7in3e', 'weshare-epd7in5_V2'):
        import subprocess
        import os

        # 透過 subprocess 執行 ePaper 更新，避免 eventlet monkey_patch 與 lgpio 衝突
        basedir = os.path.dirname(os.path.realpath(__file__))
        script = os.path.join(basedir, 'epaper_update.py')
        image_abs = os.path.join(basedir, image_path) if not os.path.isabs(image_path) else image_path
        python_bin = os.path.join(basedir, 'venv', 'bin', 'python3')
        if not os.path.exists(python_bin):
            python_bin = 'python3'

        print(f'[ePaper] 以 subprocess 執行電子紙更新...')
        try:
            result = subprocess.run(
                [python_bin, script, 'display', image_abs],
                capture_output=True, text=True, timeout=120, cwd=basedir
            )
            # 輸出子程序的 stdout/stderr
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    print(line)
            if result.stderr:
                for line in result.stderr.strip().split('\n'):
                    print(line)

            if result.returncode == 0:
                return True
            else:
                print(f'[ePaper] 子程序返回錯誤碼: {result.returncode}')
                return False
        except subprocess.TimeoutExpired:
            print('[ePaper] 子程序執行超時（120秒）')
            return False
        except Exception as e:
            print(f'[ePaper] 子程序執行失敗: {e}')
            return False
    else:
        print(f'[ePaper] 尚無對應 {device_id} 的硬體驅動程式')
        return False

def _do_epaper_update(epaper_config):
    """實際執行 ePaper 更新的工作函數（在獨立執行緒中執行）"""
    global _epaper_is_updating
    
    try:
        print(f'[ePaper] 進入 epaper 處理..')
        print(f'[ePaper] 裝置 ID: {epaper_config["device_id"]}')
        print(f'[ePaper] 顏色模式: {epaper_config["color_mode"]}')
        print(f'[ePaper] 螢幕尺寸: {epaper_config["screen_width"]}x{epaper_config["screen_height"]}')
        print(f'[ePaper] 佈局: {epaper_config["layout"]}')
        print(f'[ePaper] 畫布: {epaper_config["canvas"]}')
        
        # 組成 display_page_url
        display_page_url = f'/epaper?color_mode={epaper_config["color_mode"]}&layout={epaper_config["layout"]}&canvas={epaper_config["canvas"]}'
        print(f'[ePaper] 顯示頁面 URL: {display_page_url}')
        
        # 組成完整 URL（使用本機 localhost:80）
        full_url = f'http://localhost{display_page_url}'
        
        # 等待 Flask 應用程式就緒（最多重試 3 次）
        import urllib.request
        import urllib.error
        
        flask_ready = False
        max_retries = 3
        retry_delay = 2  # 秒
        
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen('http://localhost/', timeout=5) as response:
                    flask_ready = True
                    break
            except Exception as check_error:
                if attempt < max_retries - 1:
                    print(f'[ePaper] Flask 尚未就緒 (嘗試 {attempt + 1}/{max_retries}): {check_error}')
                    print(f'[ePaper] 等待 {retry_delay} 秒後重試...')
                    time.sleep(retry_delay)
                else:
                    print(f'[ePaper] 警告：Flask 應用程式仍無法訪問: {check_error}')
                    print(f'[ePaper] 跳過此次 ePaper 更新')
                    return  # 直接返回，不執行截圖
        
        if not flask_ready:
            print(f'[ePaper] 無法連接到 Flask，取消 ePaper 更新')
            return
        
        # 擷取網頁截圖並處理為 ePaper 格式
        image_path = capture_epaper_screenshot(
            url=full_url,
            width=epaper_config['screen_width'],
            height=epaper_config['screen_height'],
            color_mode=epaper_config['color_mode']
        )
        
        if image_path:
            print(f'[ePaper] ePaper 顯示圖檔已準備完成: {image_path}')
            success = display_on_epaper(image_path, epaper_config['device_id'])
            if success:
                print('[ePaper] epaper 處理完成..')
            else:
                print('[ePaper] epaper 硬體顯示失敗，圖檔已儲存可供手動檢視')
        else:
            print('[ePaper] epaper 處理失敗：無法生成顯示圖檔')
    finally:
        # 釋放執行鎖
        _epaper_is_updating = False

def _schedule_pending_update(delay_seconds):
    """
    記錄有待觸發的更新，並在 delay_seconds 秒後自動觸發一次。
    若已有排程中的待觸發計時器，則不重複排程（多次跳過只觸發一次）。
    """
    global _epaper_pending_update, _epaper_pending_timer

    _epaper_pending_update = True

    # 若已有計時器排程中，不重複建立
    if _epaper_pending_timer is not None and _epaper_pending_timer.is_alive():
        print(f'[ePaper] 已有待觸發的延遲更新排程，不重複排程')
        return

    print(f'[ePaper] 排程延遲更新，將在 {delay_seconds:.1f} 秒後自動觸發')
    _epaper_pending_timer = threading.Timer(delay_seconds, _pending_update_callback)
    _epaper_pending_timer.daemon = True
    _epaper_pending_timer.start()

def _pending_update_callback():
    """延遲計時器到期後的回呼，若仍有待觸發的更新則執行一次"""
    global _epaper_pending_update, _epaper_pending_timer

    _epaper_pending_timer = None

    if _epaper_pending_update:
        _epaper_pending_update = False
        print('[ePaper] 延遲更新計時器到期，觸發待處理的 ePaper 更新')
        update_epaper_display()
    else:
        print('[ePaper] 延遲更新計時器到期，但已無待處理的更新')

def update_epaper_display():
    """更新 ePaper 模組顯示內容（非阻塞，在背景執行緒執行）"""
    global _epaper_last_update_time, _epaper_is_updating
    
    # 解析設定參數
    epaper_config = parse_epaper_config()
    
    if epaper_config is None:
        print('[ePaper] 未使用epaper功能')
        return
    
    # 檢查是否有其他執行中
    if _epaper_is_updating:
        print('[ePaper] 已有更新執行中，跳過此次呼叫')
        return
    
    # 檢查時間間隔
    current_time = time.time()
    time_since_last_update = current_time - _epaper_last_update_time
    if _epaper_last_update_time > 0 and time_since_last_update < EPAPER_UPDATE_MIN_INTERVAL:
        remaining_time = EPAPER_UPDATE_MIN_INTERVAL - time_since_last_update
        print(f'[ePaper] 距離上次更新未滿 {EPAPER_UPDATE_MIN_INTERVAL} 秒（還需等待 {remaining_time:.1f} 秒），跳過此次呼叫')
        _schedule_pending_update(remaining_time)
        return
    
    # 設定執行狀態
    with _epaper_update_lock:
        _epaper_is_updating = True
        _epaper_last_update_time = current_time
    
    # 在背景執行緒中執行實際的更新工作
    print('[ePaper] 啟動背景執行緒進行 ePaper 更新...')
    update_thread = threading.Thread(
        target=_do_epaper_update,
        args=(epaper_config,),
        daemon=True,
        name='ePaperUpdateThread'
    )
    update_thread.start()

def clear_epaper_display():
    """
    將電子紙刷白（清屏）。
    ⚠ 長期不使用墨水屏時，應將屏幕刷白後再存放，避免殘影損壞膜片。
    """
    epaper_config = parse_epaper_config()
    if epaper_config is None:
        print('[ePaper] 未設定 ePaper 模組，跳過清屏')
        return False

    device_id = epaper_config['device_id']
    if device_id in ('weshare-epd7in3e', 'weshare-epd7in5_V2'):
        import subprocess
        import os

        basedir = os.path.dirname(os.path.realpath(__file__))
        script = os.path.join(basedir, 'epaper_update.py')
        python_bin = os.path.join(basedir, 'venv', 'bin', 'python3')
        if not os.path.exists(python_bin):
            python_bin = 'python3'

        print('[ePaper] 以 subprocess 執行電子紙清屏...')
        try:
            result = subprocess.run(
                [python_bin, script, 'clear'],
                capture_output=True, text=True, timeout=120, cwd=basedir
            )
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    print(line)
            if result.stderr:
                for line in result.stderr.strip().split('\n'):
                    print(line)

            if result.returncode == 0:
                return True
            else:
                print(f'[ePaper] 清屏子程序返回錯誤碼: {result.returncode}')
                return False
        except subprocess.TimeoutExpired:
            print('[ePaper] 清屏子程序執行超時（120秒）')
            return False
        except Exception as e:
            print(f'[ePaper] 清屏子程序執行失敗: {e}')
            return False
    else:
        print(f'[ePaper] 尚無對應 {device_id} 的清屏功能')
        return False

def _epaper_periodic_refresh_callback():
    """24 小時定期刷新回呼（在背景自動觸發）"""
    global _epaper_periodic_timer
    print(f'[ePaper] 定期刷新觸發（每 {EPAPER_PERIODIC_REFRESH_INTERVAL} 秒）')
    update_epaper_display()
    # 重新排程下一次定期刷新
    _epaper_periodic_timer = threading.Timer(
        EPAPER_PERIODIC_REFRESH_INTERVAL,
        _epaper_periodic_refresh_callback
    )
    _epaper_periodic_timer.daemon = True
    _epaper_periodic_timer.start()

def _epaper_initial_update():
    """啟動後延遲執行首次 ePaper 更新（等待 Flask 就緒）"""
    print('[ePaper] 首次啟動更新：等待 Flask 就緒...')
    update_epaper_display()

def start_epaper_periodic_refresh():
    """
    啟動 ePaper 功能：
    1. 延遲數秒後執行首次顯示更新（等待 Flask 就緒）
    2. 啟動 24 小時定期刷新計時器
    ⚠ Waveshare 建議至少每 24 小時刷新一次，防止長時間不刷新損壞膜片。
    應在應用程式啟動時呼叫一次。
    """
    global _epaper_periodic_timer

    epaper_config = parse_epaper_config()
    if epaper_config is None:
        print('[ePaper] 未設定 ePaper 模組或設定有誤，ePaper 功能停用')
        return

    if not PIL_AVAILABLE:
        print('[ePaper] 警告：Pillow 未安裝，ePaper 圖片處理功能將無法使用')
        print('[ePaper] 請執行: pip3 install Pillow')

    print(f'[ePaper] ✓ ePaper 功能已啟用')
    print(f'[ePaper]   裝置: {epaper_config["device_id"]}')
    print(f'[ePaper]   顏色模式: {epaper_config["color_mode"]}')
    print(f'[ePaper]   螢幕尺寸: {epaper_config["screen_width"]}x{epaper_config["screen_height"]}')
    print(f'[ePaper]   顯示模式: {epaper_config["layout"]},{epaper_config["canvas"]}')
    print(f'[ePaper]   刷新最小間隔: {EPAPER_UPDATE_MIN_INTERVAL} 秒')

    # 取消已有的計時器
    if _epaper_periodic_timer is not None:
        _epaper_periodic_timer.cancel()
    stop_photo_cycle_timer()

    # 若為照片輪播模式，啟動照片輪播計時器
    if epaper_config['layout'] == 'photo_qr':
        photos = get_photo_file_list()
        if photos:
            duration = max(getattr(config, 'EPAPER_PHOTO_DURATION', 15), 15)
            print(f'[ePaper]   照片輪播已啟用，資料夾中有 {len(photos)} 張照片，間隔 {duration} 分鐘')
            _start_photo_cycle_timer()
        else:
            folder = getattr(config, 'EPAPER_PHOTO_FOLDER', 'photos')
            print(f'[ePaper]   警告：照片資料夾 ({folder}) 中沒有照片，輪播功能停用')

    # 延遲 15 秒後執行首次更新（等待 Flask server 啟動完成）
    initial_delay = 15
    print(f'[ePaper] 將在 {initial_delay} 秒後執行首次顯示更新...')
    initial_timer = threading.Timer(initial_delay, _epaper_initial_update)
    initial_timer.daemon = True
    initial_timer.start()

    # 啟動 24 小時定期刷新計時器
    print(f'[ePaper] 啟動定期刷新計時器（間隔 {EPAPER_PERIODIC_REFRESH_INTERVAL} 秒 = {EPAPER_PERIODIC_REFRESH_INTERVAL // 3600} 小時）')
    _epaper_periodic_timer = threading.Timer(
        EPAPER_PERIODIC_REFRESH_INTERVAL,
        _epaper_periodic_refresh_callback
    )
    _epaper_periodic_timer.daemon = True
    _epaper_periodic_timer.start()
