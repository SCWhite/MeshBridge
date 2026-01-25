import eventlet
eventlet.monkey_patch()

import time
import sys
import os
import glob
import sqlite3
import uuid
import re
import subprocess
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, jsonify, make_response, session
from flask_socketio import SocketIO, emit
from meshtastic.serial_interface import SerialInterface
from pubsub import pub
import config
from config import BOARD_MESSAGE_CHANEL_NAME, SEND_INTERVAL_SECOND, ACK_TIMEOUT_SECONDS, MAX_NOTE_SHOW, MAX_ARCHIVED_NOTE_SHOW, NOTEBOARD_ADMIN_PASSCODE
NOTEBOARD_MBTILES_FOLDER = getattr(config, 'NOTEBOARD_MBTILES_FOLDER', './maps')
NOTEBOARD_MBTILES_LAYER_MODE = getattr(config, 'NOTEBOARD_MBTILES_LAYER_MODE', 'auto')
from app import get_power_status

# 抑制 Meshtastic 的 protobuf 解析錯誤日誌（這些是暫時性錯誤，不影響功能）
logging.getLogger('meshtastic.mesh_interface').setLevel(logging.CRITICAL)
logging.getLogger('meshtastic.stream_interface').setLevel(logging.CRITICAL)

# Monkey patch Meshtastic 的錯誤處理，抑制 protobuf 解析錯誤
def patch_meshtastic_error_handling():
    """修補 Meshtastic 庫的錯誤處理，抑制暫時性的 protobuf 解析錯誤"""
    try:
        from meshtastic import mesh_interface
        import io
        import contextlib
        
        original_handleFromRadio = mesh_interface.MeshInterface._handleFromRadio
        
        def patched_handleFromRadio(self, fromRadioBytes):
            # 使用 context manager 來抑制 stderr 輸出
            stderr_suppressor = io.StringIO()
            try:
                with contextlib.redirect_stderr(stderr_suppressor):
                    return original_handleFromRadio(self, fromRadioBytes)
            except Exception as e:
                error_msg = str(e)
                # 只抑制 protobuf 解析錯誤，其他錯誤仍然拋出
                if "Error parsing message" in error_msg or "DecodeError" in error_msg:
                    # 靜默忽略這些暫時性錯誤（包括 traceback）
                    pass
                else:
                    # 其他錯誤仍然拋出，並顯示 stderr
                    stderr_content = stderr_suppressor.getvalue()
                    if stderr_content:
                        sys.stderr.write(stderr_content)
                    raise
        
        mesh_interface.MeshInterface._handleFromRadio = patched_handleFromRadio
        print("[系統] 已修補 Meshtastic protobuf 錯誤處理")
    except Exception as e:
        print(f"[系統] 修補 Meshtastic 錯誤處理失敗 (可忽略): {e}")

# 在導入 SerialInterface 之後立即執行修補
patch_meshtastic_error_handling()

try:
    from config import NOTEBOARD_POST_PASSCODE
except ImportError:
    NOTEBOARD_POST_PASSCODE = ""

try:
    from config import UID_SOURCE
except ImportError:
    UID_SOURCE = "mac"

# 控制是否印出完整 LoRa 封包資訊
IS_PRINT_LORA_PACKAGE = False

# 驗證 BOARD_MESSAGE_CHANEL_NAME 設定
FORBIDDEN_CHANNEL_NAMES = ["MeshTW", "Emergency!"]

if not BOARD_MESSAGE_CHANEL_NAME or BOARD_MESSAGE_CHANEL_NAME.strip() == "":
    raise ValueError("BOARD_MESSAGE_CHANEL_NAME 不得為空")

if BOARD_MESSAGE_CHANEL_NAME in FORBIDDEN_CHANNEL_NAMES:
    raise ValueError(f"BOARD_MESSAGE_CHANEL_NAME 不得為: {', '.join(FORBIDDEN_CHANNEL_NAMES)}")

app = Flask(__name__, 
               template_folder='templates/app_noteboard',
               static_folder='static/app_noteboard')
app.config['SECRET_KEY'] = 'meshbridge_secret'
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

interface = None
current_dev_path = None
lora_connected = False
channel_validated = False
pending_ack = {}
send_interval = max(SEND_INTERVAL_SECOND, 10)

DB_PATH = 'noteboard.db'
MAX_NOTES = 200

admin_users = set()
user_last_locations = {}

COLOR_PALETTE = [
    'hsl(0, 70%, 85%)',      # 0: Red
    'hsl(30, 70%, 85%)',     # 1: Orange
    'hsl(60, 70%, 85%)',     # 2: Yellow
    'hsl(90, 70%, 85%)',     # 3: Light Green
    'hsl(120, 70%, 85%)',    # 4: Green
    'hsl(150, 70%, 85%)',    # 5: Teal
    'hsl(180, 70%, 85%)',    # 6: Cyan
    'hsl(210, 70%, 85%)',    # 7: Light Blue
    'hsl(240, 70%, 85%)',    # 8: Blue
    'hsl(270, 70%, 85%)',    # 9: Purple
    'hsl(300, 70%, 85%)',    # 10: Magenta
    'hsl(330, 70%, 85%)',    # 11: Pink
    'hsl(0, 0%, 85%)',       # 12: Light Gray
    'hsl(0, 0%, 75%)',       # 13: Gray
    'hsl(45, 80%, 85%)',     # 14: Gold
    'hsl(15, 80%, 85%)'      # 15: Coral
]

def init_database():
    """初始化 SQLite 資料庫"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            note_id TEXT PRIMARY KEY,
            reply_lora_msg_id TEXT,
            board_id TEXT NOT NULL,
            body TEXT NOT NULL,
            bg_color TEXT,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            author_key TEXT NOT NULL,
            rev INTEGER NOT NULL DEFAULT 1,
            deleted INTEGER NOT NULL DEFAULT 0,
            resent_count INTEGER NOT NULL DEFAULT 0,
            is_need_update_lora INTEGER NOT NULL DEFAULT 0,
            lora_msg_id TEXT,
            is_temp_parent_note INTEGER NOT NULL DEFAULT 0,
            is_pined_note INTEGER NOT NULL DEFAULT 0,
            resent_priority INTEGER NOT NULL DEFAULT 0,
            grid_mode TEXT NOT NULL DEFAULT '',
            grid_x INTEGER NOT NULL DEFAULT 0,
            grid_y INTEGER NOT NULL DEFAULT 0,
            lora_node_id TEXT,
            FOREIGN KEY (reply_lora_msg_id) REFERENCES notes(note_id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_board_id ON notes(board_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON notes(created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_deleted ON notes(deleted)')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ack_records (
            ack_id TEXT PRIMARY KEY,
            note_id TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            lora_node_id TEXT NOT NULL,
            FOREIGN KEY (note_id) REFERENCES notes(note_id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ack_note_id ON ack_records(note_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ack_created_at ON ack_records(created_at DESC)')
    
    conn.commit()
    conn.close()
    print("資料庫初始化完成")

def migrate_database():
    """檢查並執行資料庫遷移"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("PRAGMA table_info(notes)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'lora_node_id' not in columns:
            print("[資料庫遷移] 偵測到 notes 表缺少 lora_node_id 欄位，開始遷移...")
            cursor.execute('ALTER TABLE notes ADD COLUMN lora_node_id TEXT')
            conn.commit()
            print("[資料庫遷移] 已成功新增 lora_node_id 欄位")
        else:
            print("[資料庫遷移] notes 表已包含 lora_node_id 欄位，無需遷移")
    except Exception as e:
        print(f"[資料庫遷移] 遷移失敗: {e}")
    finally:
        conn.close()

def get_time():
    return time.strftime("%H:%M", time.localtime())

def format_note_time(timestamp_ms):
    """
    格式化便利貼時間顯示
    今天|1天前|2天前..n天前 (YYYY/MM/DD HH:MM)
    HH 為 24小時制
    """
    local_time = time.localtime(timestamp_ms / 1000)
    
    # 計算日期差異
    note_date = datetime.fromtimestamp(timestamp_ms / 1000).date()
    today = datetime.now().date()
    days_diff = (today - note_date).days
    
    # 格式化日期時間 (24小時制)
    formatted_datetime = time.strftime("%Y/%m/%d %H:%M", local_time)
    
    # 根據天數差異顯示相對時間
    if days_diff == 0:
        relative_time = "今天"
    elif days_diff == 1:
        relative_time = "昨天"
    else:
        relative_time = f"{days_diff}天前"
    
    return f"{relative_time} ({formatted_datetime})"

def generate_note_id():
    """生成唯一的 note_id"""
    return str(uuid.uuid4())

def generate_user_uuid():
    """生成用戶 UUID (8字元)"""
    alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789'
    import random
    return ''.join(random.choice(alphabet) for _ in range(8))

MAC_RE = re.compile(r"lladdr\s+([0-9a-f:]{17})", re.I)

def mac_from_ip(ip: str, iface: str = "wlan0") -> str | None:
    """從 IP 取得 MAC address (移除冒號)"""
    try:
        out = subprocess.run(
            ["ip", "neigh", "show", "dev", iface, ip],
            capture_output=True, text=True, check=False
        ).stdout
        m = MAC_RE.search(out)
        if m:
            mac_with_colons = m.group(1).lower()
            return mac_with_colons.replace(':', '')
        return None
    except Exception as e:
        print(f"Error getting MAC from IP {ip}: {e}")
        return None

def get_or_create_user_uuid():
    """從 session/cookie 取得或建立用戶 UUID"""
    if 'user_uuid' not in session:
        session['user_uuid'] = generate_user_uuid()
        session.permanent = True
    return session['user_uuid']

def generate_bg_color(author_key):
    """根據 author_key 生成背景顏色"""
    hash_val = 0
    for char in author_key:
        hash_val = ord(char) + ((hash_val << 5) - hash_val)
    h = abs(hash_val) % 360
    return f"hsl({h}, 70%, 85%)"

def get_color_from_palette(color_index):
    """從調色盤取得顏色 (0-15)"""
    try:
        index = int(color_index)
        if 0 <= index < len(COLOR_PALETTE):
            return COLOR_PALETTE[index]
    except (ValueError, TypeError):
        pass
    return COLOR_PALETTE[0]

def note_exists(note_id):
    """檢查 note_id 是否存在"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM notes WHERE note_id = ?', (note_id,))
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    except Exception as e:
        print(f"檢查 note 是否存在失敗: {e}")
        return False

def lora_msg_id_exists(lora_msg_id):
    """檢查 lora_msg_id 是否存在"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM notes WHERE lora_msg_id = ?', (lora_msg_id,))
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    except Exception as e:
        print(f"檢查 lora_msg_id 是否存在失敗: {e}")
        return False

