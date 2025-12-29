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

### 資料狀態

1. **LAN only**：留言先儲存於本地資料庫，等待 LoRa 輪到排程與連線後才自動發送
2. **LoRa sent**：留言成功透過 LoRa 發送後，狀態更新為 `LoRa sent`
3. **LoRa received**：從其他 LoRa 節點接收的留言

## 2. 啟用方式

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

#### 方式二：使用 Systemd 服務，開機自動啟動
```bash
sudo systemctl start meshbridge.service
sudo systemctl status meshbridge.service
```

```bash
sudo systemctl enable meshbridge.service
```

### 存取介面

- **本地存取**：`http://10.0.0.1` 或 `http://noteboard.meshbridge.com`
- **服務埠號**：Port 80 (HTTP)
- **WebSocket**：自動連接至相同主機

## 3. config.py 設定說明

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
```

### 注意事項

- **頻道名稱**：`BOARD_MESSAGE_CHANEL_NAME` 必須與 Meshtastic 裝置上設定的頻道名稱完全一致（區分大小寫）
- **發送間隔**：`SEND_INTERVAL_SECOND` 建議設定在 30-180 秒之間，避免 LoRa 頻寬阻塞

## 4. LoRa 指令說明

NoteBoard 使用特定格式的文字訊息在 Meshmatic LoRa 網路的Channel上傳輸，以下為各指令格式與用途。

### 4.1 新增留言

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

### 4.2 重發留言(用來補發送未收到的訊息用，尚未實作)

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

### 4.3 設定作者

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

### 4.4 設定顏色

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

### 4.5 封存留言

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

### 4.6 回覆留言

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

### 4.7 重送回覆留言(用來補發送未收到的訊息用，尚未實作)

**格式**：`/reply <lora_msg_id>[<parent_lora_msg_id>]<留言內容>`


**用途**：重新發送已存在的留言（使用指定的 `lora_msg_id`），關聯至指定的父留言

**範例**：
```
/reply <0123456789>[1234567890]這是對該留言的回覆
```


---

### 指令發送流程

1. **Web 端建立留言** → 儲存為 `LAN only` 狀態
2. **排程器發送** → 透過 LoRa 發送 `/msg [new]` 指令
3. **接收 ACK** → 更新狀態為 `LoRa sent`，記錄 `lora_msg_id`
4. **發送後續指令** → 自動發送 `/author` 和 `/color` 指令
5. **其他節點接收** → 解析指令並同步至本地資料庫

## 5. SQLite 資料庫欄位說明

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

### 欄位說明補充

#### status 狀態值
- **`LAN only`**：留言僅存在於本地，尚未發送至 LoRa
- **`LoRa sent`**：留言已成功發送至 LoRa 網路
- **`LoRa received`**：從其他 LoRa 節點接收的留言

#### is_temp_parent_note
- 當接收到回覆留言，但父留言尚未存在於本地時，設定為 1
- 用於處理訊息接收順序不一致的情況

#### is_need_update_lora
- 當留言的顏色或封存狀態變更時，設定為 1
- 排程器會自動發送更新指令至 LoRa 網路

## 6. RESTful API 說明

所有 API 端點的 Base URL 為：`http://10.0.0.1` 或 `http://chat.meshbridge.com`

### 6.1 取得使用者 UUID 

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

### 6.2 取得留言列表

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

### 6.3 建立新留言

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

### 6.4 更新留言

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

### 6.5 變更留言顏色

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

### 6.6 封存留言

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

### 6.7 刪除留言

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

### API 權限說明

- **作者驗證**：所有修改操作（更新、刪除、封存、變更顏色）都需要提供正確的 `author_key`
- **狀態限制**：
  - `LAN only` 留言：可編輯、可刪除
  - `LoRa sent` / `LoRa received` 留言：僅可變更顏色或封存，不可編輯內容或直接刪除

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
