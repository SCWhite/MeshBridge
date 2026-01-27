# MeshBridge NoteBoard 模式說明文件

## 1. 功能概述

**NoteBoard** 是 MeshBridge 的留言板模式，提供類似便利貼牆的協作介面，讓使用者透過 WiFi 或 LoRa 網路張貼、回覆、管理留言。

### 主要功能

- **便利貼式留言板**：視覺化的留言牆介面，每則留言如同一張便利貼，直覺操作，可快速搜尋所有已經接收到的資料。
- **節流傳輸**：針對 LoRa 的有限傳輸頻寬，設計的流量控制傳輸機制：所有待傳輸的訊息列隊在資料庫中，依照所設定的發送頻率依序發送。 eg: 每30秒送出一筆。
- **LoRa資料同步**：針對 MeshBridge 應用方式，設計的非同步資料更新機制
- **留言回覆**：支援階層式回覆功能，可針對特定留言進行討論
- **顏色標記**：16 色調色盤，可為留言設定不同顏色以便分類
- **權限控制**：基於 `author_key` 的權限驗證，僅作者可編輯/刪除自己的留言
- **即時更新**：使用 WebSocket (Socket.IO) 實現即時同步
- **離線地圖支援**：支援 MBTiles 格式的離線地圖，可在無網路環境下使用地圖功能

### 資料狀態

1. **LAN only**：留言先儲存於本地資料庫，等待 LoRa 輪到排程與連線後才自動發送
2. **LoRa sent**：留言成功透過 LoRa 發送後，狀態更新為 `LoRa sent`
3. **LoRa received**：從其他 LoRa 節點接收的留言

## 2. 離線地圖安裝與設定

NoteBoard 支援 MBTiles 格式的離線地圖，讓您在無網路環境下也能使用完整的地圖功能。

### 2.1 下載離線地圖檔

#### 台灣地區地圖

台灣地區使用者可從**國土測繪圖資服務雲**網站，下載免費的政府開放資料：

**地圖名稱**：[政府開放資料]臺灣通用電子地圖（套疊等高線）MBTiles 檔（APP 離線地圖用）

