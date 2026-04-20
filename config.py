LOCAL_APP = "noteboard"

# SEND_INTERVAL_SECOND: 排程器的執行間隔（秒），控制留言自動發送至 LoRa 的頻率。
#   建議設定在 60~180 秒之間，過短可能造成 LoRa 頻寬阻塞。
SEND_INTERVAL_SECOND = 60

# NOTEBOARD_SERVICE_NAME: 服務顯示名稱，用於網頁標題與 ePaper 頁面標題。
#   可自訂為符合應用場景的名稱，例如："社區公佈欄"、"活動留言板"。
NOTEBOARD_SERVICE_NAME = "Mesh資訊站"

# 單一頻道設定（舊版格式，不再使用，可直接使用新版格式的頻道設定）
# BOARD_MESSAGE_CHANEL_NAME = "MQBoardTest"
# MAX_NOTE_SHOW = 200
# MAX_ARCHIVED_NOTE_SHOW = 200
# NOTEBOARD_ADMIN_PASSCODE = "667788"
# NOTEBOARD_POST_PASSCODE = "1234"

# 多頻道設定（新功能）
# 格式：[{"name": "頻道名稱", "user_passcode": "進入密碼", "admin_passcode": "管理密碼", "post_passcode": "發文密碼", "max_notes": 便利貼數量上限，超過會自動封存 , "max_archived_notes": 封存的便利貼檢視數量上限}, ...]
# 每個頻道可設定獨立的密碼與顯示數量

BOARD_MESSAGE_CHANNELS = [
    {
        "name": "MQBoardTest",
        "user_passcode": "", "admin_passcode": "667788", "post_passcode": "",
        "max_notes": 100, "max_archived_notes": 500
    }
]

# 切換頻道時是否要求重新輸入密碼
# False（預設）：輸入一次密碼後，該頻道的認證狀態會持續保留
# True：離開頻道後認證狀態會被清除，下次進入需重新輸入密碼
REAUTH_ON_CHANNEL_SWITCH = False

# 自動補發功能參數
# 系統會在每次排程週期中，自動檢查是否有留言需要重新發送，以確保所有節點都能收到留言。
# AUTO_RESEND_NODE: 期望收到 ACK 的節點數量。預設為 0 停用自動補發功能。
#   當某則留言收到的 ACK 數量少於此值時，該留言會自動補發，直到達到期望的節點數量。
#
# AUTO_RESEND_MIN_MINUTE: 留言建立後的最短等待時間（分鐘），避免剛發送的留言立即被重發。
# AUTO_RESEND_MAX_MINUTE: 留言建立後的最長有效時間（分鐘），超過此時間的留言不再自動重發。

AUTO_RESEND_NODE=0
AUTO_RESEND_MIN_MINUTE=2
AUTO_RESEND_MAX_MINUTE=30

# 裝置連線時，自動用主機時間更新設備時間
# 建議在 Raspberry Pi 有安裝 RTC 模組 (eg. DS3231)並有正確設定時間時，可啟用此功能
UPDATE_LORA_DEVICE_TIME_FROM_LOCAL = False

# ePaper 模組設定
# 設定 ePaper 模組 ID，若未設定或為空則不使用 ePaper 功能

# 目前支援的 ePaper 硬體模組與對應的 ID: 
# weshare-epd7in3e : 7.3寸彩色 https://www.waveshare.net/wiki/7.3inch_e-Paper_HAT_(E)_Manual
# weshare-epd7in5_V2 : 7.5寸黑白 https://www.waveshare.net/wiki/7.5inch_e-Paper_HAT_Manual

EPAPER_MODULE_ID=""

# 目前支援的顯示方式: 
# standard_qr,p7 : 標準顯示方式，包含最新三則訊息加 Wifi資訊 QR Code , 直式7寸顯示方式
# standard_qr,w7 : 標準顯示方式，包含最新三則訊息加 Wifi資訊 QR Code , 橫式7寸顯示方式
# photo_qr,p7 : 像框顯示方式，顯示指定資料夾中的照片，包含最新三則訊息加 Wifi資訊 QR Code , 直式7寸顯示方式
# photo_qr,w7 : 像框顯示方式，顯示指定資料夾中的照片，包含最新三則訊息加 Wifi資訊 QR Code , 橫式7寸顯示方式

EPAPER_DISPLAY_MODE="standard_qr,w7"
#EPAPER_PHOTO_FOLDER="photos"
#EPAPER_PHOTO_DURATION=15  # 照片輪播間隔（分鐘），最小值 15 分鐘

# ePaper 連線提示文字
EPAPER_CONNECT_NOTE = "或在該網路下，手動連線 10.0.0.1 即可檢視更多訊息。 "