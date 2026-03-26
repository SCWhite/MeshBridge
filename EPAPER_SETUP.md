# ePaper 模組設定指南

## 系統需求

本功能需要在 Raspberry Pi 上安裝以下套件來支援 ePaper 顯示功能。

## 安裝步驟

### 1. 安裝 Python 套件

```bash
# 系統套件（SPI、GPIO、圖片處理）
sudo apt install python3-lgpio python3-gpiozero python3-spidev python3-pil
```

### 1.1 重建 venv（啟用 system-site-packages）

ePaper 驅動需要存取系統層級的 `lgpio`、`spidev` 等套件。
若現有 venv 建立時沒有加 `--system-site-packages`，需要重建：

```bash
cd /home/pi/MeshBridge  # 或您的專案路徑

# 先退出目前的 venv（如果有啟用的話）
deactivate 2>/dev/null

# 備份現有 requirements 後重建 venv
pip freeze > /tmp/requirements_backup.txt 2>/dev/null
rm -rf venv
python3 -m venv --system-site-packages venv

# 重新啟用 venv 並安裝專案所需套件
source venv/bin/activate
pip install -r requirements.txt

# pip 安裝 ePaper 相關套件（venv 內）
pip install spidev gpiozero pillow
```

> **說明：** `--system-site-packages` 讓 venv 可以存取 `sudo apt` 安裝的系統套件（如 `lgpio`），否則 ePaper 驅動會因找不到底層 GPIO 函式庫而失敗。

### 1.2 啟用 SPI 介面

電子紙模組透過 SPI 與 Raspberry Pi 通訊，需先啟用 SPI：

```bash
sudo raspi-config
# Interface Options → SPI → Enable
# 重啟後生效
sudo reboot
```

確認 SPI 已啟用：

```bash
ls /dev/spidev*
# 應看到 /dev/spidev0.0 /dev/spidev0.1
```

### 2. 安裝 Chromium 瀏覽器和中文字型

```bash
# 安裝 Chromium 瀏覽器（Debian Trixie）
sudo apt-get update
sudo apt-get install -y chromium

# 安裝中文字型（支援繁體中文顯示）
sudo apt-get install -y fonts-noto-cjk fonts-noto-cjk-extra

# 更新字型快取
sudo fc-cache -fv
```

**注意：** 在舊版 Debian/Ubuntu 系統上，套件名稱可能是 `chromium-browser`。程式會自動偵測可用的命令。

## 設定說明

### config.py 設定

在 `config.py` 中設定 ePaper 模組參數：

```python
# ePaper 模組 ID（決定裝置類型與顏色模式）
EPAPER_MODULE_ID = "weshare-epd7in3e"

# ePaper 顯示模式（顯示內容,方向尺寸）
EPAPER_DISPLAY_MODE = "standard_qr,w7"
```

### 支援的裝置

目前支援以下 ePaper 裝置：

