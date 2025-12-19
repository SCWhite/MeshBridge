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

## 硬體需求

1.  **Raspberry Pi**
    * 支援 3B, 4, 5, Zero 2W。
    * 建議運行 Raspberry Pi OS 
2.  **Meshtastic Device** (LoRa 節點)
    * 測試通過：Heltec V3, T114, Wio Tracker L1。
    * 其他裝置 (ESP32/nRF52) 理論上皆可支援。
3.  **USB 傳輸線** (具備資料傳輸功能)。

## 🚀 安裝指南

### 1. 系統環境準備
更新系統並安裝必要套件：
```bash
sudo apt update
sudo apt install python3-venv python3-pip dnsmasq git -y
