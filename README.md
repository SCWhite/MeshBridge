# MeshBridge

> 遇到災害時，一般人大概不會準備好適當的通訊工具，但你大概會有手機。

**MeshBridge** 是一個基於 Raspberry Pi 與 Meshtastic 的災難應急通訊閘道器。  
本專案目的在建立一個離線 WiFi 熱點與 Captive Portal（強制登入頁面），讓一般民眾**無需安裝 App**，僅需透過手機瀏覽器，即可接入 Meshtastic 網路發送求救訊息或進行通訊。

![Status](https://img.shields.io/badge/Status-Prototype-orange)
![Python](https://img.shields.io/badge/Python-3.x-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Meshtastic](https://img.shields.io/badge/Link-Meshtastic-brightgreen)

<img width="2048" height="1150" alt="圖片" src="https://github.com/user-attachments/assets/bb6a42b3-398e-458a-bd15-3be600e6066d" />

## 專案特點

目前版本 (MVP) 已實現以下功能：

* **無需 App (Captive Portal)**：
    * 使用者連接 WiFi 後，手機自動跳出聊天視窗，大幅降低使用門檻。
* **離線運作 (Offline First)**：
    * 所有資源（包含 Socket.IO 前端庫）皆儲存於 RPi 本地，無網際網路環境下可完全運作。
    * **離線歷史紀錄**：瀏覽器端 (Local Storage) 會暫存歷史訊息，斷線重連或重新整理後紀錄不消失。
* **硬體隨插即用 (Hot-plug)**：
    * 自動偵測 USB/Serial 上的 Meshtastic 裝置。
    * 支援**熱插拔**：斷線自動偵測，重新插入後自動恢復連線。
* **節點狀態監測**：
    * 網頁端即時顯示 LoRa 硬體連線狀態（紅綠燈號）。
    * 訊息傳送回饋：若 LoRa 未連線，訊息氣泡會變色提示「僅限 WiFi 本地」。

## 未來規劃

未來可能加入以下功能：

- [ ] **多頻道支援**：目前所有訊息皆跑在 LongFast 主頻道，未來支援切換或顯示不同頻道。
- [ ] **流量控制**：增加留言速度限制與訊息長度分段，避免 LoRa 頻寬阻塞。
- [ ] **管理頁面**：提供 Web 介面設定 WiFi SSID、LoRa 參數等。
- [ ] **功能分組**：區分一般聊天、緊急求救、公告廣播等不同類型的訊息流。
- [ ] **多節點/多頻率 Preset**：支援同時管理多個 LoRa 節點或預設頻率切換。
- [ ] **電子紙/留言板支援**：整合 E-Paper 顯示重要公告。
- [ ] **Local 服務延伸**：整合離線地圖或物資回報系統。
- [ ] 系統更新
- [ ] QRcode
- [ ] 類BBS系統
- [ ] 系統公告
- [ ] 山區通訊柱?

## 硬體需求

1.  **Raspberry Pi**
    * 支援 3B, 4, 5, Zero 2W。
    * 建議運行 Raspberry Pi OS 
2.  **Meshtastic Device** (LoRa 節點)
    * 測試通過：Heltec V3, T114, Wio Tracker L1。
    * 其他裝置 (ESP32/nRF52) 理論上皆可支援。
3.  **USB 傳輸線** (具備資料傳輸功能)。

## 專案目錄
```
MeshBridge/
├── app.py                      # 後端主程式 (Flask + SocketIO + Meshtastic)
├── requirements.txt            # Python 套件清單
├── README.md                   # 專案說明書 (包含安裝與使用指南)
├── LICENSE                                  
│
├── templates/
│   └── index.html              # 前端介面 (HTML + CSS + JS 邏輯)
│
├── static/
│   └── socket.io.min.js        # 離線版 Socket.IO 函式庫
│
│
├── setup_wifi.sh               # [腳本] 自動設定 WiFi AP (依據 MAC 碼)
├── setup_dns.sh                # [腳本] 自動設定 dnsmasq (Captive Portal)
├── setup_services.sh           # [腳本] 自動安裝 Systemd 服務 (複製與註冊)
│
├── meshbridge-wifi.service     # [設定] WiFi 設定服務檔 (供 setup_services.sh 複製用)
└── meshbridge.service          # [設定] 主程式服務檔 (供 setup_services.sh 複製用)

```

## 安裝指南

### 1. 系統環境準備
更新系統並安裝必要套件：
```bash
sudo apt update
sudo apt install python3-venv python3-pip dnsmasq git -y
```


### 2. 下載專案 

```bash
git clone [https://github.com/SCWhite/MeshBridge.git](https://github.com/SCWhite/MeshBridge.git)
cd MeshBridge

# 建立並啟動虛擬環境
python3 -m venv venv
source venv/bin/activate

# 安裝 Python 依賴套件
pip install -r requirements.txt
```

### 3. 設定 WiFi AP (自動化腳本)
本專案包含一個自動化腳本 `setup_wifi.sh`，它會讀取樹莓派的 MAC 位址後四碼，自動建立一個獨一無二的 SSID（例如：`MeshBridge_A1B2`），避免多台裝置名稱衝突。

執行以下指令以將PI設定成 WiFi 熱點：
```bash
# 給予腳本執行權限
chmod +x setup_wifi.sh

# 執行設定 (只需執行一次，之後會由 Systemd 接手)
sudo ./setup_wifi.sh
```

> [!IMPORTANT]
> 說明：此腳本將 WiFi 設為 AP 模式，並指定固定 IP 10.0.0.1 / 或使用 chat.meshbridge.com 
>

### 4. 設定 DNS 轉導 (自動化腳本)
執行此腳本以設定 dnsmasq。這是 Captive Portal 的核心，負責將連入使用者的所有網域請求導向樹莓派的聊天室。

```bash
chmod +x setup_dns.sh
sudo ./setup_dns.sh
```

> [!NOTE]
> 說明：腳本會修改 /etc/dnsmasq.conf 並重啟服務。
>

### 5. 建立與啟動服務 (自動化腳本)
最後，執行此腳本將 MeshBridge 註冊為 Systemd 服務，確保開機後自動運作。

```Bash

chmod +x setup_services.sh
sudo ./setup_services.sh
```
> [!NOTE]
> 說明：此腳本會將專案中的 .service 檔案複製到系統目錄，並設定開機自動啟動。
>

## 常見問題 (Troubleshooting)

```
Q: 手機連上 WiFi 後沒有自動跳出畫面？

請手動開啟瀏覽器，輸入 10.0.0.1 或 chat.meshbridge.com。

部分 Android/iOS 裝置對 Captive Portal 的偵測機制不同，可能需要幾秒鐘才會跳出通知。
```

```
Q: 程式顯示找不到 USB 裝置或 Timed out？

請檢查 USB 線材是否具備傳輸功能。
```

```
Q: 如何查看程式運作紀錄 (Logs)？

使用以下指令查看即時日誌：

sudo journalctl -u meshbridge.service -f

```

## 致謝 

* **Google Gemini 3**：特別感謝 Gemini 3 在本專案開發過程中擔任技術顧問，協助系統架構規劃、Python 程式實作、除錯以及文件撰寫。
* 基本上它做了所有的事情，我就是個按鍵盤的馬鈴薯。