| 裝置 ID | 型號 | 顏色模式 | 螢幕尺寸 | 硬體驅動 |
|---------|------|----------|----------|----------|
| `weshare-epd7in3e` | [Waveshare 7.3" (E)](https://www.waveshare.net/wiki/7.3inch_e-Paper_HAT_(E)_Manual) | 全彩 6色 (full_color) | 800x480 | ✅ |
| `weshare-epd7in5_V2` | [Waveshare 7.5" V2](https://www.waveshare.net/wiki/7.5inch_e-Paper_HAT_Manual) | 黑白 (mono) | 800x480 | ✅ |

### epaper_driver/ 驅動目錄

`epaper_driver/` 目錄存放 ePaper 電子紙的硬體驅動程式，由 `epaper_update.py` 在獨立 subprocess 中載入使用。

**檔案來源：** 所有驅動檔案皆複製自 [Waveshare 官方 Python 範例庫](https://github.com/waveshare/e-Paper/tree/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd)，並將 import 路徑從相對引用改為絕對引用，以配合本專案的目錄結構。

| 檔案 | 說明 |
|------|------|
| `epdconfig.py` | 硬體底層介面（SPI、GPIO 腳位定義與初始化） |
| `epd7in3e.py` | Waveshare 7.3" (E) 6 色電子紙驅動 |
| `epd7in5_V2.py` | Waveshare 7.5" V2 黑白電子紙驅動 |

> **為什麼獨立目錄？** 主程式 `app_noteboard.py` 使用 `eventlet.monkey_patch()` 進行非同步 I/O，這會與 `lgpio` 的內部背景執行緒產生衝突。因此 ePaper 硬體操作透過 `epaper_update.py` 以 subprocess 方式執行，在未被 monkey_patch 的獨立 Python 程序中載入此目錄的驅動，避免衝突。

## 程式實作方式說明

### 自動截圖流程

1. 系統根據設定組成 ePaper 顯示頁面 URL（例如：`http://localhost/epaper?color_mode=full_color&layout=standard_qr&canvas=w7`）
2. 檢查 Flask 應用程式是否可訪問（最多重試 3 次，每次間隔 2 秒）
3. 使用 `chromium` 命令行工具啟動無頭瀏覽器進行截圖
4. 設定視窗尺寸為目標尺寸 + 100px 高度緩衝（避免底部裁切）
5. 擷取截圖並裁切到精確的目標尺寸（例如 800x480）
6. 根據顏色模式處理圖片：
   - **mono（黑白）**：轉換為 1-bit 黑白圖片
   - **full_color（全彩）**：保持 RGB 全彩
   - **dual_rb（紅黑雙色）**：只保留紅、黑、白三色
7. 儲存處理後的圖片至 `./epaper_images/epaper_display.png`

### 硬體保護機制

> ⚠ **重要**：屏幕不能長時間上電。不刷新時必須進入休眠模式，否則長時間高電壓會損壞膜片，無法修復。

- **最小刷新間隔 180 秒**：Waveshare 建議至少間隔 180 秒，過於頻繁的刷新會損傷膜片
- **24 小時定期刷新**：系統自動每 24 小時觸發一次刷新，防止長期不刷新導致殘影或損傷
- **每次刷新後自動休眠**：`display()` → `POWER_OFF` → `DEEP_SLEEP` → 釋放 SPI/GPIO
- **異常緊急斷電**：任何錯誤發生時呼叫 `safe_power_off()` 強制關閉電源，即使部分操作失敗也會繼續嘗試後續步驟
- **Busy 超時保護**：ReadBusy 等待上限 30 秒，防止硬體異常導致無限掛起使屏幕長時間上電
- **單一執行鎖**：同一時間只允許一個更新在執行中
- **背景執行**：截圖與顯示在獨立執行緒中執行，不阻塞主應用程式
- **Chromium 超時**：截圖設有 60 秒超時限制

### 長期存放注意事項

長期不使用墨水屏時，應將屏幕**刷白**後再存放。

透過命令列手動清屏：

```bash
cd /home/pi/MeshBridge
source venv/bin/activate
python3 epaper_update.py clear
```

> **自動刷白：** 當執行 `sudo shutdown now` 或 `sudo systemctl stop meshbridge.service` 停止服務時，systemd 會透過 `ExecStop` 自動呼叫 `app_shutdown.py`，該腳本會執行 `epaper_update.py clear` 將屏幕刷白後才完成關機流程，無需手動清屏。

### 圖檔儲存位置

- 處理後的圖檔：`./epaper_images/epaper_display.png`
- 暫存檔：`./epaper_images/temp_screenshot.png`（處理完成後自動刪除）

## 疑難排解

### 中文字型顯示為方框

如果截圖中的中文顯示為方框，表示缺少中文字型：

```bash
# 安裝中文字型
sudo apt-get install -y fonts-noto-cjk fonts-noto-cjk-extra

# 更新字型快取
sudo fc-cache -fv

# 重啟服務
sudo systemctl restart meshbridge.service
```

### 截圖底部被裁切

如果發現截圖底部內容被裁切，可以調整 `app_noteboard_epaper.py` 中的視窗高度緩衝值：

```python
# 在 capture_epaper_screenshot 函數中
viewport_height = height + 100  # 增加此數值（例如改為 150）
```

### Chromium 找不到或無法啟動

檢查 Chromium 是否正確安裝：

```bash
# 檢查 chromium 命令是否存在
which chromium

# 如果不存在，安裝 chromium
sudo apt-get install -y chromium

# 測試 Chromium 是否能正常運行
chromium --version
```

### 權限問題

確保執行使用者有寫入 `./epaper_images` 目錄的權限：

```bash
mkdir -p /home/pi/MeshBridge/epaper_images
chmod 755 /home/pi/MeshBridge/epaper_images
```
