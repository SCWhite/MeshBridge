import eventlet
eventlet.monkey_patch()

import time
import sys
import os
import glob
import sqlite3
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, jsonify, make_response, session
from flask_socketio import SocketIO, emit
from meshtastic.serial_interface import SerialInterface
from pubsub import pub
from config import BOARD_MESSAGE_CHANEL_NAME, SEND_INTERVAL_SECOND, MAX_NOTE_SHOW, MAX_ARCHIVED_NOTE_SHOW

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
pending_ack = {}
send_interval = max(SEND_INTERVAL_SECOND, 5)

DB_PATH = 'noteboard.db'
MAX_NOTES = 200

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
            reply_id TEXT,
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
            FOREIGN KEY (reply_id) REFERENCES notes(note_id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_board_id ON notes(board_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON notes(created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_deleted ON notes(deleted)')
    conn.commit()
    conn.close()
    print("資料庫初始化完成")

def get_time():
    return time.strftime("%H:%M", time.localtime())

def generate_note_id():
    """生成唯一的 note_id"""
    return str(uuid.uuid4())

def generate_user_uuid():
    """生成用戶 UUID (8字元)"""
    alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789'
    import random
    return ''.join(random.choice(alphabet) for _ in range(8))

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

def update_note_color(note_id, author_key, color_index, need_lora_update=False):
    """更新 note 的背景顏色，需驗證 author_key"""
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

def update_note_author(note_id, author_key):
    """更新 note 的 author_key"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = int(time.time() * 1000)
        
        cursor.execute('''
            UPDATE notes 
            SET author_key = ?, updated_at = ?, rev = rev + 1
            WHERE note_id = ?
        ''', (author_key, timestamp, note_id))
        
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
                SET deleted = 1, updated_at = ?, is_need_update_lora = 1
                WHERE note_id = ? AND author_key = ?
            ''', (timestamp, note_id, author_key))
        else:
            cursor.execute('''
                UPDATE notes 
                SET deleted = 1, updated_at = ?
                WHERE note_id = ? AND author_key = ?
            ''', (timestamp, note_id, author_key))
        
        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        return affected_rows > 0
    except Exception as e:
        print(f"封存 note 失敗: {e}")
        return False

def save_lora_note(note_id, board_id, body, bg_color='', author_key='', reply_id=None):
    """儲存 LoRa 接收的 note"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = int(time.time() * 1000)
        status = 'LoRa received'
        
        cursor.execute('''
            INSERT INTO notes (note_id, reply_id, board_id, body, bg_color, status, 
                             created_at, updated_at, author_key, rev, deleted, lora_msg_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?)
        ''', (note_id, reply_id, board_id, body, bg_color, status, timestamp, timestamp, author_key, note_id))
        
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
        return True
    except Exception as e:
        print(f"儲存 LoRa note 失敗: {e}")
        return False

def save_note_to_db(board_id, text, sender, user_id, time_str, source, lora_success, reply_id=None):
    """儲存 note 到資料庫"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = int(time.time() * 1000)
        note_id = generate_note_id()
        bg_color = generate_bg_color(user_id)
        status = 'sent' if lora_success else 'local'
        
        cursor.execute('''
            INSERT INTO notes (note_id, reply_id, board_id, body, bg_color, status, 
                             created_at, updated_at, author_key, rev, deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
        ''', (note_id, reply_id, board_id, text, bg_color, status, timestamp, timestamp, user_id))
        
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
        return True
    except Exception as e:
        print(f"儲存 note 到資料庫失敗: {e}")
        return False

def get_oldest_lan_only_note(board_id):
    """取得最舊的 LAN only 狀態的 note"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT note_id, body, bg_color, author_key, created_at
            FROM notes 
            WHERE board_id = ? AND status = 'LAN only' AND deleted = 0
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
                'created_at': row['created_at']
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
                SELECT note_id, reply_id, body, bg_color, status, 
                       created_at, updated_at, author_key, rev, deleted
                FROM notes 
                WHERE board_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (board_id, limit))
        else:
            cursor.execute('''
                SELECT note_id, reply_id, body, bg_color, status, 
                       created_at, updated_at, author_key, rev, deleted
                FROM notes 
                WHERE board_id = ? AND deleted = 0
                ORDER BY created_at DESC
                LIMIT ?
            ''', (board_id, limit))
        
        rows = cursor.fetchall()
        notes = []
        for row in rows:
            local_time = time.localtime(row['created_at'] / 1000)
            hour = local_time.tm_hour
            period = "上午" if hour < 12 else "下午"
            display_hour = hour if hour <= 12 else hour - 12
            if display_hour == 0:
                display_hour = 12
            created_time = time.strftime(f"%Y/%m/%d ({period}) {display_hour:02d}:%M", local_time)
            author_display = row['author_key']
            if author_display.startswith('lora-'):
                raw_id = author_display.replace('lora-', '')
                author_display = f"LoRa-{raw_id[-4:]}" if len(raw_id) > 4 else raw_id
            elif author_display.startswith('user-'):
                author_display = "WebUser"
            
            notes.append({
                'noteId': row['note_id'],
                'replyId': row['reply_id'],
                'text': row['body'],
                'bgColor': row['bg_color'],
                'status': row['status'],
                'time': created_time,
                'timestamp': row['created_at'],
                'userId': row['author_key'],
                'sender': author_display,
                'loraSuccess': row['status'] == 'sent',
                'source': 'lora' if row['author_key'].startswith('lora-') else 'local',
                'rev': row['rev'],
                'archived': row['deleted'] == 1
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

def onReceive(packet, interface):
    global pending_ack
    try:
        if 'decoded' in packet and packet['decoded'].get('portnum') == 'ROUTING_APP':
            request_id = packet['decoded'].get('requestId')
            if request_id and request_id in pending_ack:
                note_info = pending_ack[request_id]
                lora_msg_id = packet.get('id')
                print(f"[收到 ACK] request_id={request_id}, lora_msg_id={lora_msg_id}")
                
                if update_note_status(note_info['note_id'], 'LoRa sent'):
                    print(f"  -> 已更新 note {note_info['note_id']} 狀態為 'LoRa sent'")
                    
                    try:
                        if lora_msg_id:
                            update_note_lora_msg_id(note_info['note_id'], str(lora_msg_id))
                            print(f"  -> 已儲存 lora_msg_id: {lora_msg_id}")
                            
                            author_cmd = f"/author [{lora_msg_id}]{note_info['author_key']}"
                            interface.sendText(author_cmd, channelIndex=get_channel_index(interface, BOARD_MESSAGE_CHANEL_NAME))
                            print(f"  -> 已發送 author 命令: {author_cmd}")
                            
                            color_index = get_color_index_from_palette(note_info['bg_color'])
                            color_cmd = f"/color [{lora_msg_id}]{note_info['author_key']}, {color_index}"
                            interface.sendText(color_cmd, channelIndex=get_channel_index(interface, BOARD_MESSAGE_CHANEL_NAME))
                            print(f"  -> 已發送 color 命令: {color_cmd}")
                    except Exception as e:
                        print(f"  -> 發送後續命令失敗: {e}")
                    
                    socketio.emit('refresh_notes', {'board_id': BOARD_MESSAGE_CHANEL_NAME})
                
                del pending_ack[request_id]
        
        if 'decoded' in packet and packet['decoded']['portnum'] == 'TEXT_MESSAGE_APP':
            msg = packet['decoded']['text']
            raw_id = packet.get('fromId', 'Unknown')
            sender_display = f"LoRa-{raw_id[-4:]}" if raw_id and len(raw_id) > 4 else (raw_id or 'Unknown')
            lora_uuid = f"lora-{raw_id}"
            lora_msg_id = str(packet.get('id', 'N/A'))
            
            channel_index = packet.get('channel', 'N/A')
            channel_name = get_channel_name(interface, channel_index) if channel_index != 'N/A' else 'N/A'
            
            if channel_name != BOARD_MESSAGE_CHANEL_NAME:
                print(f"[略過] Channel '{channel_name}' 不符合目標 '{BOARD_MESSAGE_CHANEL_NAME}'")
                return

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
                print(f"[新訊息] note_id={lora_msg_id}, body={body}")
                if save_lora_note(
                    note_id=lora_msg_id,
                    board_id=BOARD_MESSAGE_CHANEL_NAME,
                    body=body,
                    bg_color='',
                    author_key=''
                ):
                    should_refresh = True
                    
            elif msg.startswith('/msg [') and ']' in msg:
                end_bracket = msg.index(']')
                note_id = msg[6:end_bracket]
                body = msg[end_bracket + 1:]
                print(f"[重發訊息] note_id={note_id}, body={body}")
                
                if not note_exists(note_id):
                    if save_lora_note(
                        note_id=note_id,
                        board_id=BOARD_MESSAGE_CHANEL_NAME,
                        body=body,
                        bg_color='',
                        author_key=''
                    ):
                        should_refresh = True
                else:
                    print(f"  -> note_id {note_id} 已存在，略過")
                    
            elif msg.startswith('/color [') and ']' in msg:
                end_bracket = msg.index(']')
                note_id = msg[8:end_bracket]
                params = msg[end_bracket + 1:].strip()
                
                if ',' in params:
                    parts = params.split(',', 1)
                    author_key = parts[0].strip()
                    color_id = parts[1].strip()
                    print(f"[設定顏色] note_id={note_id}, author_key={author_key}, color_id={color_id}")
                    
                    if update_note_color(note_id, author_key, color_id):
                        print(f"  -> 成功更新 note {note_id} 的顏色")
                        should_refresh = True
                    else:
                        print(f"  -> 更新失敗，note_id {note_id} 不存在或 author_key 不符")
                else:
                    print(f"  -> 格式錯誤，應為 /color [note_id]author_key,color_id")
                    
            elif msg.startswith('/author [') and ']' in msg:
                end_bracket = msg.index(']')
                note_id = msg[9:end_bracket]
                author_key = msg[end_bracket + 1:].strip()
                print(f"[更新作者] note_id={note_id}, author_key={author_key}")
                
                if update_note_author(note_id, author_key):
                    print(f"  -> 成功更新 note {note_id} 的 author_key 為 {author_key}")
                    should_refresh = True
                else:
                    print(f"  -> 更新失敗，note_id {note_id} 可能不存在")
                    
            elif msg.startswith('/archive [') and ']' in msg:
                end_bracket = msg.index(']')
                note_id = msg[10:end_bracket]
                author_key = msg[end_bracket + 1:].strip()
                print(f"[封存訊息] note_id={note_id}, author_key={author_key}")
                
                if archive_note(note_id, author_key):
                    print(f"  -> 成功封存 note {note_id}")
                    should_refresh = True
                else:
                    print(f"  -> 封存失敗，note_id {note_id} 不存在或 author_key 不符")
                    
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
    patterns = ["/dev/ttyACM*", "/dev/ttyUSB*"]
    found_ports = []
    for p in patterns:
        found_ports.extend(glob.glob(p))
    return found_ports[0] if found_ports else None

def send_scheduler_loop():
    """定期發送 LAN only notes 和處理需要更新的 notes 的排程器"""
    global interface, lora_connected, pending_ack
    print(f"啟動發送排程器 (間隔: {send_interval} 秒)...")
    
    while True:
        try:
            eventlet.sleep(send_interval)
            
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
                    print(f"[排程器] 發送更新命令失敗: {e}")
                    import traceback
                    traceback.print_exc()
                
                continue
            
            note = get_oldest_lan_only_note(BOARD_MESSAGE_CHANEL_NAME)
            if not note:
                continue
            
            print(f"[排程器] 準備發送 note_id={note['note_id']}")
            
            try:
                channel_index = get_channel_index(interface, BOARD_MESSAGE_CHANEL_NAME)
                msg = f"/msg [new]{note['body']}"
                
                result = interface.sendText(msg, channelIndex=channel_index, wantAck=True)
                
                if result:
                    request_id = result.id if hasattr(result, 'id') else None
                    if request_id:
                        pending_ack[request_id] = {
                            'note_id': note['note_id'],
                            'author_key': note['author_key'],
                            'bg_color': note['bg_color']
                        }
                        print(f"  -> 已發送訊息，等待 ACK (request_id={request_id})")
                    else:
                        print(f"  -> 已發送訊息，但無 request_id")
                else:
                    print(f"  -> 發送失敗")
                    
            except Exception as e:
                print(f"[排程器] 發送失敗: {e}")
                import traceback
                traceback.print_exc()
                
        except Exception as e:
            print(f"[排程器] 錯誤: {e}")
            import traceback
            traceback.print_exc()

def mesh_loop():
    global interface, current_dev_path, lora_connected
    print("啟動 Meshtastic 自動偵測與監聽 (NoteBoard 模式)...")
    
    while True:
        try:
            if interface is None:
                if lora_connected:
                    lora_connected = False
                    socketio.emit('lora_status', {'online': False})
                
                target_port = scan_for_meshtastic()
                if target_port:
                    print(f"發現裝置於: {target_port}，嘗試連線...")
                    interface = SerialInterface(devPath=target_port)
                    current_dev_path = target_port
                    pub.subscribe(onReceive, "meshtastic.receive")
                    
                    print(f">>> 成功連線至 {target_port} (Channel: {BOARD_MESSAGE_CHANEL_NAME}) <<<")
                    
                    lora_connected = True
                    socketio.emit('lora_status', {'online': True})
                else:
                    time.sleep(3)

            else:
                if current_dev_path and not os.path.exists(current_dev_path):
                    raise Exception(f"裝置路徑 {current_dev_path} 已消失")
                
                if not lora_connected:
                    lora_connected = True
                    socketio.emit('lora_status', {'online': True})

        except Exception as e:
            print(f"Meshtastic 連線異常: {e}")
            if interface:
                try: interface.close()
                except: pass
            
            interface = None
            current_dev_path = None
            
            if lora_connected:
                lora_connected = False
                socketio.emit('lora_status', {'online': False})
            
            print("正在重置狀態... (3秒後重試)")
            time.sleep(3)
            
        eventlet.sleep(2)

@app.route('/api/user/uuid', methods=['GET'])
def get_user_uuid():
    """取得或建立用戶 UUID (使用 session/cookie)"""
    user_uuid = get_or_create_user_uuid()
    return jsonify({
        'success': True,
        'uuid': user_uuid
    })

@app.route('/api/boards/<board_id>/notes', methods=['GET'])
def get_board_notes(board_id):
    """取得指定 board 的所有 notes"""
    is_include_deleted = request.args.get('is_include_deleted', 'false').lower() == 'true'
    notes = get_notes_from_db(board_id, include_deleted=is_include_deleted)
    return jsonify({
        'success': True,
        'board_id': board_id,
        'notes': notes,
        'count': len(notes)
    })

@app.route('/api/boards/<board_id>/notes', methods=['POST'])
def create_board_note(board_id):
    """建立新的 note (LAN only 模式)"""
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
        timestamp = int(time.time() * 1000)
        note_id = generate_note_id()
        bg_color = get_color_from_palette(color_index)
        status = 'LAN only'
        
        cursor.execute('''
            INSERT INTO notes (note_id, reply_id, board_id, body, bg_color, status, 
                             created_at, updated_at, author_key, rev, deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
        ''', (note_id, None, board_id, text, bg_color, status, timestamp, timestamp, author_key))
        
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
        
        socketio.emit('refresh_notes', {'board_id': board_id})
        
        return jsonify({
            'success': True,
            'note_id': note_id,
            'board_id': board_id
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
                'error': 'Only LAN only notes can be edited'
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
    """封存 note (僅限 author 本人且 status 非 LAN only)"""
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
        
        if status == 'LAN only':
            conn.close()
            return jsonify({
                'success': False,
                'error': 'LAN only notes cannot be archived via this endpoint'
            }), 403
        
        if db_author_key != author_key:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Not authorized to archive this note'
            }), 403
        
        conn.close()
        
        if archive_note(note_id, author_key, need_lora_update=True):
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
    """變更 note 顏色 (僅限 author 本人且 status 非 LAN only)"""
    try:
        data = request.get_json() or {}
        author_key = data.get('author_key', 'user-unknown')
        color_index = data.get('color_index', 0)
        
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
        
        if db_author_key != author_key:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Not authorized to change color of this note'
            }), 403
        
        conn.close()
        
        if update_note_color(note_id, author_key, color_index, need_lora_update=True):
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
    emit('lora_status', {'online': lora_connected})

@socketio.on('send_mesh')
def handle_msg(data):
    text = data.get('text', '')
    sender = data.get('sender', 'WebUser')
    user_id = data.get('userId', 'anon')
    
    if not text: return

    full_msg = f"[{sender}] {text}"
    print(f"[網頁發送] {full_msg}")

    is_sent_to_lora = False

    if interface and lora_connected:
        try:
            interface.sendText(full_msg)
            is_sent_to_lora = True
        except Exception as e:
            print(f"LoRa 發送失敗: {e}")
            is_sent_to_lora = False
    
    save_note_to_db(
        board_id=BOARD_MESSAGE_CHANEL_NAME,
        text=text,
        sender=sender,
        user_id=user_id,
        time_str=get_time(),
        source='local',
        lora_success=is_sent_to_lora
    )
    
    emit('refresh_notes', {'board_id': BOARD_MESSAGE_CHANEL_NAME}, broadcast=True)

def run_noteboard_app():
    init_database()
    socketio.start_background_task(target=mesh_loop)
    socketio.start_background_task(target=send_scheduler_loop)
    print(f"MeshBridge NoteBoard 伺服器啟動中 (Port 80, Channel: {BOARD_MESSAGE_CHANEL_NAME})...")
    socketio.run(app, host='0.0.0.0', port=80, debug=False)