**下載連結**：[https://maps.nlsc.gov.tw/MbIndex_qryPage.action?fun=8](https://maps.nlsc.gov.tw/MbIndex_qryPage.action?fun=8)

#### 其他地區地圖

如需使用其他地區的離線地圖，可從以下來源取得：
- **OpenStreetMap**：使用開源工具（如 TileMill、Mapbox Studio）自行製作
- **第三方地圖服務**：部分地圖服務提供商提供 MBTiles 格式下載

### 2.2 安裝離線地圖

1. **建立地圖資料夾**（如不存在）：
   ```bash
   mkdir -p MeshBridge/maps
   ```

2. **放置地圖檔案**：
   將下載的 `.mbtiles` 檔案放入 `maps/` 資料夾中
   ```
   MeshBridge/
   ├── maps/
   │   ├── taiwan.mbtiles
   │   └── other_region.mbtiles
   ├── app.py
   └── config.py
   ```

3. **系統自動載入**：
   系統啟動時會自動識別並載入 `maps/` 資料夾中的所有 `.mbtiles` 檔案

### 2.3 MBTiles 支援說明

#### 多檔支援
- ✅ **多地區支援**：可同時放置多個不同地區的 `.mbtiles` 檔案
- ✅ **圖層套疊**：支援多個檔案針對同一地區進行圖層套疊（如：底圖 + 等高線 + 路網）

#### 格式建議
- **推薦格式**：Raster（點陣圖）格式
- **原因**：Raster 格式的地圖完全自包含，不依賴網路字型，可確保在完全離線環境下正常顯示
- **Vector 格式注意事項**：Vector（向量圖）格式的地圖可能使用網路字型渲染文字圖層，在離線環境下可能無法正常顯示文字標籤

### 2.4 config.py 地圖相關設定

系統會自動載入指定資料夾中的所有 `.mbtiles` 檔案。如需自訂設定，可在 `config.py` 中新增以下參數：

```python
# 地圖相關設定
NOTEBOARD_MBTILES_FOLDER = "./maps"  # 地圖檔案路徑（預設值：./maps）
NOTEBOARD_MBTILES_LAYER_MODE = "auto"  # 圖層模式（預設值：auto）
```

#### 參數說明

**`NOTEBOARD_MBTILES_FOLDER`**
- **類型**：字串
- **預設值**：`"./maps"`
- **說明**：指定 MBTiles 地圖檔案的存放資料夾路徑

**`NOTEBOARD_MBTILES_LAYER_MODE`**
- **類型**：字串
- **預設值**：`"auto"`
- **說明**：設定多個地圖檔案的圖層載入與顯示模式
- **可選值**：
  - `"auto"`：自動模式 - 系統根據地圖檔案的縮放層級範圍自動判斷使用 `overlay` 或 `zoom-level` 模式
    - 若多個地圖檔案的縮放層級範圍重疊較多（≥2 個層級），使用 `overlay` 模式
    - 若多個地圖檔案的縮放層級範圍重疊較少（<2 個層級）或不重疊，使用 `zoom-level` 模式
  - `"overlay"`：疊加模式 - 所有地圖檔案同時顯示並疊加在一起（適用於底圖 + 等高線 + 路網等多圖層套疊）
  - `"zoom-level"`：縮放層級模式 - 根據當前縮放層級自動切換顯示對應的地圖檔案（適用於不同精細度的地圖分層）
- **範例**：
  ```python
  NOTEBOARD_MBTILES_LAYER_MODE = "auto"        # 自動判斷（推薦）
  NOTEBOARD_MBTILES_LAYER_MODE = "overlay"     # 強制使用疊加模式
  NOTEBOARD_MBTILES_LAYER_MODE = "zoom-level"  # 強制使用縮放層級模式
  ```

**`NOTEBOARD_MAP_INIT_LOCATION`**
- **類型**：字串
- **預設值**：無（選填）
- **格式**：`"緯度,經度"`（例如：`"25.013799,121.464188"`）
- **說明**：設定地圖選擇器（Location Picker）的初始中心點座標
- **範例**：
  ```python
  NOTEBOARD_MAP_INIT_LOCATION = "25.013799,121.464188"  # 設定台北市某地點為初始中心
  ```

**注意事項**：
- 如未在 `config.py` 中設定這些參數，系統將使用預設值
- 修改設定後需重新啟動服務才會生效

### 2.5 地圖初始中心點優先順序

當使用者開啟地點選擇器（Location Picker）時，系統會依照以下優先順序決定地圖的初始中心點：

1. **使用者上次使用的地圖位置**（`lastLocation`）
   - 系統會記住每位使用者最後一次使用地圖選擇器時的位置
   - 此為最高優先級，確保使用者體驗的連貫性

2. **管理員設定的初始位置**（`NOTEBOARD_MAP_INIT_LOCATION`）
   - 在 `config.py` 中設定的固定座標
   - 適用於特定區域的應用場景（如：校園、社區、活動場地）
   - 僅在使用者沒有歷史位置記錄時生效

3. **設備 GPS 位置**（`deviceLastPosition`）
   - 從連接的 Meshtastic 設備取得的 GPS 座標
   - 需要設備已設定位置或已經透過 GPS 定位成功取得座標
   - 僅在與設備連線時，取得一次位置，不會做持續更新

4. **系統預設位置**
   - 座標：`(25.0330, 121.5654)`（台北市中心附近）
   - 當以上所有條件都不滿足時使用

## 3. 啟用方式

### 切換至 NoteBoard 模式

編輯 `config.py` 檔案：

```python
LOCAL_APP = "noteboard"
```

### 啟動服務

#### 方式一：直接執行 (開發除錯用)
```bash
cd MeshBridge
source venv/bin/activate
python3 app.py
```

#### 方式二：使用 Systemd 服務，開機自動啟動（與 MeshBridge 整合使用採用此一方式）
```bash
sudo systemctl start meshbridge.service
sudo systemctl status meshbridge.service
```

```bash
sudo systemctl enable meshbridge.service
```

#### 方式三：使用 Docker 容器執行（僅建議 Linux 環境）

**⚠️ 重要限制說明**

Docker 執行方式**僅建議在 Linux 系統上使用**，因為 USB 裝置掛載在不同作業系統上有以下限制：

- **macOS**：Docker Desktop for Mac 不支援將主機的 USB 裝置以 `/dev/xxx` 的方式直接映射進容器。這是 Docker Desktop 在 macOS 上的架構限制。
- **Windows (WSL2)**：需再透過 `usbipd-win` 工具將 USB 轉發到 WSL2

**在 Linux 上使用 Docker：**

```bash
# 1. 確認 USB 裝置路徑（通常是 /dev/ttyACM0 或 /dev/ttyUSB0）
ls /dev/tty*

# 2. 編輯 docker-compose.yml，確認裝置路徑正確
# devices:
#   - /dev/ttyACM0:/dev/ttyACM0

# 3. 從 Docker Hub 拉取並啟動
docker compose pull
docker compose up -d

# 4. 查看日誌
docker compose logs -f

# 5. 停止服務
docker compose down
```

**macOS/Windows 使用者建議**：請使用「方式一：直接執行」來運行 MeshBridge，以確保 LoRa USB 裝置能正常存取。

### 存取介面

- **本地存取**：`http://localhost` 
- **服務埠號**：Port 80 (HTTP)
- **WebSocket**：自動連接至相同主機

## 4. 使用者角色與權限管理

NoteBoard 提供兩種使用者角色：**一般使用者**與**管理者**，各自擁有不同的操作權限。

### 4.1 角色說明

#### 一般使用者

一般使用者為系統預設角色，所有訪問者在未進行管理者認證前皆為一般使用者身份。

**權限範圍**：
- ✅ 檢視所有便利貼與回覆
- ✅ 建立新便利貼與回覆（需符合發送通關碼設定）
- ✅ 編輯自己建立的便利貼
- ✅ 刪除/封存自己建立的便利貼
- ✅ 變更自己建立的便利貼顏色
- ✅ 重新發送自己建立的便利貼
- ❌ 無法編輯、刪除或封存他人建立的便利貼
- ❌ 無法置頂便利貼

#### 管理者

管理者為具有完整管理權限的角色，需透過管理者密碼認證後取得。

**權限範圍**：
- ✅ 擁有一般使用者的所有權限
- ✅ **封存任何使用者建立的便利貼**（包含他人的便利貼）
- ✅ **變更任何便利貼的顏色**（包含他人的便利貼）
- ✅ **置頂便利貼**（一次僅能置頂一則，置頂便利貼會顯示在最上方）
- ✅ **免除發送通關碼限制**（即使系統啟用發送通關碼，管理者仍可直接發送）

**注意事項**：
- 管理者無法編輯他人便利貼的內容，僅能封存或變更顏色
- 管理者身份為暫時性，登出後即恢復為一般使用者

### 4.2 角色切換方式

#### 切換至管理者身份

1. 點擊介面右上角的「**一般用戶**」標籤
2. 系統彈出「管理者認證」對話框
3. 輸入管理者密碼（於 `config.py` 中的 `NOTEBOARD_ADMIN_PASSCODE` 設定）
4. 點擊「確定」完成認證
5. 認證成功後，右上角標籤將顯示為「**🔑 管理者**」

#### 登出管理者身份

1. 點擊介面右上角的「**🔑 管理者**」標籤
2. 系統彈出確認對話框：「確定要登出管理者身份，切換為一般使用者嗎？」
3. 點擊「確定」完成登出
4. 登出後，右上角標籤將恢復為「**一般用戶**」

### 4.3 發送用通關碼（Post Passcode）

發送用通關碼為可選的安全機制，用於限制一般使用者發送便利貼與回覆的權限。啟用後，僅知道通關碼的使用者才能發送訊息，可有效防止未授權的訊息張貼。

#### 功能說明

- **適用對象**：僅對一般使用者生效，管理者不受此限制
- **適用範圍**：建立新便利貼、建立回覆
- **驗證時機**：在送出便利貼或回覆時進行驗證

#### 啟用方式

編輯 `config.py` 檔案，設定 `NOTEBOARD_POST_PASSCODE` 參數：

```python
# 發送用通關碼（留空或不設定則停用此功能）
NOTEBOARD_POST_PASSCODE = "1234"
```

**設定說明**：
- 若設定為非空字串（如 `"1234"`），則啟用發送通關碼功能
- 若設定為空字串（`""`）或不設定此參數，則停用此功能
- 建議使用 4-8 位數字或英數混合的通關碼

#### 使用流程

當發送通關碼功能啟用時：

1. **一般使用者建立便利貼或回覆**：
   - 在便利貼編輯介面中，會顯示「**發送用通關碼**」輸入欄位
   - 輸入正確的通關碼後，點擊「送出」
   - 若通關碼正確，訊息成功送出
   - 若通關碼錯誤或未填寫，系統顯示錯誤訊息：「請輸入發送用通關碼！」或「發送用通關碼錯誤」

2. **管理者建立便利貼或回覆**：
   - 管理者身份下，不會顯示「發送用通關碼」輸入欄位
   - 可直接送出訊息，無需輸入通關碼

#### 安全建議

- 定期更換通關碼，避免長期使用相同密碼
- 通關碼應與管理者密碼（`NOTEBOARD_ADMIN_PASSCODE`）設定為不同值
- 僅將通關碼告知授權使用者，或是代為輸入，避免公開張貼

### 4.4 權限對照表

| 操作項目 | 一般使用者 | 管理者 | 備註 |
|---------|-----------|--------|------|
| 檢視便利貼 | ✅ | ✅ | - |
| 建立便利貼/回覆 | ✅ | ✅ | 一般使用者需符合發送通關碼設定 |
| 編輯自己的便利貼 | ✅ (僅 LAN only) | ✅ (僅 LAN only) | 僅限內容尚未發送至 LoRa 的便利貼 |
| 刪除自己的便利貼 | ✅ (僅 LAN only) | ✅ (僅 LAN only) | 僅限內容尚未發送至 LoRa 的便利貼 |
| 封存自己的便利貼 | ✅ | ✅ | 適用於已發送至 LoRa 的便利貼 |
| 封存他人的便利貼 | ❌ | ✅ | 管理者專屬權限 |
| 變更自己便利貼顏色 | ✅ | ✅ | - |
| 變更他人便利貼顏色 | ❌ | ✅ | 管理者專屬權限 |
| 置頂便利貼 | ❌ | ✅ | 管理者專屬權限，一次僅能置頂一則 |
| 重新發送自己的便利貼 | ✅ | ✅ | 僅限 LoRa sent 狀態 |
| 免除發送通關碼 | ❌ | ✅ | 管理者發送訊息時無需輸入通關碼 |

## 5. config.py 設定說明

### 設定檔位置
```
MeshBridge/config.py
```

### 設定參數

| 參數名稱 | 類型 | 預設值 | 說明 |
|---------|------|--------|------|
| `LOCAL_APP` | string | `"noteboard"` | 應用模式選擇：`"chat"` 或 `"noteboard"` |
| `BOARD_MESSAGE_CHANEL_NAME` | string | `"YourChannelName"` | LoRa 頻道名稱，需與 Meshtastic 裝置設定一致 |
| `SEND_INTERVAL_SECOND` | int | `30` | 自動發送排程器間隔時間（秒），最小值不小於 10 秒 |
| `MAX_NOTE_SHOW` | int | `200` | 前端顯示的最大留言數量（不含已封存） |
| `MAX_ARCHIVED_NOTE_SHOW` | int | `200` | 前端顯示的最大已封存留言數量 |
| `NOTEBOARD_ADMIN_PASSCODE` | string | - | 管理者密碼，用於認證管理者身份 |
| `NOTEBOARD_POST_PASSCODE` | string | `""` | 發送用通關碼，留空則停用此功能 |

### 設定範例

```python
# 應用模式
LOCAL_APP = "noteboard"

# LoRa 頻道設定（需與 Meshtastic 裝置的頻道名稱一致）
BOARD_MESSAGE_CHANEL_NAME = "YourChannelName"

# 發送間隔（秒）- 控制 LAN only 留言自動發送至 LoRa 的頻率
SEND_INTERVAL_SECOND = 30

# 顯示數量限制
MAX_NOTE_SHOW = 200           # 一般留言顯示上限
MAX_ARCHIVED_NOTE_SHOW = 200  # 封存留言顯示上限

# 管理者密碼（用於認證管理者身份）
NOTEBOARD_ADMIN_PASSCODE = "your_admin_password"

# 發送用通關碼（留空則停用此功能）
NOTEBOARD_POST_PASSCODE = "1234"  # 設定為 "" 可停用發送通關碼功能
```

### 注意事項

- **頻道名稱**：`BOARD_MESSAGE_CHANEL_NAME` 必須與 Meshtastic 裝置上設定的頻道名稱完全一致（區分大小寫）
- **發送間隔**：`SEND_INTERVAL_SECOND` 建議設定在 30-180 秒之間，避免 LoRa 頻寬阻塞

## 6. LoRa 指令說明

NoteBoard 使用特定格式的文字訊息在 Meshmatic LoRa 網路的Channel上傳輸，以下為各指令格式與用途。

### 6.1 新增留言

**格式**：`/msg [new]<留言內容>`

**用途**：建立一則新的留言

**範例**：
```
/msg [new]這是一則測試留言
```

**說明**：
- 系統會自動產生 `lora_msg_id` 作為此留言的唯一識別碼
- 初始 `author_key` 和 `bg_color` 為空，需透過後續指令設定

---

### 6.2 重發留言

**格式**：`/msg [<lora_msg_id>]<留言內容>`

**用途**：重新發送已存在的留言（使用指定的 `lora_msg_id`）

**範例**：
```
/msg [1234567890]這是重發的留言
```

**說明**：
- 用於確保留言在網路中的一致性
- 如果本地已存在該 `lora_msg_id`，則略過不重複建立

---

### 6.3 設定作者

**格式**：`/author [<lora_msg_id>]<author_key>`

**用途**：設定留言的作者識別碼

**範例**：
```
/author [1234567890]lora-a1b2c3d4
```

**說明**：
- `author_key` 格式通常為 `lora-<device_id>` 或 `user-<uuid>`
- 此指令會更新指定留言的 `author_key` 欄位

---

### 6.4 設定顏色

**格式**：`/color [<lora_msg_id>]<author_key>, <color_index>`

**用途**：設定留言的背景顏色

**範例**：
```
/color [1234567890]lora-a1b2c3d4, 5
```

**說明**：
- `color_index` 範圍：0-15（對應 16 色調色盤）
- 需提供正確的 `author_key` 進行權限驗證
- 顏色索引對照：
  - 0: Red, 1: Orange, 2: Yellow, 3: Light Green
  - 4: Green, 5: Teal, 6: Cyan, 7: Light Blue
  - 8: Blue, 9: Purple, 10: Magenta, 11: Pink
  - 12: Light Gray, 13: Gray, 14: Gold, 15: Coral

---

### 6.5 封存留言

**格式**：`/archive [<lora_msg_id>]<author_key>`

**用途**：將留言標記為已封存（deleted=1）

**範例**：
```
/archive [1234567890]lora-a1b2c3d4
```

**說明**：
- 需提供正確的 `author_key` 進行權限驗證
- 封存的留言不會被刪除，僅標記為 `deleted=1`
- 前端可選擇是否顯示已封存的留言

---

### 6.6 回覆留言

**格式**：`/reply <new>[<parent_lora_msg_id>]<留言內容>`

**用途**：建立一則回覆留言，關聯至指定的父留言

**範例**：
```
/reply <new>[1234567890]這是對該留言的回覆
```

**說明**：
- `parent_lora_msg_id` 為要回覆的父留言的 `lora_msg_id`
- 如果父留言不存在於本地資料庫，系統會設定 `is_temp_parent_note=1`
- 支援多層級回覆（回覆的回覆）

### 6.7 重送回覆留言

**格式**：`/reply <lora_msg_id>[<parent_lora_msg_id>]<留言內容>`


**用途**：重新發送已存在的留言（使用指定的 `lora_msg_id`），關聯至指定的父留言

**範例**：
```
/reply <0123456789>[1234567890]這是對該留言的回覆
```

---

### 6.8 使用者 ACK 確認

**格式**：`/ack <lora_msg_id>`

**用途**：當接收到新留言後，延遲 60 秒自動發送 ACK 確認，通知發送者該留言已被接收

**範例**：
```
/ack 1234567890
```

**說明**：
- 系統在接收到 `/msg [new]` 或 `/msg [<lora_msg_id>]` 或 `/reply` 指令後，會自動在 60 秒後發送 ACK
- ACK 記錄會儲存至 `ack_records` 資料表，記錄哪些節點已確認接收此留言
- 發送者可透過 ACK 記錄了解留言的傳播狀況

---

### 指令發送流程

1. **Web 端建立留言** → 儲存為 `LAN only` 狀態
2. **排程器發送** → 透過 LoRa 發送 `/msg [new]` 指令
3. **接收 ACK** → 更新狀態為 `LoRa sent`，記錄 `lora_msg_id`
4. **發送後續指令** → 自動發送 `/author` 和 `/color` 指令
5. **其他節點接收** → 解析指令並同步至本地資料庫

## 7. SQLite 資料庫欄位說明

### 資料庫檔案
- **檔案名稱**：`noteboard.db`
- **位置**：專案根目錄
- **類型**：SQLite 3

### 資料表：notes

| 欄位名稱 | 資料型別 | 約束條件 | 預設值 | 說明 |
|---------|---------|---------|--------|------|
| `note_id` | TEXT | PRIMARY KEY | - | 留言唯一識別碼（UUID v4） |
| `reply_lora_msg_id` | TEXT | FOREIGN KEY | NULL | 回覆的父留言 `lora_msg_id`，NULL 表示為根留言 |
| `board_id` | TEXT | NOT NULL | - | 留言板 ID（對應頻道名稱） |
| `body` | TEXT | NOT NULL | - | 留言內容 |
| `bg_color` | TEXT | - | - | 背景顏色（HSL 格式，如 `hsl(120, 70%, 85%)`） |
| `status` | TEXT | NOT NULL | - | 留言狀態：`LAN only`、`LoRa sent`、`LoRa received` |
| `created_at` | INTEGER | NOT NULL | - | 建立時間戳記（毫秒） |
| `updated_at` | INTEGER | NOT NULL | - | 更新時間戳記（毫秒） |
| `author_key` | TEXT | NOT NULL | - | 作者識別碼（如 `lora-a1b2c3d4` 或 `user-12345678`） |
| `rev` | INTEGER | NOT NULL | 1 | 版本號（每次更新 +1） |
| `deleted` | INTEGER | NOT NULL | 0 | 是否已封存（0: 否, 1: 是） |
| `resent_count` | INTEGER | NOT NULL | 0 | 重發次數（尚未實作，保留欄位） |
| `is_need_update_lora` | INTEGER | NOT NULL | 0 | 是否需要更新至 LoRa（0: 否, 1: 是） |
| `lora_msg_id` | TEXT | - | NULL | LoRa 訊息 ID（由 Meshtastic 產生） |
| `is_temp_parent_note` | INTEGER | NOT NULL | 0 | 是否為暫時父留言（0: 否, 1: 是） |
| `is_pined_note` | INTEGER | NOT NULL | 0 | 是否為置頂留言（尚未實作，保留欄位） |
| `resent_priority` | INTEGER | NOT NULL | 0 | 重發優先級（尚未實作，保留欄位） |
| `grid_mode` | TEXT | NOT NULL | '' | 網格模式（尚未實作，保留欄位） |
| `grid_x` | INTEGER | NOT NULL | 0 | 網格 X 座標（尚未實作，保留欄位） |
| `grid_y` | INTEGER | NOT NULL | 0 | 網格 Y 座標（尚未實作，保留欄位） |

### 索引

| 索引名稱 | 欄位 | 說明 |
|---------|------|------|
| `idx_board_id` | `board_id` | 加速依留言板查詢 |
| `idx_created_at` | `created_at DESC` | 加速依時間排序查詢 |
| `idx_deleted` | `deleted` | 加速過濾已封存留言 |

---

### 資料表：ack_records

**用途**：記錄使用者 ACK 確認，追蹤哪些 LoRa 節點已確認接收特定留言

| 欄位名稱 | 資料型別 | 約束條件 | 預設值 | 說明 |
|---------|---------|---------|--------|------|
| `ack_id` | TEXT | PRIMARY KEY | - | ACK 記錄唯一識別碼（UUID v4） |
| `note_id` | TEXT | NOT NULL, FOREIGN KEY | - | 關聯的留言 ID（對應 `notes.note_id`） |
| `created_at` | INTEGER | NOT NULL | - | 建立時間戳記（毫秒） |
| `updated_at` | INTEGER | NOT NULL | - | 更新時間戳記（毫秒） |
| `lora_node_id` | TEXT | NOT NULL | - | 發送 ACK 的 LoRa 節點 ID（格式：`lora-<device_id>`） |

### 索引

| 索引名稱 | 欄位 | 說明 |
|---------|------|------|
| `idx_ack_note_id` | `note_id` | 加速依留言查詢 ACK 記錄 |
| `idx_ack_created_at` | `created_at DESC` | 加速依時間排序查詢 |

**說明**：
- 每個 `note_id` 和 `lora_node_id` 的組合是唯一的（同一節點對同一留言只記錄一次 ACK）
- 如果同一節點重複發送 ACK，系統會更新 `updated_at` 時間戳記
- ACK 記錄用於追蹤留言的傳播狀況，幫助使用者了解哪些節點已接收到留言

### 欄位說明補充

#### status 狀態值

`status` 欄位記錄留言的傳輸狀態，共有以下四種可能值：

| 狀態值 | 說明 | 觸發時機 | 可執行操作 |
|--------|------|----------|-----------|
| **`LAN only`** | 留言僅存在於本地區網，尚未發送至 LoRa | • 透過 Web 介面新建留言時的初始狀態<br>• ACK 超時後從 `Sending` 狀態回退 | • 可編輯內容<br>• 可直接刪除<br>• 等待排程器發送至 LoRa |
| **`Sending`** | 留言正在發送至 LoRa，等待 ACK 確認 | • 排程器發送留言至 LoRa 後，等待接收 ACK 封包 | • 等待 ACK 確認<br>• 若超時則回退為 `LAN only` |
| **`LoRa sent`** | 留言已成功發送至 LoRa 網路 | • 收到 LoRa ACK 封包後，從 `Sending` 狀態更新 | • 僅可變更顏色<br>• 僅可封存（不可直接刪除）<br>• 不可編輯內容 |
| **`LoRa received`** | 從其他 LoRa 節點接收的留言 | • 接收到其他節點透過 LoRa 發送的留言指令 | • 僅可變更顏色（需為作者）<br>• 僅可封存（需為作者）<br>• 不可編輯內容 |

**狀態轉換流程**：

```
[Web 建立] → LAN only → [排程器發送] → Sending → [收到 ACK] → LoRa sent
                ↑                            |
                └────────[ACK 超時]──────────┘

[LoRa 接收] → LoRa received
```

**注意事項**：
- `LAN only` 和 `Sending` 狀態的留言會被排程器自動處理
- ACK 超時時間由 `config.py` 的 `ACK_TIMEOUT_SECONDS` 設定
- 只有 `LAN only` 狀態的留言可以編輯內容或直接刪除
- `LoRa sent` 和 `LoRa received` 狀態的留言只能變更顏色或封存

#### is_temp_parent_note
- 當接收到回覆留言，但父留言尚未存在於本地時，設定為 1
- 用於處理訊息接收順序不一致的情況

#### is_need_update_lora
- 當留言的顏色或封存狀態變更時，設定為 1
- 排程器會自動發送更新指令至 LoRa 網路

## 8. RESTful API 說明

所有 API 端點的 Base URL 為：`http://10.0.0.1` 或 `http://chat.meshbridge.com`

### 8.1 取得使用者 UUID 

**端點**：`GET /api/user/uuid`

**說明**：快速建立臨時用戶，但iOS無作用，取得或建立當前使用者的 UUID（儲存於 session/cookie）

**回應範例**：
```json
{
  "success": true,
  "uuid": "abc12345"
}
```

---

### 8.2 取得留言列表

**端點**：`GET /api/boards/<board_id>/notes`

**參數**：
- `board_id`（路徑參數）：留言板 ID（通常為頻道名稱）
- `is_include_deleted`（查詢參數，選填）：是否包含已封存留言（`true` / `false`，預設 `false`）

**說明**：取得指定留言板的所有留言，包含階層式回覆結構

**回應範例**：
```json
{
  "success": true,
  "board_id": "YourChannelName",
  "notes": [
    {
      "noteId": "uuid-1234",
      "replyLoraMessageId": null,
      "text": "這是一則留言",
      "bgColor": "hsl(120, 70%, 85%)",
      "status": "LoRa sent",
      "time": "2024/12/29 下午 02:30",
      "timestamp": 1735456200000,
      "userId": "user-abc12345",
      "sender": "WebUser",
      "loraSuccess": true,
      "source": "local",
      "rev": 1,
      "archived": false,
      "loraMessageId": "1234567890",
      "isTempParentNote": false,
      "replyNotes": [
        {
          "noteId": "uuid-5678",
          "replyLoraMessageId": "1234567890",
          "text": "這是回覆",
          "bgColor": "hsl(240, 70%, 85%)",
          "status": "LoRa received",
          "time": "2024/12/29 下午 02:35",
          "timestamp": 1735456500000,
          "userId": "lora-a1b2c3d4",
          "sender": "LoRa-c3d4",
          "loraSuccess": true,
          "source": "lora",
          "rev": 1,
          "archived": false,
          "loraMessageId": "9876543210",
          "isTempParentNote": false
        }
      ]
    }
  ],
  "count": 1
}
```

---

### 8.3 建立新留言

**端點**：`POST /api/boards/<board_id>/notes`

**參數**：
- `board_id`（路徑參數）：留言板 ID

**請求 Body**：
```json
{
  "text": "留言內容",
  "author_key": "user-abc12345",
  "color_index": 5,
  "parent_note_id": "1234567890"  // 選填，回覆時填入父留言的 lora_msg_id
}
```

**說明**：建立一則新留言，初始狀態為 `LAN only`

**回應範例**：
```json
{
  "success": true,
  "note_id": "uuid-1234",
  "board_id": "YourChannelName"
}
```

**錯誤回應**：
```json
{
  "success": false,
  "error": "Text is required"
}
```

---

### 8.4 更新留言

**端點**：`PUT /api/boards/<board_id>/notes/<note_id>`

**參數**：
- `board_id`（路徑參數）：留言板 ID
- `note_id`（路徑參數）：留言 ID

**請求 Body**：
```json
{
  "text": "更新後的內容",
  "author_key": "user-abc12345",
  "color_index": 8
}
```

**說明**：更新留言內容與顏色，僅限作者本人且狀態為 `LAN only` 的留言

**回應範例**：
```json
{
  "success": true,
  "note_id": "uuid-1234",
  "board_id": "YourChannelName"
}
```

**錯誤回應**：
```json
{
  "success": false,
  "error": "Only LAN only notes can be edited"
}
```

---

### 8.5 變更留言顏色

**端點**：`POST /api/boards/<board_id>/notes/<note_id>/color`

**參數**：
- `board_id`（路徑參數）：留言板 ID
- `note_id`（路徑參數）：留言 ID

**請求 Body**：
```json
{
  "author_key": "user-abc12345",
  "color_index": 10
}
```

**說明**：變更留言顏色，僅限作者本人且狀態非 `LAN only` 的留言。變更後會自動同步至 LoRa

**回應範例**：
```json
{
  "success": true,
  "note_id": "uuid-1234",
  "board_id": "YourChannelName"
}
```

---

### 8.6 封存留言

**端點**：`POST /api/boards/<board_id>/notes/<note_id>/archive`

**參數**：
- `board_id`（路徑參數）：留言板 ID
- `note_id`（路徑參數）：留言 ID

**請求 Body**：
```json
{
  "author_key": "user-abc12345"
}
```

**說明**：封存留言（設定 `deleted=1`），僅限作者本人且狀態非 `LAN only` 的留言。封存後會自動同步至 LoRa

**回應範例**：
```json
{
  "success": true,
  "note_id": "uuid-1234",
  "board_id": "YourChannelName"
}
```

---

### 8.7 刪除留言

**端點**：`DELETE /api/boards/<board_id>/notes/<note_id>`

**參數**：
- `board_id`（路徑參數）：留言板 ID
- `note_id`（路徑參數）：留言 ID

**請求 Body**：
```json
{
  "author_key": "user-abc12345"
}
```

**說明**：刪除留言（設定 `deleted=1`），僅限作者本人且狀態為 `LAN only` 的留言

**回應範例**：
```json
{
  "success": true,
  "note_id": "uuid-1234",
  "board_id": "YourChannelName"
}
```

---

### WebSocket 事件

#### 連線事件
**事件名稱**：`connect`

**說明**：客戶端連線時，伺服器會發送 LoRa 連線狀態

**伺服器發送**：
```json
{
  "online": true
}
```

---

#### LoRa 狀態更新
**事件名稱**：`lora_status`

**說明**：LoRa 連線狀態變更時廣播

**伺服器發送**：
```json
{
  "online": false
}
```

---

#### 留言更新通知
**事件名稱**：`refresh_notes`

**說明**：當有新留言、留言更新或刪除時，通知客戶端重新載入留言列表

**伺服器發送**：
```json
{
  "board_id": "YourChannelName"
}
```

---

### 8.8 重新發送留言

**端點**：`POST /api/boards/<board_id>/notes/<note_id>/resend`

**參數**：
- `board_id`（路徑參數）：留言板 ID
- `note_id`（路徑參數）：留言 ID

**請求 Body**：
```json
{
  "author_key": "user-abc12345"
}
```

**說明**：重新發送已成功發送至 LoRa 的留言（`status` 為 `LoRa sent`），用於補發未被其他節點接收到的訊息

**功能**：
- 僅限作者本人且狀態為 `LoRa sent` 的留言
- 自動遞增 `resent_count` 計數器
- 根據留言類型自動選擇：
  - 一般留言：使用 `/msg [<lora_msg_id>]<內容>` 格式
  - 回覆留言：使用 `/reply <lora_msg_id>[<parent_lora_msg_id>]<內容>` 格式
- 自動發送 `/author` 和 `/color` 後續指令

**回應範例**：
```json
{
  "success": true,
  "note_id": "uuid-1234",
  "board_id": "YourChannelName",
  "resent_count": 1
}
```

**錯誤回應**：
```json
{
  "success": false,
  "error": "Only LoRa sent notes can be resent"
}
```

---

### 8.9 取得留言的 ACK 記錄

**端點**：`GET /api/boards/<board_id>/notes/<note_id>/acks`

**參數**：
- `board_id`（路徑參數）：留言板 ID
- `note_id`（路徑參數）：留言 ID

**說明**：取得指定留言的所有 ACK 確認記錄，顯示哪些 LoRa 節點已確認接收此留言

**回應範例**：
```json
{
  "success": true,
  "note_id": "uuid-1234",
  "acks": [
    {
      "ackId": "ack-uuid-5678",
      "loraNodeId": "lora-a1b2c3d4",
      "displayId": "LoRa-c3d4",
      "createdAt": 1735456200000,
      "updatedAt": 1735456200000
    },
    {
      "ackId": "ack-uuid-9012",
      "loraNodeId": "lora-e5f6g7h8",
      "displayId": "LoRa-g7h8",
      "createdAt": 1735456260000,
      "updatedAt": 1735456260000
    }
  ],
  "count": 2
}
```

**說明**：
- `ackId`：ACK 記錄的唯一識別碼
- `loraNodeId`：發送 ACK 的 LoRa 節點完整 ID
- `displayId`：節點 ID 的顯示名稱（簡化版）
- `createdAt`：首次接收 ACK 的時間戳記
- `updatedAt`：最後一次接收 ACK 的時間戳記
- ACK 記錄按建立時間降序排列（最新的在前）

---

### API 權限說明

- **作者驗證**：所有修改操作（更新、刪除、封存、變更顏色、重新發送）都需要提供正確的 `author_key`
- **狀態限制**：
  - `LAN only` 留言：可編輯、可刪除
  - `LoRa sent` 留言：僅可變更顏色、封存或重新發送，不可編輯內容或直接刪除
  - `LoRa received` 留言：僅可變更顏色或封存，不可編輯內容或直接刪除

---

## 附錄

### 系統架構圖

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│  Web Client │◄───────►│  Flask App   │◄───────►│  Meshtastic │
│  (Browser)  │ Socket  │  + SocketIO  │  Serial │   Device    │
└─────────────┘  .IO    └──────────────┘         └─────────────┘
                              │
                              ▼
                        ┌──────────┐
                        │ SQLite   │
                        │ Database │
                        └──────────┘
```

### 相關檔案

- **主程式**：`app_noteboard.py`
- **設定檔**：`config.py`
- **前端模板**：`templates/app_noteboard/index.html`
- **前端靜態資源**：`static/app_noteboard/`
- **資料庫**：`noteboard.db`（自動建立）

### 開發者資訊

- **Python 版本**：3.x
- **主要套件**：Flask, Flask-SocketIO, eventlet, meshtastic, pubsub
- **前端技術**：HTML5, CSS3, JavaScript, Socket.IO Client

### 授權

本專案採用 MIT 授權條款。
