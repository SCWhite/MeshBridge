# MBTiles 離線地圖安裝與設定

NoteBoard 支援 MBTiles 格式的離線地圖，讓您在無網路環境下也能使用完整的地圖功能。

## 下載離線地圖檔

### 台灣地區地圖

台灣地區使用者可從**國土測繪圖資服務雲**網站，下載免費的政府開放資料：

**地圖名稱**：[政府開放資料]臺灣通用電子地圖（套疊等高線）MBTiles 檔（APP 離線地圖用）

**下載連結**：[https://maps.nlsc.gov.tw/MbIndex_qryPage.action?fun=8](https://maps.nlsc.gov.tw/MbIndex_qryPage.action?fun=8)

### 其他地區地圖

如需使用其他地區的離線地圖，可從以下來源取得：
- **OpenStreetMap**：使用開源工具（如 TileMill、Mapbox Studio）自行製作
- **第三方地圖服務**：部分地圖服務提供商提供 MBTiles 格式下載

## 安裝離線地圖

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

## MBTiles 支援說明

### 多檔支援
- ✅ **多地區支援**：可同時放置多個不同地區的 `.mbtiles` 檔案
- ✅ **圖層套疊**：支援多個檔案針對同一地區進行圖層套疊（如：底圖 + 等高線 + 路網）

### 格式建議
- **推薦格式**：Raster（點陣圖）格式
- **原因**：Raster 格式的地圖完全自包含，不依賴網路字型，可確保在完全離線環境下正常顯示
- **Vector 格式注意事項**：Vector（向量圖）格式的地圖可能使用網路字型渲染文字圖層，在離線環境下可能無法正常顯示文字標籤

## config.py 地圖相關設定

系統會自動載入指定資料夾中的所有 `.mbtiles` 檔案。如需自訂設定，可在 `config.py` 中新增以下參數：

```python
# 地圖相關設定
NOTEBOARD_MBTILES_FOLDER = "./maps"  # 地圖檔案路徑（預設值：./maps）
NOTEBOARD_MBTILES_LAYER_MODE = "auto"  # 圖層模式（預設值：auto）
```

### 參數說明

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

## 地圖初始中心點優先順序

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