def get_note_id_by_lora_msg_id(lora_msg_id):
    """透過 lora_msg_id 取得 note_id"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT note_id FROM notes WHERE lora_msg_id = ?', (lora_msg_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        print(f"透過 lora_msg_id 取得 note_id 失敗: {e}")
        return None

def save_or_update_ack_record(note_id, lora_node_id):
    """儲存或更新 ACK 記錄"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = int(time.time() * 1000)
        
        cursor.execute('''
            SELECT ack_id FROM ack_records 
            WHERE note_id = ? AND lora_node_id = ?
        ''', (note_id, lora_node_id))
        
        existing_record = cursor.fetchone()
        
        if existing_record:
            cursor.execute('''
                UPDATE ack_records 
                SET updated_at = ?
                WHERE note_id = ? AND lora_node_id = ?
            ''', (timestamp, note_id, lora_node_id))
            conn.commit()
            conn.close()
            print(f"  -> 已更新 ACK 記錄 (note_id={note_id}, lora_node_id={lora_node_id})")
            return True
        else:
            ack_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO ack_records (ack_id, note_id, created_at, updated_at, lora_node_id)
                VALUES (?, ?, ?, ?, ?)
            ''', (ack_id, note_id, timestamp, timestamp, lora_node_id))
            conn.commit()
            conn.close()
            print(f"  -> 已新建 USER ACK 記錄 (ack_id={ack_id}, note_id={note_id}, lora_node_id={lora_node_id})")
            return True
    except Exception as e:
        print(f"儲存或更新 USER ACK 記錄失敗: {e}")
        return False

def update_note_color(lora_msg_id, author_key, color_index, need_lora_update=False):
    """透過 lora_msg_id 更新 note 的背景顏色，需驗證 author_key"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        bg_color = get_color_from_palette(color_index)
        timestamp = int(time.time() * 1000)
        
        if need_lora_update:
            cursor.execute('''
                UPDATE notes 
                SET bg_color = ?, updated_at = ?, rev = rev + 1, is_need_update_lora = 1
                WHERE lora_msg_id = ? AND author_key = ?
            ''', (bg_color, timestamp, lora_msg_id, author_key))
        else:
            cursor.execute('''
                UPDATE notes 
                SET bg_color = ?, updated_at = ?, rev = rev + 1
                WHERE lora_msg_id = ? AND author_key = ?
            ''', (bg_color, timestamp, lora_msg_id, author_key))
        
        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        return affected_rows > 0
    except Exception as e:
        print(f"更新 note 顏色失敗: {e}")
        return False

def update_note_color_by_note_id(note_id, author_key, color_index, need_lora_update=False):
    """透過 note_id 更新 note 的背景顏色，需驗證 author_key"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        bg_color = get_color_from_palette(color_index)
        timestamp = int(time.time() * 1000)
        
        if need_lora_update:
            cursor.execute('''
                UPDATE notes 
                SET bg_color = ?, updated_at = ?, rev = rev + 1, is_need_update_lora = 1
                WHERE note_id = ? AND author_key = ?
            ''', (bg_color, timestamp, note_id, author_key))
        else:
            cursor.execute('''
                UPDATE notes 
                SET bg_color = ?, updated_at = ?, rev = rev + 1
                WHERE note_id = ? AND author_key = ?
            ''', (bg_color, timestamp, note_id, author_key))
        
        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        return affected_rows > 0
    except Exception as e:
        print(f"更新 note 顏色失敗: {e}")
        return False

def update_note_author(lora_msg_id, author_key):
    """更新 note 的 author_key"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = int(time.time() * 1000)
        
        cursor.execute('''
            UPDATE notes 
            SET author_key = ?, updated_at = ?, rev = rev + 1
            WHERE lora_msg_id = ?
        ''', (author_key, timestamp, lora_msg_id))
        
        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        return affected_rows > 0
    except Exception as e:
        print(f"更新 note author_key 失敗: {e}")
        return False

def archive_note(note_id, author_key, need_lora_update=False):
    """將 note 標記為已刪除 (deleted=1)，需驗證 author_key"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = int(time.time() * 1000)
        
        if need_lora_update:
            cursor.execute('''
                UPDATE notes 
                SET deleted = 1, is_pined_note = 0, updated_at = ?, is_need_update_lora = 1
                WHERE note_id = ? AND author_key = ?
            ''', (timestamp, note_id, author_key))
        else:
            cursor.execute('''
                UPDATE notes 
                SET deleted = 1, is_pined_note = 0, updated_at = ?
                WHERE note_id = ? AND author_key = ?
            ''', (timestamp, note_id, author_key))
        
        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        return affected_rows > 0
    except Exception as e:
        print(f"封存 note 失敗: {e}")
        return False

def archive_note_by_lora_msg_id(lora_msg_id, author_key):
    """透過 lora_msg_id 將 note 標記為已刪除 (deleted=1)，需驗證 author_key"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = int(time.time() * 1000)
        
        cursor.execute('''
            UPDATE notes 
            SET deleted = 1, is_pined_note = 0, updated_at = ?
            WHERE lora_msg_id = ? AND author_key = ?
        ''', (timestamp, lora_msg_id, author_key))
        
        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        return affected_rows > 0
    except Exception as e:
        print(f"封存 note 失敗: {e}")
        return False

def pin_note_by_lora_msg_id(lora_msg_id, author_key):
    """透過 lora_msg_id 將 note 標記為置頂 (is_pined_note=1)，需驗證 author_key 和 lora_msg_id 存在"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        timestamp = int(time.time() * 1000)
        
        cursor.execute('''
            SELECT board_id, reply_lora_msg_id, is_temp_parent_note, deleted
            FROM notes 
            WHERE lora_msg_id = ? AND author_key = ?
        ''', (lora_msg_id, author_key))
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return False
        
        board_id = result['board_id']
        reply_lora_msg_id = result['reply_lora_msg_id']
        is_temp_parent_note = result['is_temp_parent_note']
        deleted = result['deleted']
        
        if reply_lora_msg_id is not None and reply_lora_msg_id != '':
            print(f"  -> 無法置頂回覆訊息")
            conn.close()
            return False
        
        if is_temp_parent_note == 1:
            print(f"  -> 無法置頂臨時父訊息")
            conn.close()
            return False
        
        if deleted == 1:
            print(f"  -> 無法置頂已封存的訊息")
            conn.close()
            return False
        
        cursor.execute('''
            UPDATE notes 
            SET is_pined_note = 0, updated_at = ?
            WHERE board_id = ? AND is_pined_note = 1
        ''', (timestamp, board_id))
        
        cursor.execute('''
            UPDATE notes 
            SET is_pined_note = 1, updated_at = ?
            WHERE lora_msg_id = ? AND author_key = ?
        ''', (timestamp, lora_msg_id, author_key))
        
        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        return affected_rows > 0
    except Exception as e:
        print(f"置頂 note 失敗: {e}")
        return False

def save_lora_note(lora_msg_id, board_id, body, bg_color='', author_key='', reply_lora_msg_id=None, lora_node_id=''):
    """儲存 LoRa 接收的 note"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = int(time.time() * 1000)
        status = 'LoRa received'
        note_id = generate_note_id()
        
        cursor.execute('''
            INSERT INTO notes (note_id, reply_lora_msg_id, board_id, body, bg_color, status, 
                             created_at, updated_at, author_key, rev, deleted, lora_msg_id, lora_node_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
        ''', (note_id, reply_lora_msg_id, board_id, body, bg_color, status, timestamp, timestamp, author_key, lora_msg_id, lora_node_id))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"儲存 LoRa note 失敗: {e}")
        return False

def get_oldest_lan_only_note(board_id):
    """取得最舊的 LAN only 狀態的 note"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT note_id, body, bg_color, author_key, created_at, reply_lora_msg_id
            FROM notes 
            WHERE board_id = ? AND (status = 'LAN only' OR status = 'Sending') AND deleted = 0
            ORDER BY created_at ASC
            LIMIT 1
        ''', (board_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'note_id': row['note_id'],
                'body': row['body'],
                'bg_color': row['bg_color'],
                'author_key': row['author_key'],
                'created_at': row['created_at'],
                'reply_lora_msg_id': row['reply_lora_msg_id']
            }
        return None
    except Exception as e:
        print(f"取得最舊 LAN only note 失敗: {e}")
        return None

def get_note_need_update_lora(board_id):
    """取得一個需要更新到 LoRa 的 note (is_need_update_lora=1)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT note_id, body, bg_color, author_key, deleted, lora_msg_id
            FROM notes 
            WHERE board_id = ? AND is_need_update_lora = 1
            ORDER BY updated_at ASC
            LIMIT 1
        ''', (board_id,))
        
        row = cursor.fetchone()
        
        if row:
            note_data = {
                'note_id': row['note_id'],
                'body': row['body'],
                'bg_color': row['bg_color'],
                'author_key': row['author_key'],
                'deleted': row['deleted'],
                'lora_msg_id': row['lora_msg_id']
            }
            
            timestamp = int(time.time() * 1000)
            cursor.execute('''
                UPDATE notes 
                SET is_need_update_lora = 0, updated_at = ?
                WHERE note_id = ?
            ''', (timestamp, row['note_id']))
            
            conn.commit()
            conn.close()
            return note_data
        
        conn.close()
        return None
    except Exception as e:
        print(f"取得需要更新的 note 失敗: {e}")
        return None

def update_note_status(note_id, status):
    """更新 note 的 status"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = int(time.time() * 1000)
        
        cursor.execute('''
            UPDATE notes 
            SET status = ?, updated_at = ?
            WHERE note_id = ?
        ''', (status, timestamp, note_id))
        
        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        return affected_rows > 0
    except Exception as e:
        print(f"更新 note status 失敗: {e}")
        return False

def update_note_lora_msg_id(note_id, lora_msg_id):
    """更新 note 的 lora_msg_id"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = int(time.time() * 1000)
        
        cursor.execute('''
            UPDATE notes 
            SET lora_msg_id = ?, updated_at = ?
            WHERE note_id = ?
        ''', (lora_msg_id, timestamp, note_id))
        
        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        return affected_rows > 0
    except Exception as e:
        print(f"更新 note lora_msg_id 失敗: {e}")
        return False

def get_notes_from_db(board_id, include_deleted=False):
    """從資料庫取得 notes"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        limit = (MAX_NOTE_SHOW + MAX_ARCHIVED_NOTE_SHOW) if include_deleted else MAX_NOTE_SHOW
        
        if include_deleted:
            cursor.execute('''
                SELECT note_id, reply_lora_msg_id, body, bg_color, status, 
                       created_at, updated_at, author_key, rev, deleted, lora_msg_id, is_temp_parent_note, is_pined_note, lora_node_id
                FROM notes 
                WHERE board_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (board_id, limit))
        else:
            cursor.execute('''
                SELECT note_id, reply_lora_msg_id, body, bg_color, status, 
                       created_at, updated_at, author_key, rev, deleted, lora_msg_id, is_temp_parent_note, is_pined_note, lora_node_id
                FROM notes 
                WHERE board_id = ? AND deleted = 0
                ORDER BY created_at DESC
                LIMIT ?
            ''', (board_id, limit))
        
        rows = cursor.fetchall()
        notes = []
        for row in rows:
            created_time = format_note_time(row['created_at'])
            author_display = row['author_key']
            if author_display.startswith('lora-'):
                raw_id = author_display.replace('lora-', '')
                author_display = f"LoRa-{raw_id[-4:]}" if len(raw_id) > 4 else raw_id
            elif author_display.startswith('user-'):
                author_display = "WebUser"
            
            lora_node_id = row['lora_node_id'] or ''
            sender_node_display = ''
            if lora_node_id and lora_node_id.startswith('lora-'):
                raw_node_id = lora_node_id.replace('lora-', '')
                sender_node_display = f"LoRa-{raw_node_id[-4:]}" if len(raw_node_id) > 4 else raw_node_id
            
            notes.append({
                'noteId': row['note_id'],
                'replyLoraMessageId': row['reply_lora_msg_id'],
                'text': row['body'],
                'bgColor': row['bg_color'],
                'status': row['status'],
                'time': created_time,
                'timestamp': row['created_at'],
                'userId': row['author_key'],
                'sender': author_display,
                'loraSuccess': row['status'] == 'LoRa sent',
                'source': 'lora' if row['author_key'].startswith('lora-') else 'local',
                'rev': row['rev'],
                'archived': row['deleted'] == 1,
                'loraMessageId': row['lora_msg_id'],
                'isTempParentNote': row['is_temp_parent_note'] == 1,
                'isPinedNote': row['is_pined_note'] == 1,
                'loraNodeId': lora_node_id,
                'senderNodeDisplay': sender_node_display
            })
        
        conn.close()
        return notes
    except Exception as e:
        print(f"從資料庫取得 notes 失敗: {e}")
        return []

def get_channel_name(interface, channel_index):
    """根據 channel index 取得 channel name"""
    try:
        if interface and interface.localNode and interface.localNode.channels:
            for ch in interface.localNode.channels:
                if ch.settings and ch.index == channel_index:
                    return ch.settings.name if ch.settings.name else f"Channel-{channel_index}"
        return f"Channel-{channel_index}"
    except Exception as e:
        return f"Channel-{channel_index}"

def get_channel_index(interface, channel_name):
    """根據 channel name 取得 channel index"""
    try:
        if interface and interface.localNode and interface.localNode.channels:
            for ch in interface.localNode.channels:
                if ch.settings and ch.settings.name == channel_name:
                    return ch.index
        return 0
    except Exception as e:
        return 0

def get_color_index_from_palette(bg_color):
    """從背景顏色取得調色盤索引"""
    try:
        if bg_color in COLOR_PALETTE:
            return COLOR_PALETTE.index(bg_color)
        return 0
    except Exception as e:
        return 0

def send_ack_delayed(lora_msg_id, interface_obj, channel_name, retry_count=0, max_retries=3):
    """延遲發送 USER ACK 命令（含重試機制）"""
    try:
        if not interface_obj:
            print(f"  -> [延遲 60 秒後] Interface 物件為 None，無法發送 ACK")
            return
        
        if not hasattr(interface_obj, 'localNode') or not interface_obj.localNode:
            print(f"  -> [延遲 60 秒後] Interface 未連接到本地節點，無法發送 ACK")
            return
        
        if not lora_connected:
            print(f"  -> [延遲 60 秒後] LoRa 設備未連接，無法發送 ACK")
            return
        
        ack_cmd = f"/ack {lora_msg_id}"
        interface_obj.sendText(ack_cmd, channelIndex=get_channel_index(interface_obj, channel_name))
        print(f"  -> [延遲 60 秒後] 已發送 USER ACK 命令: {ack_cmd}")
    except Exception as e:
        print(f"  -> [延遲 60 秒後] 發送 USER ACK 命令失敗 (嘗試 {retry_count + 1}/{max_retries + 1}): {e}")
        
        if retry_count < max_retries:
            retry_delay = 10
            print(f"  -> 將在 {retry_delay} 秒後重試...")
            eventlet.spawn_after(retry_delay, send_ack_delayed, lora_msg_id, interface_obj, channel_name, retry_count + 1, max_retries)
        else:
            print(f"  -> 已達最大重試次數，放棄發送 ACK 命令")

def onReceive(packet, interface):
    global pending_ack
    try:
        if 'decoded' in packet and packet['decoded'].get('portnum') == 'ROUTING_APP':
            request_id = packet['decoded'].get('requestId')
            if request_id and request_id in pending_ack:
                note_info = pending_ack[request_id]
                ack_packet_id = packet.get('id')
                lora_msg_id = str(request_id)
                print(f"[收到 ACK] request_id={request_id}, lora_msg_id={ack_packet_id}")
                
                if update_note_status(note_info['note_id'], 'LoRa sent'):
                    print(f"  -> 已更新 note {note_info['note_id']} 狀態為 'LoRa sent'")
                    
                    try:
                        update_note_lora_msg_id(note_info['note_id'], lora_msg_id)
                        print(f"  -> 已儲存 lora_msg_id: {lora_msg_id} (使用 request_id)")
                        
                        def send_author_and_color():
                            try:
                                author_cmd = f"/author [{lora_msg_id}]{note_info['author_key']}"
                                interface.sendText(author_cmd, channelIndex=get_channel_index(interface, BOARD_MESSAGE_CHANEL_NAME))
                                print(f"  -> [延遲 5 秒後] 已發送 author 命令: {author_cmd}")
                                
                                def send_color():
                                    try:
                                        color_index = get_color_index_from_palette(note_info['bg_color'])
                                        color_cmd = f"/color [{lora_msg_id}]{note_info['author_key']}, {color_index}"
                                        interface.sendText(color_cmd, channelIndex=get_channel_index(interface, BOARD_MESSAGE_CHANEL_NAME))
                                        print(f"  -> [延遲 10 秒後] 已發送 color 命令: {color_cmd}")
                                    except Exception as e:
                                        print(f"  -> [延遲 10 秒後] 發送 color 命令失敗: {e}")
                                
                                eventlet.spawn_after(5, send_color)
                                print(f"  -> 已排程在 5 秒後發送 color 命令")
                            except Exception as e:
                                print(f"  -> [延遲 5 秒後] 發送 author 命令失敗: {e}")
                        
                        eventlet.spawn_after(5, send_author_and_color)
                        print(f"  -> 已排程在 5 秒後發送 author 和 color 命令")
                    except Exception as e:
                        print(f"  -> 發送後續命令失敗: {e}")
                    
                    socketio.emit('refresh_notes', {'board_id': BOARD_MESSAGE_CHANEL_NAME})
                
                del pending_ack[request_id]
        
        if 'decoded' in packet and packet['decoded']['portnum'] == 'TEXT_MESSAGE_APP':
            msg = packet['decoded']['text']
            raw_id = packet.get('fromId')
            if raw_id is None:
                from_num = packet.get('from')
                if from_num is not None:
                    raw_id = f"!{from_num:08x}"
                else:
                    raw_id = 'Unknown'
            sender_display = f"LoRa-{raw_id[-4:]}" if raw_id and len(raw_id) > 4 else (raw_id or 'Unknown')
            lora_uuid = f"lora-{raw_id}"
            lora_msg_id = str(packet.get('id', 'N/A'))
            
            channel_index = packet.get('channel', 'N/A')
            channel_name = get_channel_name(interface, channel_index) if channel_index != 'N/A' else 'N/A'
            
            if channel_name != BOARD_MESSAGE_CHANEL_NAME:
                # print(f"[略過] Channel '{channel_name}' 不符合目標 '{BOARD_MESSAGE_CHANEL_NAME}'")
                return

            if IS_PRINT_LORA_PACKAGE:
                print(f"[收到 LoRa] 完整封包資訊:")
                print(f"  - 發送者 ID: {raw_id}")
                print(f"  - 顯示名稱: {sender_display}")
                print(f"  - 訊息內容: {msg}")
                print(f"  - 訊息 ID: {lora_msg_id}")
                print(f"  - 時間戳記: {packet.get('rxTime', packet.get('timestamp', 'N/A'))}")
                print(f"  - 接收 SNR: {packet.get('rxSnr', 'N/A')}")
                print(f"  - 接收 RSSI: {packet.get('rxRssi', 'N/A')}")
                print(f"  - Hop Limit: {packet.get('hopLimit', 'N/A')}")
                print(f"  - 目標 ID: {packet.get('toId', 'N/A')}")
                print(f"  - Channel Index: {channel_index}")
                print(f"  - Channel Name: {channel_name}")
                if 'decoded' in packet:
                    print(f"  - Port Number: {packet['decoded'].get('portnum', 'N/A')}")
                    print(f"  - 請求 ID: {packet['decoded'].get('requestId', 'N/A')}")
                print(f"  - 原始封包: {packet}")
                print("-" * 60)
            
            should_refresh = False
            
            if msg.startswith('/msg [new]'):
                body = msg[10:]
                print(f"[新訊息] lora_msg_id={lora_msg_id}, body={body}")
                if save_lora_note(
                    lora_msg_id=lora_msg_id,
                    board_id=BOARD_MESSAGE_CHANEL_NAME,
                    body=body,
                    bg_color='',
                    author_key='',
                    lora_node_id=lora_uuid
                ):
                    should_refresh = True
                    print(f"  -> 已儲存訊息，將在 60 秒後發送 USER ACK 命令")
                    eventlet.spawn_after(60, send_ack_delayed, lora_msg_id, interface, BOARD_MESSAGE_CHANEL_NAME)
                    
            elif msg.startswith('/msg [') and ']' in msg:
                end_bracket = msg.index(']')
                resend_lora_msg_id = msg[6:end_bracket]
                body = msg[end_bracket + 1:]
                print(f"[重發訊息] lora_msg_id={resend_lora_msg_id}, body={body}")
                
                if not lora_msg_id_exists(resend_lora_msg_id):
                    if save_lora_note(
                        lora_msg_id=resend_lora_msg_id,
                        board_id=BOARD_MESSAGE_CHANEL_NAME,
                        body=body,
                        bg_color='',
                        author_key='',
                        lora_node_id=lora_uuid
                    ):
                        should_refresh = True
                        print(f"[重發訊息寫入資料庫成功] lora_msg_id={resend_lora_msg_id}, body={body}")
                        print(f"  -> 已儲存訊息，將在 60 秒後發送 USER ACK 命令")
                        eventlet.spawn_after(60, send_ack_delayed, resend_lora_msg_id, interface, BOARD_MESSAGE_CHANEL_NAME)
                        # 更新以此訊息為父訊息的回覆，將 is_temp_parent_note 設為 0
                        try:
                            conn = sqlite3.connect(DB_PATH)
                            cursor = conn.cursor()
                            cursor.execute('''
                                UPDATE notes SET is_temp_parent_note = 0
                                WHERE reply_lora_msg_id = ? AND is_temp_parent_note = 1
                            ''', (resend_lora_msg_id,))
                            updated_count = cursor.rowcount
                            conn.commit()
                            conn.close()
                            if updated_count > 0:
                                print(f"  -> 已更新 {updated_count} 筆回覆的 is_temp_parent_note 為 0")
                        except Exception as e:
                            print(f"  -> 更新 is_temp_parent_note 失敗: {e}")
                else:
                    print(f"  -> lora_msg_id {resend_lora_msg_id} 已存在，略過建立資料")
                    print(f"  -> 但仍將在 60 秒後發送 USER ACK 命令")
                    eventlet.spawn_after(60, send_ack_delayed, resend_lora_msg_id, interface, BOARD_MESSAGE_CHANEL_NAME)
                    
            elif msg.startswith('/color [') and ']' in msg:
                end_bracket = msg.index(']')
                lora_msg_id = msg[8:end_bracket]
                params = msg[end_bracket + 1:].strip()
                
                if ',' in params:
                    parts = params.split(',', 1)
                    author_key = parts[0].strip()
                    color_id = parts[1].strip()
                    print(f"[設定顏色] lora_msg_id={lora_msg_id}, author_key={author_key}, color_id={color_id}")
                    
                    if update_note_color(lora_msg_id, author_key, color_id):
                        print(f"  -> 成功更新 note (lora_msg_id={lora_msg_id}) 的顏色")
                        should_refresh = True
                    else:
                        print(f"  -> 更新失敗，lora_msg_id {lora_msg_id} 不存在或 author_key 不符")
                else:
                    print(f"  -> 格式錯誤，應為 /color [lora_msg_id]author_key,color_id")
                    
            elif msg.startswith('/author [') and ']' in msg:
                end_bracket = msg.index(']')
                lora_msg_id = msg[9:end_bracket]
                author_key = msg[end_bracket + 1:].strip()
                print(f"[更新作者] lora_msg_id={lora_msg_id}, author_key={author_key}")
                
                if update_note_author(lora_msg_id, author_key):
                    print(f"  -> 成功更新 note (lora_msg_id={lora_msg_id}) 的 author_key 為 {author_key}")
                    should_refresh = True
                else:
                    print(f"  -> 更新失敗，lora_msg_id {lora_msg_id} 可能不存在")
                    
            elif msg.startswith('/archive [') and ']' in msg:
                end_bracket = msg.index(']')
                lora_msg_id = msg[10:end_bracket]
                author_key = msg[end_bracket + 1:].strip()
                print(f"[封存訊息] lora_msg_id={lora_msg_id}, author_key={author_key}")
                
                if archive_note_by_lora_msg_id(lora_msg_id, author_key):
                    print(f"  -> 成功封存 note (lora_msg_id={lora_msg_id})")
                    should_refresh = True
                else:
                    print(f"  -> 封存失敗，lora_msg_id {lora_msg_id} 不存在或 author_key 不符")
                    
            elif msg.startswith('/pin [') and ']' in msg:
                end_bracket = msg.index(']')
                lora_msg_id = msg[6:end_bracket]
                author_key = msg[end_bracket + 1:].strip()
                print(f"[置頂訊息] lora_msg_id={lora_msg_id}, author_key={author_key}")
                
                if pin_note_by_lora_msg_id(lora_msg_id, author_key):
                    print(f"  -> 成功置頂 note (lora_msg_id={lora_msg_id})")
                    should_refresh = True
                else:
                    print(f"  -> 置頂失敗，lora_msg_id {lora_msg_id} 不存在或 author_key 不符")
                    
            elif msg.startswith('/ack '):
                ack_lora_msg_id = msg[5:].strip()
                print(f"[收到 ACK] lora_msg_id={ack_lora_msg_id}, from={lora_uuid}")
                
                note_id = get_note_id_by_lora_msg_id(ack_lora_msg_id)
                if not note_id:
                    print(f"  -> 錯誤：找不到 lora_msg_id={ack_lora_msg_id} 對應的 note")
                else:
                    if save_or_update_ack_record(note_id, lora_uuid):
                        print(f"  -> 成功處理 USER ACK (note_id={note_id})")
                        socketio.emit('ack_received', {
                            'note_id': note_id,
                            'lora_node_id': lora_uuid
                        })
                    else:
                        print(f"  -> 處理 USER ACK 失敗")
                    
            elif msg.startswith('/reply <new>[') and ']' in msg:
                end_bracket = msg.index(']', 13)
                parent_lora_msg_id = msg[13:end_bracket]
                body = msg[end_bracket + 1:]
                print(f"[新回覆訊息] parent_lora_msg_id={parent_lora_msg_id}, body={body}")
                
                is_temp_parent = 0
                
                if lora_msg_id_exists(parent_lora_msg_id):
                    reply_lora_msg_id = parent_lora_msg_id
                    print(f"  -> 找到父訊息 lora_msg_id: {parent_lora_msg_id}")
                else:
                    reply_lora_msg_id = parent_lora_msg_id
                    is_temp_parent = 1
                    print(f"  -> 父訊息 lora_msg_id {parent_lora_msg_id} 不存在本機，仍將 reply_lora_msg_id 設為 {parent_lora_msg_id}，並設定 is_temp_parent_note=1")
                
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    timestamp = int(time.time() * 1000)
                    status = 'LoRa received'
                    reply_note_id = generate_note_id()
                    
                    cursor.execute('''
                        INSERT INTO notes (note_id, reply_lora_msg_id, board_id, body, bg_color, status, 
                                         created_at, updated_at, author_key, rev, deleted, lora_msg_id, is_temp_parent_note, lora_node_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?)
                    ''', (reply_note_id, reply_lora_msg_id, BOARD_MESSAGE_CHANEL_NAME, body, '', status, 
                          timestamp, timestamp, '', lora_msg_id, is_temp_parent, lora_uuid))
                    
                    conn.commit()
                    conn.close()
                    should_refresh = True
                    print(f"  -> 成功儲存回覆訊息，將在 60 秒後發送 USER ACK 命令")
                    eventlet.spawn_after(60, send_ack_delayed, lora_msg_id, interface, BOARD_MESSAGE_CHANEL_NAME)
                except Exception as e:
                    print(f"  -> 儲存回覆訊息失敗: {e}")
                    
            elif msg.startswith('/reply <') and '>[' in msg and ']' in msg:
                # 重發回覆格式: /reply <resend_lora_msg_id>[parent_lora_msg_id]body
                # resend_lora_msg_id 是這則回覆的 lora_msg_id
                # parent_lora_msg_id 是父訊息的 lora_msg_id
                end_angle = msg.index('>')
                resend_lora_msg_id = msg[8:end_angle]  # <xxxx> 中的值作為此回覆的 lora_msg_id
                
                start_bracket = end_angle + 1
                if msg[start_bracket] != '[':
                    print(f"[格式錯誤] /reply 重發格式應為 /reply <lora_msg_id>[parent_lora_msg_id]body")
                else:
                    end_bracket = msg.index(']', start_bracket)
                    parent_lora_msg_id = msg[start_bracket + 1:end_bracket]
                    body = msg[end_bracket + 1:]
                    print(f"[重發回覆訊息] resend_lora_msg_id={resend_lora_msg_id}, parent_lora_msg_id={parent_lora_msg_id}, body={body}")
                    
                    # 檢查此回覆是否已存在
                    if not lora_msg_id_exists(resend_lora_msg_id):
                        is_temp_parent = 0
                        
                        if lora_msg_id_exists(parent_lora_msg_id):
                            reply_lora_msg_id = parent_lora_msg_id
                            print(f"  -> 找到父訊息 lora_msg_id: {parent_lora_msg_id}")
                        else:
                            reply_lora_msg_id = parent_lora_msg_id
                            is_temp_parent = 1
                            print(f"  -> 父訊息 lora_msg_id {parent_lora_msg_id} 不存在本機，仍將 reply_lora_msg_id 設為 {parent_lora_msg_id}，並設定 is_temp_parent_note=1")
                        
                        try:
                            conn = sqlite3.connect(DB_PATH)
                            cursor = conn.cursor()
                            timestamp = int(time.time() * 1000)
                            status = 'LoRa received'
                            reply_note_id = generate_note_id()
                            
                            cursor.execute('''
                                INSERT INTO notes (note_id, reply_lora_msg_id, board_id, body, bg_color, status, 
                                                 created_at, updated_at, author_key, rev, deleted, lora_msg_id, is_temp_parent_note, lora_node_id)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?)
                            ''', (reply_note_id, reply_lora_msg_id, BOARD_MESSAGE_CHANEL_NAME, body, '', status, 
                                  timestamp, timestamp, '', resend_lora_msg_id, is_temp_parent, lora_uuid))
                            
                            conn.commit()
                            
                            # 更新以此回覆為父訊息的其他回覆，將 is_temp_parent_note 設為 0
                            cursor.execute('''
                                UPDATE notes SET is_temp_parent_note = 0
                                WHERE reply_lora_msg_id = ? AND is_temp_parent_note = 1
                            ''', (resend_lora_msg_id,))
                            updated_count = cursor.rowcount
                            conn.commit()
                            conn.close()
                            
                            should_refresh = True
                            print(f"[重發回覆寫入資料庫成功] lora_msg_id={resend_lora_msg_id}, body={body}")
                            print(f"  -> 已儲存訊息，將在 60 秒後發送 USER ACK 命令")
                            eventlet.spawn_after(60, send_ack_delayed, resend_lora_msg_id, interface, BOARD_MESSAGE_CHANEL_NAME)
                            if updated_count > 0:
                                print(f"  -> 已更新 {updated_count} 筆回覆的 is_temp_parent_note 為 0")
                        except Exception as e:
                            print(f"  -> 儲存重發回覆訊息失敗: {e}")
                    else:
                        print(f"  -> lora_msg_id {resend_lora_msg_id} 已存在，略過建立資料")
                        print(f"  -> 但仍將在 60 秒後發送 USER ACK 命令")
                        eventlet.spawn_after(60, send_ack_delayed, resend_lora_msg_id, interface, BOARD_MESSAGE_CHANEL_NAME)
                    
            else:
                if not msg.startswith('/'):
                    print(f"[非 noteboard 格式，已忽略] {msg}")
                else:
                    print(f"[未知命令格式，已忽略] {msg}")
            
            if should_refresh:
                socketio.emit('refresh_notes', {'board_id': BOARD_MESSAGE_CHANEL_NAME})
                
    except Exception as e:
        print(f"Packet Error: {e}")
        import traceback
        traceback.print_exc()

def scan_for_meshtastic():
    patterns = [
        "/dev/ttyACM*",           # Linux
        "/dev/ttyUSB*",           # Linux
        "/dev/cu.usbserial-*",    # Mac
        "/dev/cu.SLAB_USBtoUART*"    # Mac (CP210x driver)
    ]
    found_ports = []
    for p in patterns:
        found_ports.extend(glob.glob(p))
    return found_ports[0] if found_ports else None

def check_ack_timeout():
    """檢查並處理 ACK 超時的訊息"""
    global pending_ack
    current_time = int(time.time())
    timeout_requests = []
    
    for request_id, info in pending_ack.items():
        if current_time - info['timestamp'] > ACK_TIMEOUT_SECONDS:
            timeout_requests.append(request_id)
    
    for request_id in timeout_requests:
        info = pending_ack[request_id]
        note_id = info['note_id']
        print(f"[ACK 超時] request_id={request_id}, note_id={note_id}")
        print(f"  -> 將狀態從 'Sending' 改回 'LAN only'，等待重送")
        
        if update_note_status(note_id, 'LAN only'):
            print(f"  -> 成功更新 note {note_id} 狀態為 'LAN only'")
            socketio.emit('refresh_notes', {'board_id': BOARD_MESSAGE_CHANEL_NAME})
        
        del pending_ack[request_id]

def send_scheduler_loop():
    """定期發送 LAN only notes 和處理需要更新的 notes 的排程器"""
    global interface, lora_connected, pending_ack
    print(f"啟動發送排程器 (間隔: {send_interval} 秒)...")
    
    while True:
        try:
            eventlet.sleep(send_interval)
            
            check_ack_timeout()
            
            if not interface or not lora_connected:
                continue
            
            update_note = get_note_need_update_lora(BOARD_MESSAGE_CHANEL_NAME)
            if update_note:
                print(f"[排程器] 處理需要更新的 note_id={update_note['note_id']}")
                
                if not update_note['lora_msg_id']:
                    print(f"  -> 跳過：此 note 尚未發送至 LoRa，無 lora_msg_id")
                    continue
                
                try:
                    channel_index = get_channel_index(interface, BOARD_MESSAGE_CHANEL_NAME)
                    
                    if update_note['deleted'] == 1:
                        msg = f"/archive [{update_note['lora_msg_id']}]{update_note['author_key']}"
                        print(f"  -> 發送 archive 命令: {msg}")
                    else:
                        color_index = get_color_index_from_palette(update_note['bg_color'])
                        msg = f"/color [{update_note['lora_msg_id']}]{update_note['author_key']}, {color_index}"
                        print(f"  -> 發送 color 命令: {msg}")
                    
                    interface.sendText(msg, channelIndex=channel_index)
                    print(f"  -> 已發送更新命令")
                    socketio.emit('refresh_notes', {'board_id': BOARD_MESSAGE_CHANEL_NAME})
                    
                except Exception as e:
                    error_str = str(e)
                    print(f"[排程器] 發送更新命令失敗: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    # 檢測 USB 連線異常
                    if "Timed out waiting for connection completion" in error_str or \
                       "device disconnected" in error_str or \
                       "裝置路徑" in error_str and "已消失" in error_str:
                        error_msg = "發送失敗：USB連線異常中斷，可能是 Pi 電力供應不足、更換線材、或 Mesh 裝置需要重啟"
                        print(f"[排程器] {error_msg}")
                        socketio.emit('usb_connection_error', {'message': error_msg})
                
                continue
            
            note = get_oldest_lan_only_note(BOARD_MESSAGE_CHANEL_NAME)
            if not note:
                continue
            
            print(f"[排程器] 準備發送 note_id={note['note_id']}")
            print(f"  -> note 完整資料: {note}")
            
            try:
                channel_index = get_channel_index(interface, BOARD_MESSAGE_CHANEL_NAME)
                
                reply_lora_msg_id = note.get('reply_lora_msg_id')
                print(f"  -> reply_lora_msg_id 值: {reply_lora_msg_id} (type: {type(reply_lora_msg_id)})")
                
                if reply_lora_msg_id:
                    msg = f"/reply <new>[{reply_lora_msg_id}]{note['body']}"
                    print(f"  -> 使用 /reply 指令 (reply_lora_msg_id={reply_lora_msg_id})")
                else:
                    msg = f"/msg [new]{note['body']}"
                    print(f"  -> 使用 /msg 指令 (無 reply_lora_msg_id)")
                
                result = interface.sendText(msg, channelIndex=channel_index, wantAck=True)
                
                if result:
                    request_id = result.id if hasattr(result, 'id') else None
                    if request_id:
                        current_time = int(time.time())
                        pending_ack[request_id] = {
                            'note_id': note['note_id'],
                            'author_key': note['author_key'],
                            'bg_color': note['bg_color'],
                            'timestamp': current_time
                        }
                        update_note_status(note['note_id'], 'Sending')
                        print(f"  -> 已發送訊息，等待 ACK (request_id={request_id})")
                        socketio.emit('refresh_notes', {'board_id': BOARD_MESSAGE_CHANEL_NAME})
                    else:
                        print(f"  -> 已發送訊息，但無 request_id")
                else:
                    print(f"  -> 發送失敗")
                    
            except Exception as e:
                error_str = str(e)
                print(f"[排程器] 發送失敗: {e}")
                import traceback
                traceback.print_exc()
                
                # 檢測 USB 連線異常
                if "Timed out waiting for connection completion" in error_str or \
                   "device disconnected" in error_str or \
                   "裝置路徑" in error_str and "已消失" in error_str:
                    error_msg = "發送失敗：USB連線異常中斷，可能是 Pi 電力供應不足、更換線材、或 Mesh 裝置需要重啟"
                    print(f"[排程器] {error_msg}")
                    socketio.emit('usb_connection_error', {'message': error_msg})
                
        except Exception as e:
            error_str = str(e)
            print(f"[排程器] 錯誤: {e}")
            import traceback
            traceback.print_exc()

def validate_channel_name(interface):
    """驗證裝置的 channel name 是否與 config 中的設定一致"""
    global channel_validated
    try:
        if not interface or not interface.localNode or not interface.localNode.channels:
            return (False, f"無法讀取裝置 channel 資訊")
        
        for ch in interface.localNode.channels:
            if ch.settings and ch.settings.name == BOARD_MESSAGE_CHANEL_NAME:
                if ch.index == 0:
                    channel_validated = False
                    error_msg = f"Channel '{BOARD_MESSAGE_CHANEL_NAME}' 的 Index 不可以為 0"
                    print(f"[✗] {error_msg}")
                    return (False, error_msg)
                
                channel_validated = True
                print(f"[✓] Channel 名稱驗證成功: '{BOARD_MESSAGE_CHANEL_NAME}' (Index: {ch.index})")
                return (True, None)
        
        channel_validated = False
        error_msg = f"Channel 名稱驗證失敗: 找不到名為 '{BOARD_MESSAGE_CHANEL_NAME}' 的 channel"
        print(f"[✗] {error_msg}")
        print(f"[✗] 可用的 channels:")
        for ch in interface.localNode.channels:
            if ch.settings:
                print(f"    - Index {ch.index}: {ch.settings.name}")
        return (False, error_msg)
    except Exception as e:
        error_msg = f"Channel 驗證異常: {e}"
        print(f"[✗] {error_msg}")
        channel_validated = False
        return (False, error_msg)

def mesh_loop():
    global interface, current_dev_path, lora_connected, channel_validated
    print("啟動 Meshtastic 自動偵測與監聽 (NoteBoard 模式)...")
    
    while True:
        try:
            if interface is None:
                if lora_connected:
                    lora_connected = False
                    channel_validated = False
                    socketio.emit('lora_status', {'online': False, 'channel_validated': False, 'error_message': None, 'power_issue': False})
                
                target_port = scan_for_meshtastic()
                if target_port:
                    print(f"發現裝置於: {target_port}，檢查電源狀態...")
                    
                    # 檢查電源狀態
                    power_status = get_power_status()
                    if not power_status['is_normal']:
                        print(f"[✗] 電源狀態異常: {power_status['error_message']}")
                        print(f"[✗] 跳過連線，等待電源恢復正常...")
                        socketio.emit('lora_status', {
                            'online': False, 
                            'channel_validated': False,
                            'error_message': None,
                            'power_issue': True
                        })
                        time.sleep(5)
                        continue
                    else:
                        print(f"[✓] 電源狀態正常，嘗試連線...")
                    
                    # 嘗試連線，最多重試 3 次
                    max_retries = 3
                    retry_delay = 2
                    connection_success = False
                    
                    for attempt in range(max_retries):
                        try:
                            if attempt > 0:
                                print(f"  -> 重試連線 (嘗試 {attempt + 1}/{max_retries})...")
                                time.sleep(retry_delay * attempt)
                            
                            # 清空可能的殘留資料
                            try:
                                import serial
                                # 使用 exclusive=False 避免鎖定問題
                                temp_serial = serial.Serial(target_port, 115200, timeout=1, exclusive=False)
                                temp_serial.reset_input_buffer()
                                temp_serial.reset_output_buffer()
                                temp_serial.close()
                                time.sleep(2)
                                print(f"  -> 已清空 serial buffer，等待設備穩定...")
                            except Exception as e:
                                print(f"  -> 清空 buffer 失敗: {e}")
                                # 如果是鎖定問題，等待一下再繼續
                                if "lock" in str(e).lower() or "Resource temporarily unavailable" in str(e):
                                    print(f"  -> 偵測到 port 鎖定問題，等待 3 秒後繼續...")
                                    time.sleep(3)
                            
                            # 初始化 SerialInterface
                            interface = SerialInterface(devPath=target_port)
                            current_dev_path = target_port
                            pub.subscribe(onReceive, "meshtastic.receive")
                            
                            print(f">>> 成功連線至 {target_port} <<<")
                            connection_success = True
                            break
                            
                        except Exception as conn_error:
                            error_msg = str(conn_error)
                            print(f"  -> 連線失敗 (嘗試 {attempt + 1}/{max_retries}): {error_msg}")
                            
                            # 如果是 protobuf 解析錯誤，可能只是暫時性問題，繼續重試
                            if "Error parsing message" in error_msg or "DecodeError" in error_msg:
                                print(f"  -> 偵測到 protobuf 解析錯誤，將重試...")
                                if interface:
                                    try:
                                        interface.close()
                                    except:
                                        pass
                                    interface = None
                                continue
                            else:
                                # 其他錯誤直接拋出
                                raise
                    
                    if not connection_success:
                        print(f"  -> 連線失敗，已達最大重試次數")
                        time.sleep(3)
                        continue
                    
                    eventlet.sleep(2)
                    
                    is_channel_valid, error_msg = validate_channel_name(interface)
                    
                    lora_connected = True
                    socketio.emit('lora_status', {
                        'online': True, 
                        'channel_validated': is_channel_valid,
                        'error_message': error_msg,
                        'power_issue': False
                    })
                else:
                    time.sleep(3)

            else:
                if current_dev_path and not os.path.exists(current_dev_path):
                    raise Exception(f"裝置路徑 {current_dev_path} 已消失")
                
                if not lora_connected:
                    lora_connected = True
                    is_channel_valid, error_msg = validate_channel_name(interface)
                    socketio.emit('lora_status', {
                        'online': True, 
                        'channel_validated': is_channel_valid,
                        'error_message': error_msg,
                        'power_issue': False
                    })

        except Exception as e:
            error_str = str(e)
            print(f"Meshtastic 連線異常: {e}")
            if interface:
                try: interface.close()
                except: pass
            
            interface = None
            current_dev_path = None
            
            if lora_connected:
                lora_connected = False
                channel_validated = False
                socketio.emit('lora_status', {'online': False, 'channel_validated': False, 'error_message': None, 'power_issue': False})
                
                # 檢測 USB 連線異常，通知前端
                if "裝置路徑" in error_str and "已消失" in error_str:
                    error_msg = "發送失敗：USB連線異常中斷，可能是 Pi 電力供應不足、更換線材、或 Mesh 裝置需要重啟"
                    print(f"[mesh_loop] {error_msg}")
                    socketio.emit('usb_connection_error', {'message': error_msg})
            
            print("正在重置狀態... (3秒後重試)")
            time.sleep(3)
            
        eventlet.sleep(2)

@app.route('/api/config/channel_name', methods=['GET'])
def get_channel_name_config():
    """取得設定檔中的 channel name"""
    return jsonify({
        'success': True,
        'channel_name': BOARD_MESSAGE_CHANEL_NAME
    })

@app.route('/api/config/features', methods=['GET'])
def get_features_config():
    """取得所有功能的啟用狀態"""
    try:
        # 檢查地圖功能是否啟用
        map_enabled = False
        if NOTEBOARD_MBTILES_FOLDER and os.path.exists(NOTEBOARD_MBTILES_FOLDER):
            mbtiles_files = glob.glob(os.path.join(NOTEBOARD_MBTILES_FOLDER, '*.mbtiles'))
            map_enabled = len(mbtiles_files) > 0
        
        return jsonify({
            'success': True,
            'features': {
                'map_enabled': map_enabled,
                'location_picker_enabled': map_enabled
            }
        })
    except Exception as e:
        print(f"取得功能配置失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/config/post_passcode_required', methods=['GET'])
def get_post_passcode_required():
    """檢查是否需要張貼通關碼"""
    return jsonify({
        'success': True,
        'required': bool(NOTEBOARD_POST_PASSCODE and NOTEBOARD_POST_PASSCODE.strip())
    })

@app.route('/api/user/uuid', methods=['GET'])
def get_user_uuid():
    """取得或建立用戶 UUID (依照 UID_SOURCE 設定)"""
    if UID_SOURCE == "mac":
        client_ip = request.remote_addr
        mac_address = mac_from_ip(client_ip)
        if mac_address:
            return jsonify({
                'success': True,
                'uuid': mac_address
            })
        else:
            print(f"MAC 模式失敗，改用 flask_session 模式 (IP: {client_ip})")
            user_uuid = get_or_create_user_uuid()
            return jsonify({
                'success': True,
                'uuid': user_uuid
            })
    else:
        user_uuid = get_or_create_user_uuid()
        return jsonify({
            'success': True,
            'uuid': user_uuid
        })

@app.route('/api/user/admin/status', methods=['GET'])
def get_admin_status():
    """檢查當前用戶是否為管理者"""
    try:
        if UID_SOURCE == "mac":
            client_ip = request.remote_addr
            mac_address = mac_from_ip(client_ip)
            user_uuid = mac_address if mac_address else get_or_create_user_uuid()
        else:
            user_uuid = get_or_create_user_uuid()
        
        is_admin = user_uuid in admin_users
        return jsonify({
            'success': True,
            'is_admin': is_admin
        })
    except Exception as e:
        print(f"檢查管理者狀態失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/user/admin/authenticate', methods=['POST'])
def authenticate_admin():
    """驗證管理者 passcode"""
    try:
        data = request.get_json()
        passcode = data.get('passcode', '')
        
        if not passcode:
            return jsonify({
                'success': False,
                'error': 'Passcode is required'
            }), 400
        
        if passcode != NOTEBOARD_ADMIN_PASSCODE:
            return jsonify({
                'success': False,
                'error': 'Invalid passcode'
            }), 401
        
        if UID_SOURCE == "mac":
            client_ip = request.remote_addr
            mac_address = mac_from_ip(client_ip)
            user_uuid = mac_address if mac_address else get_or_create_user_uuid()
        else:
            user_uuid = get_or_create_user_uuid()
        
        admin_users.add(user_uuid)
        print(f"用戶 {user_uuid} 已認證為管理者")
        
        return jsonify({
            'success': True,
            'is_admin': True
        })
    except Exception as e:
        print(f"管理者認證失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/user/admin/logout', methods=['POST'])
def logout_admin():
    """登出管理者身份"""
    try:
        if UID_SOURCE == "mac":
            client_ip = request.remote_addr
            mac_address = mac_from_ip(client_ip)
            user_uuid = mac_address if mac_address else get_or_create_user_uuid()
        else:
            user_uuid = get_or_create_user_uuid()
        
        if user_uuid in admin_users:
            admin_users.remove(user_uuid)
            print(f"用戶 {user_uuid} 已登出管理者身份")
        
        return jsonify({
            'success': True,
            'is_admin': False
        })
    except Exception as e:
        print(f"管理者登出失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/boards/<board_id>/notes', methods=['GET'])
def get_board_notes(board_id):
    """取得指定 board 的所有 notes，包含 reply_notes 階層結構"""
    is_include_deleted = request.args.get('is_include_deleted', 'false').lower() == 'true'
    
    # 當 is_include_deleted=False 時，仍需取得所有 notes 以正確處理 reply 關係
    # 因為 deleted=0 的 reply note 可能指向 deleted=1 的 parent note
    all_notes_raw = get_notes_from_db(board_id, include_deleted=True)
    
    # 如果不顯示已封存，需要進行智慧過濾
    if not is_include_deleted:
        # 建立 lora_msg_id 到 note 的映射（用於查找 parent chain）
        lora_msg_id_to_note = {}
        for note in all_notes_raw:
            if note.get('loraMessageId'):
                lora_msg_id_to_note[note['loraMessageId']] = note
        
        # 收集所有 deleted=1 的 lora_msg_id（這些 parent 不應顯示）
        deleted_lora_msg_ids = set()
        for note in all_notes_raw:
            if note.get('archived') and note.get('loraMessageId'):
                deleted_lora_msg_ids.add(note['loraMessageId'])
        
        # 輔助函數：沿著 reply chain 往上找到第一個未刪除的 parent 的 lora_msg_id
        def find_valid_parent_lora_msg_id(reply_lora_msg_id, visited=None):
            if visited is None:
                visited = set()
            
            # 防止無限迴圈
            if reply_lora_msg_id in visited:
                return None
            visited.add(reply_lora_msg_id)
            
            # 如果指向的 parent 未刪除，直接返回
            if reply_lora_msg_id not in deleted_lora_msg_ids:
                return reply_lora_msg_id
            
            # 指向的 parent 已刪除，往上找
            parent_note = lora_msg_id_to_note.get(reply_lora_msg_id)
            if parent_note and parent_note.get('replyLoraMessageId'):
                # 繼續往上找
                return find_valid_parent_lora_msg_id(parent_note['replyLoraMessageId'], visited)
            
            # 已刪除的 parent 沒有更上層的 parent，返回 None（成為獨立 note）
            return None
        
        # 過濾 notes：只保留 deleted=0 的
        # 對於 reply note，如果其 replyLoraMessageId 指向已刪除的 parent，沿 chain 往上找
        # 如果 root 已刪除（valid_parent 為 None），則整串都不顯示
        all_notes = []
        for note in all_notes_raw:
            if not note.get('archived'):
                # deleted=0，保留
                # 檢查其 replyLoraMessageId 是否指向已刪除的 parent
                if note.get('replyLoraMessageId') in deleted_lora_msg_ids:
                    # 沿著 reply chain 往上找到第一個未刪除的 parent
                    valid_parent = find_valid_parent_lora_msg_id(note['replyLoraMessageId'])
                    if valid_parent is None:
                        # root 已刪除，整串都不顯示，跳過此 note
                        continue
                    note['replyLoraMessageId'] = valid_parent
                all_notes.append(note)
    else:
        all_notes = all_notes_raw
    
    # 建立 lora_msg_id 到 note 的映射
    lora_msg_id_map = {}
    for note in all_notes:
        if note.get('loraMessageId'):
            lora_msg_id_map[note['loraMessageId']] = note
    
    # 分離 parent notes 和 reply notes
    parent_notes = []
    reply_notes_pool = []
    
    for note in all_notes:
        if note.get('replyLoraMessageId') is None:
            # reply_lora_msg_id 為 null，是 parent note
            note['replyNotes'] = []
            parent_notes.append(note)
        elif note.get('isTempParentNote'):
            # reply_lora_msg_id 不為 null，但 is_temp_parent_note=1，也放入 parent_notes
            note['replyNotes'] = []
            parent_notes.append(note)
            reply_notes_pool.append(note)
        else:
            # reply_lora_msg_id 不為 null 且 is_temp_parent_note=0，是 reply note
            reply_notes_pool.append(note)
    
    # 為每個 parent note 建立 reply_notes
    for parent in parent_notes:
        parent_lora_msg_id = parent.get('loraMessageId')
        
        # 如果沒有 lora_msg_id，跳過（LAN only 的 note 不支援回覆）
        if not parent_lora_msg_id:
            continue
        
        # 收集所有回覆此 parent 的 notes
        replies = []
        
        # 遞迴函數：收集所有層級的回覆（只透過 lora_msg_id 匹配）
        def collect_replies(target_lora_msg_id, collected_ids=None):
            if collected_ids is None:
                collected_ids = set()
            
            if target_lora_msg_id in collected_ids:
                return []
            
            collected_ids.add(target_lora_msg_id)
            found_replies = []
            
            for reply_note in reply_notes_pool:
                if reply_note.get('replyLoraMessageId') == target_lora_msg_id:
                    found_replies.append(reply_note)
                    # 遞迴收集此 reply 的子回覆
                    child_lora_msg_id = reply_note.get('loraMessageId')
                    if child_lora_msg_id:
                        child_replies = collect_replies(child_lora_msg_id, collected_ids)
                        found_replies.extend(child_replies)
            
            return found_replies
        
        replies = collect_replies(parent_lora_msg_id)
        
        # 按時間排序（由舊到新）
        replies.sort(key=lambda x: x.get('timestamp', 0))
        
        parent['replyNotes'] = replies
    
    # 將置頂的 note 排到最前面
    parent_notes.sort(key=lambda x: (not x.get('isPinedNote', False), -x.get('timestamp', 0)))
    
    return jsonify({
        'success': True,
        'board_id': board_id,
        'notes': parent_notes,
        'count': len(parent_notes)
    })

@app.route('/api/boards/<board_id>/notes', methods=['POST'])
def create_board_note(board_id):
    """建立新的 note (LAN only 模式)，支援 parent_note_id 來建立回覆"""
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        author_key = data.get('author_key', 'user-unknown')
        color_index = data.get('color_index', 0)
        parent_note_id = data.get('parent_note_id', None)
        post_passcode = data.get('post_passcode', '')
        
        if not text:
            return jsonify({
                'success': False,
                'error': 'Text is required'
            }), 400
        
        # 檢查是否需要驗證張貼通關碼（非管理者時）
        if UID_SOURCE == "mac":
            client_ip = request.remote_addr
            mac_address = mac_from_ip(client_ip)
            user_uuid = mac_address if mac_address else get_or_create_user_uuid()
        else:
            user_uuid = get_or_create_user_uuid()
        
        is_admin = user_uuid in admin_users
        
        if not is_admin and NOTEBOARD_POST_PASSCODE and NOTEBOARD_POST_PASSCODE.strip():
            if post_passcode != NOTEBOARD_POST_PASSCODE:
                return jsonify({
                    'success': False,
                    'error': '發送用通關碼錯誤'
                }), 403
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = int(time.time() * 1000)
        note_id = generate_note_id()
        bg_color = get_color_from_palette(color_index)
        status = 'LAN only'
        
        # 處理回覆關係：parent_note_id 現在直接就是父 note 的 lora_msg_id
        reply_lora_msg_id = None
        if parent_note_id:
            # 驗證此 lora_msg_id 是否存在
            cursor.execute('''
                SELECT note_id FROM notes 
                WHERE lora_msg_id = ? AND board_id = ? AND deleted = 0
            ''', (parent_note_id, board_id))
            parent_result = cursor.fetchone()
            if parent_result:
                reply_lora_msg_id = parent_note_id
            else:
                conn.close()
                return jsonify({
                    'success': False,
                    'error': 'Parent note not found'
                }), 404
        
        cursor.execute('''
            INSERT INTO notes (note_id, reply_lora_msg_id, board_id, body, bg_color, status, 
                             created_at, updated_at, author_key, rev, deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
        ''', (note_id, reply_lora_msg_id, board_id, text, bg_color, status, timestamp, timestamp, author_key))
        
        cursor.execute('SELECT COUNT(*) FROM notes WHERE board_id = ? AND deleted = 0', (board_id,))
        count = cursor.fetchone()[0]
        
        if count > MAX_NOTES:
            cursor.execute('''
                UPDATE notes 
                SET deleted = 1, updated_at = ?
                WHERE note_id IN (
                    SELECT note_id FROM notes 
                    WHERE board_id = ? AND deleted = 0
                    ORDER BY created_at ASC 
                    LIMIT ?
                )
            ''', (timestamp, board_id, count - MAX_NOTES))
        
        conn.commit()
        conn.close()
        
        # 建立完整的 note 物件返回給前端
        created_time = format_note_time(timestamp)
        
        author_display = author_key
        if author_display.startswith('lora-'):
            raw_id = author_display.replace('lora-', '')
            author_display = f"LoRa-{raw_id[-4:]}" if len(raw_id) > 4 else raw_id
        elif author_display.startswith('user-'):
            author_display = "WebUser"
        
        note_obj = {
            'noteId': note_id,
            'replyLoraMessageId': reply_lora_msg_id,
            'text': text,
            'bgColor': bg_color,
            'status': status,
            'time': created_time,
            'timestamp': timestamp,
            'userId': author_key,
            'sender': author_display,
            'loraSuccess': False,
            'source': 'local',
            'rev': 1,
            'archived': False,
            'loraMessageId': None,
            'isTempParentNote': False
        }
        
        socketio.emit('refresh_notes', {'board_id': board_id})
        
        return jsonify({
            'success': True,
            'note_id': note_id,
            'board_id': board_id,
            'note': note_obj
        }), 201
        
    except Exception as e:
        print(f"建立 note 失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/boards/<board_id>/notes/<note_id>', methods=['PUT'])
def update_board_note(board_id, note_id):
    """更新 note 的內容與顏色 (僅限 author 本人且 status 為 LAN only)"""
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        author_key = data.get('author_key', 'user-unknown')
        color_index = data.get('color_index', 0)
        
        if not text:
            return jsonify({
                'success': False,
                'error': 'Text is required'
            }), 400
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT status, author_key FROM notes 
            WHERE note_id = ? AND board_id = ? AND deleted = 0
        ''', (note_id, board_id))
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Note not found'
            }), 404
        
        status, db_author_key = result
        
        if status != 'LAN only':
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Only LAN only notes can be edited (該便利貼可能已經完成送出.)'
            }), 403
        
        if db_author_key != author_key:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Not authorized to edit this note'
            }), 403
        
        timestamp = int(time.time() * 1000)
        bg_color = get_color_from_palette(color_index)
        
        cursor.execute('''
            UPDATE notes 
            SET body = ?, bg_color = ?, updated_at = ?, rev = rev + 1
            WHERE note_id = ? AND board_id = ?
        ''', (text, bg_color, timestamp, note_id, board_id))
        
        conn.commit()
        conn.close()
        
        socketio.emit('refresh_notes', {'board_id': board_id})
        
        return jsonify({
            'success': True,
            'note_id': note_id,
            'board_id': board_id
        }), 200
        
    except Exception as e:
        print(f"更新 note 失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/boards/<board_id>/notes/<note_id>/archive', methods=['POST'])
def archive_board_note(board_id, note_id):
    """封存 note (僅限 author 本人或管理者，且 status 非 LAN only)"""
    try:
        data = request.get_json() or {}
        author_key = data.get('author_key', 'user-unknown')
        is_admin_request = data.get('is_admin', False)
        
        # 取得當前使用者的 UUID
        if UID_SOURCE == "mac":
            client_ip = request.remote_addr
            mac_address = mac_from_ip(client_ip)
            current_user_uuid = mac_address if mac_address else get_or_create_user_uuid()
        else:
            current_user_uuid = get_or_create_user_uuid()
        
        # 驗證管理者身份
        is_verified_admin = is_admin_request and (current_user_uuid in admin_users)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT status, author_key FROM notes 
            WHERE note_id = ? AND board_id = ? AND deleted = 0
        ''', (note_id, board_id))
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Note not found'
            }), 404
        
        status, db_author_key = result
        
        if status == 'LAN only':
            conn.close()
            return jsonify({
                'success': False,
                'error': 'LAN only notes cannot be archived via this endpoint'
            }), 403
        
        # 權限檢查：
        # 1. 一般使用者：當前使用者 UUID 必須與資料庫中的 author_key 相符
        # 2. 管理者：已驗證為管理者即可封存任何便利貼
        is_own_note = (current_user_uuid == db_author_key)
        
        if not is_own_note and not is_verified_admin:
            conn.close()
            print(f"封存權限檢查失敗: current_user={current_user_uuid}, db_author={db_author_key}, is_admin={is_verified_admin}")
            return jsonify({
                'success': False,
                'error': 'Not authorized to archive this note'
            }), 403
        
        conn.close()
        
        if archive_note(note_id, db_author_key, need_lora_update=True):
            socketio.emit('refresh_notes', {'board_id': board_id})
            return jsonify({
                'success': True,
                'note_id': note_id,
                'board_id': board_id
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to archive note'
            }), 500
        
    except Exception as e:
        print(f"封存 note 失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/boards/<board_id>/notes/<note_id>/color', methods=['POST'])
def change_note_color(board_id, note_id):
    """變更 note 顏色 (僅限 author 本人或管理者，且 status 非 LAN only)"""
    try:
        data = request.get_json() or {}
        author_key = data.get('author_key', 'user-unknown')
        color_index = data.get('color_index', 0)
        is_admin_action = data.get('is_admin', False)
        
        # 檢查是否為管理者
        if UID_SOURCE == "mac":
            client_ip = request.remote_addr
            mac_address = mac_from_ip(client_ip)
            user_uuid = mac_address if mac_address else get_or_create_user_uuid()
        else:
            user_uuid = get_or_create_user_uuid()
        
        is_admin_user = user_uuid in admin_users
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT status, author_key FROM notes 
            WHERE note_id = ? AND board_id = ? AND deleted = 0
        ''', (note_id, board_id))
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Note not found'
            }), 404
        
        status, db_author_key = result
        
        if status == 'LAN only':
            conn.close()
            return jsonify({
                'success': False,
                'error': 'LAN only notes cannot change color via this endpoint'
            }), 403
        
        # 管理者可以變更任何人的 note 顏色
        if is_admin_action and is_admin_user:
            effective_author_key = db_author_key
        elif db_author_key != author_key:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Not authorized to change color of this note'
            }), 403
        else:
            effective_author_key = author_key
        
        conn.close()
        
        if update_note_color_by_note_id(note_id, effective_author_key, color_index, need_lora_update=True):
            socketio.emit('refresh_notes', {'board_id': board_id})
            return jsonify({
                'success': True,
                'note_id': note_id,
                'board_id': board_id
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to change note color'
            }), 500
        
    except Exception as e:
        print(f"變更 note 顏色失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/boards/<board_id>/notes/<note_id>/pin', methods=['POST'])
def pin_board_note(board_id, note_id):
    """置頂 note (僅限管理者)"""
    global interface, lora_connected
    try:
        if UID_SOURCE == "mac":
            client_ip = request.remote_addr
            mac_address = mac_from_ip(client_ip)
            user_uuid = mac_address if mac_address else get_or_create_user_uuid()
        else:
            user_uuid = get_or_create_user_uuid()
        
        if user_uuid not in admin_users:
            return jsonify({
                'success': False,
                'error': 'Not authorized - admin only'
            }), 403
        
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT note_id, reply_lora_msg_id, is_temp_parent_note, deleted, author_key, lora_msg_id
            FROM notes 
            WHERE note_id = ? AND board_id = ?
        ''', (note_id, board_id))
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Note not found'
            }), 404
        
        reply_lora_msg_id = result['reply_lora_msg_id']
        is_temp_parent_note = result['is_temp_parent_note']
        deleted = result['deleted']
        author_key = result['author_key']
        lora_msg_id = result['lora_msg_id']
        
        if reply_lora_msg_id is not None and reply_lora_msg_id != '':
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Cannot pin reply notes'
            }), 403
        
        if is_temp_parent_note == 1:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Cannot pin temporary parent notes'
            }), 403
        
        if deleted == 1:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Cannot pin archived notes'
            }), 403
        
        timestamp = int(time.time() * 1000)
        
        cursor.execute('''
            UPDATE notes 
            SET is_pined_note = 0, updated_at = ?
            WHERE board_id = ? AND is_pined_note = 1
        ''', (timestamp, board_id))
        
        cursor.execute('''
            UPDATE notes 
            SET is_pined_note = 1, updated_at = ?
            WHERE note_id = ? AND board_id = ?
        ''', (timestamp, note_id, board_id))
        
        conn.commit()
        conn.close()
        
        if interface and lora_connected:
            try:
                pin_cmd = f"/pin [{lora_msg_id}]{author_key}"
                interface.sendText(pin_cmd, channelIndex=get_channel_index(interface, board_id))
                print(f"已發送置頂命令: {pin_cmd}")
            except Exception as e:
                print(f"發送置頂命令失敗: {e}")
        
        socketio.emit('refresh_notes', {'board_id': board_id})
        
        return jsonify({
            'success': True,
            'note_id': note_id,
            'board_id': board_id
        }), 200
        
    except Exception as e:
        print(f"置頂 note 失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/boards/<board_id>/notes/<note_id>', methods=['DELETE'])
def delete_board_note(board_id, note_id):
    """刪除 note (僅限 author 本人且 status 為 LAN only)"""
    try:
        data = request.get_json() or {}
        author_key = data.get('author_key', 'user-unknown')
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT status, author_key FROM notes 
            WHERE note_id = ? AND board_id = ? AND deleted = 0
        ''', (note_id, board_id))
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Note not found'
            }), 404
        
        status, db_author_key = result
        
        if status != 'LAN only':
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Only LAN only notes can be deleted'
            }), 403
        
        if db_author_key != author_key:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Not authorized to delete this note'
            }), 403
        
        timestamp = int(time.time() * 1000)
        
        cursor.execute('''
            UPDATE notes 
            SET deleted = 1, updated_at = ?
            WHERE note_id = ? AND board_id = ?
        ''', (timestamp, note_id, board_id))
        
        conn.commit()
        conn.close()
        
        socketio.emit('refresh_notes', {'board_id': board_id})
        
        return jsonify({
            'success': True,
            'note_id': note_id,
            'board_id': board_id
        }), 200
        
    except Exception as e:
        print(f"刪除 note 失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/boards/<board_id>/notes/<note_id>/resend', methods=['POST'])
def resend_board_note(board_id, note_id):
    """重新發送 note (僅限 status 為 LoRa sent 的 note)"""
    global interface, lora_connected, pending_ack
    try:
        data = request.get_json() or {}
        author_key = data.get('author_key', 'user-unknown')
        is_admin = data.get('is_admin', False)
        
        # 驗證管理者身份
        if is_admin:
            if UID_SOURCE == "mac":
                client_ip = request.remote_addr
                mac_address = mac_from_ip(client_ip)
                user_uuid = mac_address if mac_address else get_or_create_user_uuid()
            else:
                user_uuid = get_or_create_user_uuid()
            
            if user_uuid not in admin_users:
                return jsonify({
                    'success': False,
                    'error': 'Not authorized as admin'
                }), 403
        
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT note_id, status, author_key, body, bg_color, lora_msg_id, reply_lora_msg_id, resent_count, is_pined_note
            FROM notes 
            WHERE note_id = ? AND board_id = ? AND deleted = 0
        ''', (note_id, board_id))
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Note not found'
            }), 404
        
        status = result['status']
        db_author_key = result['author_key']
        body = result['body']
        bg_color = result['bg_color']
        lora_msg_id = result['lora_msg_id']
        reply_lora_msg_id = result['reply_lora_msg_id']
        resent_count = result['resent_count']
        is_pined_note = result['is_pined_note']
        
        if status != 'LoRa sent':
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Only LoRa sent notes can be resent'
            }), 403
        
        # 如果不是管理者，則檢查是否為作者本人
        if not is_admin and db_author_key != author_key:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Not authorized to resend this note'
            }), 403
        
        if not lora_msg_id:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Note has no lora_msg_id'
            }), 400
        
        if not interface or not lora_connected:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'LoRa not connected'
            }), 503
        
        # 更新 resent_count
        timestamp = int(time.time() * 1000)
        cursor.execute('''
            UPDATE notes 
            SET resent_count = resent_count + 1, updated_at = ?
            WHERE note_id = ?
        ''', (timestamp, note_id))
        conn.commit()
        conn.close()
        
        # 根據是否為回覆決定使用 /msg 或 /reply 指令
        try:
            channel_index = get_channel_index(interface, BOARD_MESSAGE_CHANEL_NAME)
            
            if reply_lora_msg_id:
                # 是回覆，使用 /reply 指令
                msg = f"/reply <{lora_msg_id}>[{reply_lora_msg_id}]{body}"
                print(f"[重新發送] 使用 /reply 指令: {msg}")
            else:
                # 不是回覆，使用 /msg 指令
                msg = f"/msg [{lora_msg_id}]{body}"
                print(f"[重新發送] 使用 /msg 指令: {msg}")
            
            interface.sendText(msg, channelIndex=channel_index)
            print(f"  -> 已發送重新發送命令 (note_id={note_id}, resent_count={resent_count + 1})")
            
            # 延遲 5 秒後發送 author、color 和 pin 命令
            def send_follow_up_commands():
                try:
                    # 發送 author 命令
                    author_cmd = f"/author [{lora_msg_id}]{db_author_key}"
                    interface.sendText(author_cmd, channelIndex=channel_index)
                    print(f"  -> [延遲 5 秒後] 已發送 author 命令: {author_cmd}")
                    
                    # 發送 color 命令
                    color_index = get_color_index_from_palette(bg_color)
                    color_cmd = f"/color [{lora_msg_id}]{db_author_key}, {color_index}"
                    interface.sendText(color_cmd, channelIndex=channel_index)
                    print(f"  -> [延遲 5 秒後] 已發送 color 命令: {color_cmd}")
                    
                    # 如果該 note 有 is_pined_note = true，也發送 /pin 命令
                    if is_pined_note == 1:
                        pin_cmd = f"/pin [{lora_msg_id}]{db_author_key}"
                        interface.sendText(pin_cmd, channelIndex=channel_index)
                        print(f"  -> [延遲 5 秒後] 已發送 pin 命令: {pin_cmd}")
                except Exception as e:
                    print(f"  -> [延遲 5 秒後] 發送後續命令失敗: {e}")
            
            eventlet.spawn_after(5, send_follow_up_commands)
            print(f"  -> 已排程在 5 秒後發送 author、color 和 pin 命令")
            
            socketio.emit('refresh_notes', {'board_id': board_id})
            
            return jsonify({
                'success': True,
                'note_id': note_id,
                'board_id': board_id,
                'resent_count': resent_count + 1
            }), 200
            
        except Exception as e:
            print(f"[重新發送] 發送失敗: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'error': f'Failed to send: {str(e)}'
            }), 500
        
    except Exception as e:
        print(f"重新發送 note 失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/boards/<board_id>/notes/<note_id>/acks', methods=['GET'])
def get_note_acks(board_id, note_id):
    """取得指定 note 的 ACK 記錄"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT ack_id, lora_node_id, created_at, updated_at
            FROM ack_records
            WHERE note_id = ?
            ORDER BY created_at DESC
        ''', (note_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        acks = []
        for row in rows:
            lora_node_id = row['lora_node_id']
            display_id = lora_node_id
            if lora_node_id.startswith('lora-'):
                raw_id = lora_node_id.replace('lora-', '')
                display_id = f"LoRa-{raw_id[-4:]}" if len(raw_id) > 4 else raw_id
            
            acks.append({
                'ackId': row['ack_id'],
                'loraNodeId': lora_node_id,
                'displayId': display_id,
                'createdAt': row['created_at'],
                'updatedAt': row['updated_at']
            })
        
        return jsonify({
            'success': True,
            'note_id': note_id,
            'acks': acks,
            'count': len(acks)
        }), 200
        
    except Exception as e:
        print(f"取得 ACK 記錄失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/user/<user_id>/last-location', methods=['GET'])
def get_user_last_location(user_id):
    """取得使用者最後的地圖位置和縮放等級（從記憶體中）"""
    try:
        location = user_last_locations.get(user_id)
        if location:
            return jsonify({
                'success': True,
                'location': location
            }), 200
        else:
            return jsonify({
                'success': True,
                'location': None
            }), 200
    except Exception as e:
        print(f"取得使用者最後位置失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/user/<user_id>/last-location', methods=['POST'])
def set_user_last_location(user_id):
    """儲存使用者最後的地圖位置和縮放等級（到記憶體中）"""
    try:
        data = request.get_json()
        lat = data.get('lat')
        lng = data.get('lng')
        zoom = data.get('zoom')
        
        if lat is None or lng is None or zoom is None:
            return jsonify({
                'success': False,
                'error': 'Missing required fields: lat, lng, zoom'
            }), 400
        
        user_last_locations[user_id] = {
            'lat': lat,
            'lng': lng,
            'zoom': zoom
        }
        
        return jsonify({
            'success': True,
            'location': user_last_locations[user_id]
        }), 200
        
    except Exception as e:
        print(f"儲存使用者最後位置失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/available-tilesets')
def get_available_tilesets():
    """列出所有可用的 mbtiles 檔案並分析疊加策略"""
    try:
        maps_folder = NOTEBOARD_MBTILES_FOLDER
        
        # 檢查資料夾是否存在
        if not maps_folder or not os.path.exists(maps_folder):
            return jsonify({
                'success': True,
                'map_enabled': False,
                'tilesets': [],
                'layer_mode': 'none',
                'message': 'Maps folder not configured or not found'
            })
        
        tilesets = []
        mbtiles_files = glob.glob(os.path.join(maps_folder, '*.mbtiles'))
        
        if not mbtiles_files:
            return jsonify({
                'success': True,
                'map_enabled': False,
                'tilesets': [],
                'layer_mode': 'none',
                'message': 'No mbtiles files found'
            })
        
        # 讀取每個 mbtiles 檔案的 metadata
        for mbtiles_path in sorted(mbtiles_files):
            filename = os.path.basename(mbtiles_path)
            tileset_name = filename[:-8]  # 移除 .mbtiles 副檔名
            
            try:
                conn = sqlite3.connect(mbtiles_path)
                cursor = conn.cursor()
                cursor.execute('SELECT name, value FROM metadata')
                metadata = dict(cursor.fetchall())
                conn.close()
                
                # 解析 bounds
                bounds_str = metadata.get('bounds', '-180,-85,180,85')
                bounds = [float(b) for b in bounds_str.split(',')]
                
                # 取得 zoom 範圍
                minzoom = int(metadata.get('minzoom', 0))
                maxzoom = int(metadata.get('maxzoom', 14))
                
                # 判斷是 raster 還是 vector
                tile_format = metadata.get('format', 'png')
                tile_type = metadata.get('type', 'baselayer')
                # pbf 是 vector tiles 格式，其他圖片格式才是 raster
                is_raster = tile_format in ['png', 'jpg', 'jpeg', 'webp'] and tile_format != 'pbf'
                
                tileset_info = {
                    'name': tileset_name,
                    'display_name': metadata.get('name', tileset_name),
                    'description': metadata.get('description', ''),
                    'bounds': bounds,
                    'minzoom': minzoom,
                    'maxzoom': maxzoom,
                    'format': tile_format,
                    'type': tile_type,
                    'is_raster': is_raster,
                    'attribution': metadata.get('attribution', '')
                }
                
                # Debug 輸出
                #print(f"[DEBUG] 載入 tileset: {tileset_name}")
                #print(f"  - display_name: {tileset_info['display_name']}")
                #print(f"  - description: {tileset_info['description']}")
                #print(f"  - bounds: {tileset_info['bounds']}")
                #print(f"  - minzoom: {tileset_info['minzoom']}")
                #print(f"  - maxzoom: {tileset_info['maxzoom']}")
                #print(f"  - format: {tileset_info['format']}")
                #print(f"  - type: {tileset_info['type']}")
                #print(f"  - is_raster: {tileset_info['is_raster']}")
                #print(f"  - attribution: {tileset_info['attribution']}")
                
                tilesets.append(tileset_info)
            except Exception as e:
                print(f"讀取 {filename} metadata 失敗: {e}")
                # 即使讀取失敗，也加入基本資訊
                tilesets.append({
                    'name': tileset_name,
                    'display_name': tileset_name,
                    'description': '',
                    'bounds': [-180, -85, 180, 85],
                    'minzoom': 0,
                    'maxzoom': 14,
                    'format': 'png',
                    'type': 'baselayer',
                    'is_raster': True,
                    'attribution': ''
                })
        
        # 分析疊加策略
        layer_mode = NOTEBOARD_MBTILES_LAYER_MODE
        detected_mode = 'single'  # 預設為單一模式
        
        if len(tilesets) == 1:
            # 只有一個 tileset，使用 single 模式
            detected_mode = 'single'
        elif len(tilesets) > 1 and layer_mode == 'auto':
            # 自動判斷：檢查 zoom 範圍是否重疊
            zoom_ranges = [(ts['minzoom'], ts['maxzoom']) for ts in tilesets]
            
            # 檢查是否有明顯的縮放層級分層（zoom 範圍不重疊或僅輕微重疊）
            has_zoom_separation = False
            for i in range(len(zoom_ranges) - 1):
                for j in range(i + 1, len(zoom_ranges)):
                    min1, max1 = zoom_ranges[i]
                    min2, max2 = zoom_ranges[j]
                    
                    # 如果兩個範圍完全不重疊，或重疊少於 2 個層級
                    overlap = min(max1, max2) - max(min1, min2)
                    if overlap < 2:
                        has_zoom_separation = True
                        break
                
                if has_zoom_separation:
                    break
            
            detected_mode = 'zoom-level' if has_zoom_separation else 'overlay'
        elif layer_mode in ['overlay', 'zoom-level']:
            detected_mode = layer_mode
        
        return jsonify({
            'success': True,
            'map_enabled': True,
            'tilesets': tilesets,
            'layer_mode': detected_mode,
            'configured_mode': layer_mode
        })
        
    except Exception as e:
        print(f"取得可用 tilesets 失敗: {e}")
        return jsonify({
            'success': False,
            'map_enabled': False,
            'error': str(e)
        }), 500

@app.route('/tiles/<tileset>/<int:z>/<int:x>/<int:y>')
def get_tile(tileset, z, x, y):
    """提供 MBTiles 的 tile 資料"""
    try:
        mbtiles_path = os.path.join(os.path.dirname(__file__), 'maps', f'{tileset}.mbtiles')
        
        if not os.path.exists(mbtiles_path):
            return jsonify({
                'success': False,
                'error': f'Tileset {tileset} not found'
            }), 404
        
        conn = sqlite3.connect(mbtiles_path)
        cursor = conn.cursor()
        
        # MBTiles 使用 TMS 座標系統，需要轉換 y 座標
        tms_y = (2 ** z) - 1 - y
        
        cursor.execute('''
            SELECT tile_data FROM tiles 
            WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?
        ''', (z, x, tms_y))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            tile_data = row[0]
            response = make_response(tile_data)
            
            # 檢查 tile 格式
            if tile_data[:8] == b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A':
                response.headers['Content-Type'] = 'image/png'
            elif tile_data[:2] == b'\xFF\xD8':
                response.headers['Content-Type'] = 'image/jpeg'
            elif tile_data[:2] == b'\x1f\x8b':
                response.headers['Content-Type'] = 'application/x-protobuf'
                response.headers['Content-Encoding'] = 'gzip'
            else:
                response.headers['Content-Type'] = 'application/octet-stream'
            
            response.headers['Cache-Control'] = 'public, max-age=86400'
            return response
        else:
            return '', 204
            
    except Exception as e:
        print(f"取得 tile 失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/tiles/style.json')
def get_multi_style():
    """提供支援多個 mbtiles 疊加的 MapLibre style.json"""
    try:
        maps_folder = NOTEBOARD_MBTILES_FOLDER
        
        # 檢查資料夾是否存在
        if not maps_folder or not os.path.exists(maps_folder):
            return jsonify({
                'success': False,
                'error': 'Maps folder not configured or not found'
            }), 404
        
        mbtiles_files = sorted(glob.glob(os.path.join(maps_folder, '*.mbtiles')))
        
        if not mbtiles_files:
            return jsonify({
                'success': False,
                'error': 'No mbtiles files found'
            }), 404
        
        # 讀取所有 mbtiles 的 metadata
        tilesets_info = []
        for mbtiles_path in mbtiles_files:
            filename = os.path.basename(mbtiles_path)
            tileset_name = filename[:-8]
            
            try:
                conn = sqlite3.connect(mbtiles_path)
                cursor = conn.cursor()
                cursor.execute('SELECT name, value FROM metadata')
                metadata = dict(cursor.fetchall())
                conn.close()
                
                bounds_str = metadata.get('bounds', '-180,-85,180,85')
                bounds = [float(b) for b in bounds_str.split(',')]
                minzoom = int(metadata.get('minzoom', 0))
                maxzoom = int(metadata.get('maxzoom', 14))
                tile_format = metadata.get('format', 'png')
                tile_type = metadata.get('type', 'baselayer')
                # pbf 是 vector tiles 格式，其他圖片格式才是 raster
                is_raster = tile_format in ['png', 'jpg', 'jpeg', 'webp'] and tile_format != 'pbf'
                
                tilesets_info.append({
                    'name': tileset_name,
                    'display_name': metadata.get('name', tileset_name),
                    'bounds': bounds,
                    'minzoom': minzoom,
                    'maxzoom': maxzoom,
                    'is_raster': is_raster,
                    'format': tile_format,
                    'type': tile_type
                })
            except Exception as e:
                print(f"讀取 {filename} metadata 失敗: {e}")
                continue
        
        if not tilesets_info:
            return jsonify({
                'success': False,
                'error': 'Failed to read any mbtiles metadata'
            }), 500
        
        # 判斷疊加模式
        layer_mode = NOTEBOARD_MBTILES_LAYER_MODE
        detected_mode = 'overlay'
        
        if len(tilesets_info) > 1 and layer_mode == 'auto':
            zoom_ranges = [(ts['minzoom'], ts['maxzoom']) for ts in tilesets_info]
            has_zoom_separation = False
            
            for i in range(len(zoom_ranges) - 1):
                for j in range(i + 1, len(zoom_ranges)):
                    min1, max1 = zoom_ranges[i]
                    min2, max2 = zoom_ranges[j]
                    overlap = min(max1, max2) - max(min1, min2)
                    if overlap < 2:
                        has_zoom_separation = True
                        break
                if has_zoom_separation:
                    break
            
            detected_mode = 'zoom-level' if has_zoom_separation else 'overlay'
        elif layer_mode in ['overlay', 'zoom-level']:
            detected_mode = layer_mode
        
        # 建立 MapLibre style
        host = request.host
        style = {
            "version": 8,
            "name": "Multi-Tileset Map",
            "sources": {},
            "layers": []
        }
        
        # 計算整體 bounds（取所有 tileset 的聯集）
        all_bounds = [ts['bounds'] for ts in tilesets_info]
        overall_bounds = [
            min(b[0] for b in all_bounds),  # west
            min(b[1] for b in all_bounds),  # south
            max(b[2] for b in all_bounds),  # east
            max(b[3] for b in all_bounds)   # north
        ]
        
        # 根據模式建立 sources 和 layers
        if detected_mode == 'zoom-level':
            # 縮放層級模式：每個 tileset 在其 zoom 範圍內顯示
            for idx, ts in enumerate(tilesets_info):
                source_id = ts['name']
                style['sources'][source_id] = {
                    "type": "raster" if ts['is_raster'] else "vector",
                    "tiles": [f"http://{host}/tiles/{ts['name']}/{{z}}/{{x}}/{{y}}"],
                    "tileSize": 256 if ts['is_raster'] else None,
                    "minzoom": ts['minzoom'],
                    "maxzoom": ts['maxzoom'],
                    "bounds": ts['bounds']
                }
                
                if ts['is_raster']:
                    style['layers'].append({
                        "id": f"{source_id}-layer",
                        "type": "raster",
                        "source": source_id,
                        "minzoom": ts['minzoom'],
                        "maxzoom": ts['maxzoom'] + 1
                    })
                else:
                    # Vector tiles 在縮放層級模式下，需要讀取實際的 layers
                    # 暫時使用簡化處理，建議使用單一 vector tileset 或使用 /tiles/<tileset>/style.json
                    print(f"[WARNING] Vector tiles '{source_id}' in zoom-level mode may need custom styling")
        else:
            # 疊加模式：所有 tileset 同時顯示（底層到上層）
            for idx, ts in enumerate(tilesets_info):
                source_id = ts['name']
                style['sources'][source_id] = {
                    "type": "raster" if ts['is_raster'] else "vector",
                    "tiles": [f"http://{host}/tiles/{ts['name']}/{{z}}/{{x}}/{{y}}"],
                    "tileSize": 256 if ts['is_raster'] else None,
                    "minzoom": ts['minzoom'],
                    "maxzoom": ts['maxzoom'],
                    "bounds": ts['bounds']
                }
                
                if ts['is_raster']:
                    # 第一層不透明，後續層可以設定透明度
                    opacity = 1.0 if idx == 0 else 0.7
                    style['layers'].append({
                        "id": f"{source_id}-layer",
                        "type": "raster",
                        "source": source_id,
                        "paint": {
                            "raster-opacity": opacity
                        }
                    })
                else:
                    # Vector tiles 在疊加模式下需要更複雜的處理
                    print(f"[WARNING] Vector tiles '{source_id}' in overlay mode may need custom styling")
        
        response = make_response(jsonify(style))
        response.headers['Content-Type'] = 'application/json'
        return response
        
    except Exception as e:
        print(f"取得 multi style.json 失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/tiles/<tileset>/style.json')
def get_style(tileset):
    """提供 MapLibre style.json"""
    try:
        mbtiles_path = os.path.join(os.path.dirname(__file__), 'maps', f'{tileset}.mbtiles')
        
        if not os.path.exists(mbtiles_path):
            return jsonify({
                'success': False,
                'error': f'Tileset {tileset} not found'
            }), 404
        
        conn = sqlite3.connect(mbtiles_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 讀取 metadata
        cursor.execute('SELECT name, value FROM metadata')
        metadata = {row['name']: row['value'] for row in cursor.fetchall()}
        
        # 取得 bounds 和 zoom 範圍
        bounds = metadata.get('bounds', '-180,-85,180,85').split(',')
        bounds = [float(b) for b in bounds]
        
        minzoom = int(metadata.get('minzoom', 0))
        maxzoom = int(metadata.get('maxzoom', 14))
        
        # 檢查是否為 raster tiles
        tile_format = metadata.get('format', 'png')
        tile_type = metadata.get('type', 'baselayer')
        # pbf 是 vector tiles 格式，其他圖片格式才是 raster
        is_raster = tile_format in ['png', 'jpg', 'jpeg', 'webp'] and tile_format != 'pbf'
        
        conn.close()
        
        # 建立 MapLibre style
        if is_raster:
            # Raster tiles style
            # MapLibre 的 maxZoom 需要比 tile 的實際 maxzoom 多 1，才能正確顯示最大縮放層級
            style = {
                "version": 8,
                "name": metadata.get('name', tileset),
                "sources": {
                    tileset: {
                        "type": "raster",
                        "tiles": [f"http://{{host}}/tiles/{tileset}/{{z}}/{{x}}/{{y}}"],
                        "tileSize": 256,
                        "minzoom": minzoom,
                        "maxzoom": maxzoom,
                        "bounds": bounds
                    }
                },
                "layers": [
                    {
                        "id": "raster-tiles",
                        "type": "raster",
                        "source": tileset,
                        "minzoom": minzoom,
                        "maxzoom": maxzoom
                    }
                ]
            }
        else:
            # Vector tiles style
            # 嘗試從 metadata 讀取 vector_layers 資訊
            import json as json_module
            vector_layers = []
            
            try:
                if 'json' in metadata:
                    tile_json = json_module.loads(metadata['json'])
                    vector_layers = tile_json.get('vector_layers', [])
            except Exception as e:
                print(f"無法解析 vector_layers: {e}")
            
            # 建立基本 style
            # 使用線上字體服務
            host = request.host
            style = {
                "version": 8,
                "name": metadata.get('name', tileset),
                "glyphs": "https://cdn.protomaps.com/fonts/pbf/{fontstack}/{range}.pbf",
                "sources": {
                    tileset: {
                        "type": "vector",
                        "tiles": [f"http://{host}/tiles/{tileset}/{{z}}/{{x}}/{{y}}"],
                        "minzoom": minzoom,
                        "maxzoom": maxzoom,
                        "bounds": bounds
                    }
                },
                "layers": [
                    {
                        "id": "background",
                        "type": "background",
                        "paint": {
                            "background-color": "#f8f8f8"
                        }
                    }
                ]
            }
            
            # 根據實際的 vector_layers 生成 layer 定義
            if vector_layers:
                print(f"[DEBUG] Vector layers found: {[layer.get('id') for layer in vector_layers]}")
                
                # OpenMapTiles 標準 layers 的完整 style 定義
                # 按照正確的渲染順序（從底層到上層）
                
                # 1. Water (水域) - 底層
                if any(l.get('id') == 'water' for l in vector_layers):
                    style['layers'].append({
                        "id": "water",
                        "type": "fill",
                        "source": tileset,
                        "source-layer": "water",
                        "paint": {
                            "fill-color": "#aad3df"
                        }
                    })
                
                # 2. Waterway (河流)
                if any(l.get('id') == 'waterway' for l in vector_layers):
                    style['layers'].append({
                        "id": "waterway",
                        "type": "line",
                        "source": tileset,
                        "source-layer": "waterway",
                        "paint": {
                            "line-color": "#aad3df",
                            "line-width": 1
                        }
                    })
                
                # 3. Landcover (土地覆蓋 - 森林、草地等)
                if any(l.get('id') == 'landcover' for l in vector_layers):
                    style['layers'].append({
                        "id": "landcover",
                        "type": "fill",
                        "source": tileset,
                        "source-layer": "landcover",
                        "paint": {
                            "fill-color": "#d8e8c8",
                            "fill-opacity": 0.5
                        }
                    })
                
                # 4. Landuse (土地使用)
                if any(l.get('id') == 'landuse' for l in vector_layers):
                    style['layers'].append({
                        "id": "landuse",
                        "type": "fill",
                        "source": tileset,
                        "source-layer": "landuse",
                        "paint": {
                            "fill-color": "#e0e0e0",
                            "fill-opacity": 0.3
                        }
                    })
                
                # 5. Park (公園)
                if any(l.get('id') == 'park' for l in vector_layers):
                    style['layers'].append({
                        "id": "park",
                        "type": "fill",
                        "source": tileset,
                        "source-layer": "park",
                        "paint": {
                            "fill-color": "#c8e6c9",
                            "fill-opacity": 0.6
                        }
                    })
                
                # 6. Boundary (邊界)
                if any(l.get('id') == 'boundary' for l in vector_layers):
                    style['layers'].append({
                        "id": "boundary",
                        "type": "line",
                        "source": tileset,
                        "source-layer": "boundary",
                        "paint": {
                            "line-color": "#9e9cab",
                            "line-width": 1,
                            "line-dasharray": [3, 3]
                        }
                    })
                
                # 7. Aeroway (機場跑道)
                if any(l.get('id') == 'aeroway' for l in vector_layers):
                    style['layers'].append({
                        "id": "aeroway",
                        "type": "fill",
                        "source": tileset,
                        "source-layer": "aeroway",
                        "paint": {
                            "fill-color": "#e9e9ed"
                        }
                    })
                
                # 8. Transportation (道路) - 多層渲染
                if any(l.get('id') == 'transportation' for l in vector_layers):
                    # 道路外框（較粗）
                    style['layers'].append({
                        "id": "transportation-case",
                        "type": "line",
                        "source": tileset,
                        "source-layer": "transportation",
                        "paint": {
                            "line-color": "#e0e0e0",
                            "line-width": {
                                "stops": [[10, 2], [14, 6], [18, 12]]
                            }
                        }
                    })
                    # 道路內線（較細）
                    style['layers'].append({
                        "id": "transportation",
                        "type": "line",
                        "source": tileset,
                        "source-layer": "transportation",
                        "paint": {
                            "line-color": "#ffffff",
                            "line-width": {
                                "stops": [[10, 1], [14, 4], [18, 10]]
                            }
                        }
                    })
                
                # 9. Building (建築物)
                if any(l.get('id') == 'building' for l in vector_layers):
                    style['layers'].append({
                        "id": "building",
                        "type": "fill",
                        "source": tileset,
                        "source-layer": "building",
                        "minzoom": 13,
                        "paint": {
                            "fill-color": "#d6d6d6",
                            "fill-opacity": 0.7
                        }
                    })
                
                # 10. Water name (水域名稱)
                if any(l.get('id') == 'water_name' for l in vector_layers):
                    style['layers'].append({
                        "id": "water_name",
                        "type": "symbol",
                        "source": tileset,
                        "source-layer": "water_name",
                        "layout": {
                            "text-field": ["get", "name"],
                            "text-font": ["Noto Sans Regular"],
                            "text-size": 12
                        },
                        "paint": {
                            "text-color": "#5a7a8f",
                            "text-halo-color": "#ffffff",
                            "text-halo-width": 1
                        }
                    })
                
                # 11. Transportation name (道路名稱)
                if any(l.get('id') == 'transportation_name' for l in vector_layers):
                    style['layers'].append({
                        "id": "transportation_name",
                        "type": "symbol",
                        "source": tileset,
                        "source-layer": "transportation_name",
                        "layout": {
                            "text-field": ["get", "name"],
                            "text-font": ["Noto Sans Regular"],
                            "text-size": 10,
                            "symbol-placement": "line",
                            "text-rotation-alignment": "map"
                        },
                        "paint": {
                            "text-color": "#666666",
                            "text-halo-color": "#ffffff",
                            "text-halo-width": 1
                        }
                    })
                
                # 12. Place (地名)
                if any(l.get('id') == 'place' for l in vector_layers):
                    style['layers'].append({
                        "id": "place",
                        "type": "symbol",
                        "source": tileset,
                        "source-layer": "place",
                        "layout": {
                            "text-field": ["get", "name"],
                            "text-font": ["Noto Sans Bold"],
                            "text-size": {
                                "stops": [[6, 10], [10, 14], [14, 18]]
                            }
                        },
                        "paint": {
                            "text-color": "#333333",
                            "text-halo-color": "#ffffff",
                            "text-halo-width": 1.5
                        }
                    })
                
                # 13. Housenumber (門牌號碼)
                if any(l.get('id') == 'housenumber' for l in vector_layers):
                    style['layers'].append({
                        "id": "housenumber",
                        "type": "symbol",
                        "source": tileset,
                        "source-layer": "housenumber",
                        "minzoom": 17,
                        "layout": {
                            "text-field": ["get", "housenumber"],
                            "text-font": ["Noto Sans Regular"],
                            "text-size": 9
                        },
                        "paint": {
                            "text-color": "#666666"
                        }
                    })
                
                # 14. POI (興趣點)
                if any(l.get('id') == 'poi' for l in vector_layers):
                    style['layers'].append({
                        "id": "poi",
                        "type": "symbol",
                        "source": tileset,
                        "source-layer": "poi",
                        "minzoom": 14,
                        "layout": {
                            "text-field": ["get", "name"],
                            "text-font": ["Noto Sans Regular"],
                            "text-size": 10,
                            "text-anchor": "top",
                            "text-offset": [0, 0.5]
                        },
                        "paint": {
                            "text-color": "#666666",
                            "text-halo-color": "#ffffff",
                            "text-halo-width": 1
                        }
                    })
                
                # 15. Aerodrome label (機場標籤)
                if any(l.get('id') == 'aerodrome_label' for l in vector_layers):
                    style['layers'].append({
                        "id": "aerodrome_label",
                        "type": "symbol",
                        "source": tileset,
                        "source-layer": "aerodrome_label",
                        "layout": {
                            "text-field": ["get", "name"],
                            "text-font": ["Noto Sans Regular"],
                            "text-size": 11
                        },
                        "paint": {
                            "text-color": "#666666",
                            "text-halo-color": "#ffffff",
                            "text-halo-width": 1
                        }
                    })
                
                # 16. Mountain peak (山峰)
                if any(l.get('id') == 'mountain_peak' for l in vector_layers):
                    style['layers'].append({
                        "id": "mountain_peak",
                        "type": "symbol",
                        "source": tileset,
                        "source-layer": "mountain_peak",
                        "layout": {
                            "text-field": ["get", "name"],
                            "text-font": ["Noto Sans Italic"],
                            "text-size": 10
                        },
                        "paint": {
                            "text-color": "#7a5c3d",
                            "text-halo-color": "#ffffff",
                            "text-halo-width": 1
                        }
                    })
            else:
                # 如果沒有 vector_layers 資訊，使用預設的 layer 定義
                print(f"[WARNING] No vector_layers found in metadata, using default layers")
                style['layers'].extend([
                    {
                        "id": "water",
                        "type": "fill",
                        "source": tileset,
                        "source-layer": "water",
                        "paint": {
                            "fill-color": "#a0c8f0"
                        }
                    },
                    {
                        "id": "landuse",
                        "type": "fill",
                        "source": tileset,
                        "source-layer": "landuse",
                        "paint": {
                            "fill-color": "#e8e8e8"
                        }
                    },
                    {
                        "id": "roads",
                        "type": "line",
                        "source": tileset,
                        "source-layer": "transportation",
                        "paint": {
                            "line-color": "#ffffff",
                            "line-width": 2
                        }
                    },
                    {
                        "id": "buildings",
                        "type": "fill",
                        "source": tileset,
                        "source-layer": "building",
                        "paint": {
                            "fill-color": "#d0d0d0",
                            "fill-opacity": 0.7
                        }
                    }
                ])
        
        # 替換 host placeholder
        host = request.host
        style_json = jsonify(style).get_data(as_text=True)
        style_json = style_json.replace('{host}', host)
        
        response = make_response(style_json)
        response.headers['Content-Type'] = 'application/json'
        return response
        
    except Exception as e:
        print(f"取得 style.json 失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/tiles/<tileset>/tilejson.json')
def get_tilejson(tileset):
    """提供 TileJSON metadata"""
    try:
        mbtiles_path = os.path.join(os.path.dirname(__file__), 'maps', f'{tileset}.mbtiles')
        
        if not os.path.exists(mbtiles_path):
            return jsonify({
                'success': False,
                'error': f'Tileset {tileset} not found'
            }), 404
        
        conn = sqlite3.connect(mbtiles_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 讀取 metadata
        cursor.execute('SELECT name, value FROM metadata')
        metadata = {row['name']: row['value'] for row in cursor.fetchall()}
        
        conn.close()
        
        # 取得 bounds 和 zoom 範圍
        bounds = metadata.get('bounds', '-180,-85,180,85').split(',')
        bounds = [float(b) for b in bounds]
        
        center_str = metadata.get('center', '0,0,0').split(',')
        center = [float(center_str[0]), float(center_str[1]), int(center_str[2])]
        
        minzoom = int(metadata.get('minzoom', 0))
        maxzoom = int(metadata.get('maxzoom', 14))
        
        # 建立 TileJSON
        tilejson = {
            "tilejson": "3.0.0",
            "name": metadata.get('name', tileset),
            "description": metadata.get('description', ''),
            "version": metadata.get('version', '1.0.0'),
            "attribution": metadata.get('attribution', ''),
            "scheme": "xyz",
            "tiles": [f"http://{request.host}/tiles/{tileset}/{{z}}/{{x}}/{{y}}"],
            "minzoom": minzoom,
            "maxzoom": maxzoom,
            "bounds": bounds,
            "center": center
        }
        
        return jsonify(tilejson), 200
        
    except Exception as e:
        print(f"取得 tilejson.json 失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/<path:path>')
def catch_all(path):
    return redirect(url_for('index'))

@app.route('/generate_204')
def gen_204():
    return redirect(url_for('index'))

@socketio.on('connect')
def handle_connect():
    emit('lora_status', {'online': lora_connected, 'channel_validated': channel_validated, 'error_message': None})

def run_noteboard_app():
    init_database()
    migrate_database()
    
    # 檢查地圖功能是否啟用
    map_enabled = False
    if NOTEBOARD_MBTILES_FOLDER and os.path.exists(NOTEBOARD_MBTILES_FOLDER):
        mbtiles_files = glob.glob(os.path.join(NOTEBOARD_MBTILES_FOLDER, '*.mbtiles'))
        map_enabled = len(mbtiles_files) > 0
    
    if not map_enabled:
        print("mbtiles 目錄未設定或無檔案，離線地圖功能停用")
    
    socketio.start_background_task(target=mesh_loop)
    socketio.start_background_task(target=send_scheduler_loop)
    print(f"MeshBridge NoteBoard 伺服器啟動中 (Port 80, Channel: {BOARD_MESSAGE_CHANEL_NAME})...")
    socketio.run(app, host='0.0.0.0', port=80, debug=False)
