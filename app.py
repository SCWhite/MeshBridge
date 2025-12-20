import eventlet
eventlet.monkey_patch()

import time
import sys
import os
import glob
from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, emit
from meshtastic.serial_interface import SerialInterface
from pubsub import pub

app = Flask(__name__)
app.config['SECRET_KEY'] = 'meshbridge_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# 全域變數
interface = None
current_dev_path = None
lora_connected = False  # <--- 新增：記錄 LoRa 連線狀態

def get_time():
    return time.strftime("%H:%M", time.localtime())

# --- 1. Meshtastic 訊息接收 ---
def onReceive(packet, interface):
    try:
        if 'decoded' in packet and packet['decoded']['portnum'] == 'TEXT_MESSAGE_APP':
            msg = packet['decoded']['text']
            raw_id = packet.get('fromId', 'Unknown')
            sender_display = f"LoRa-{raw_id[-4:]}" if len(raw_id) > 4 else raw_id
            lora_uuid = f"lora-{raw_id}"

            print(f"[收到 LoRa] {sender_display}: {msg}")
            
            socketio.emit('new_message', {
                'text': msg,
                'sender': sender_display,
                'userId': lora_uuid,
                'time': get_time(),
                'source': 'lora',
                'loraSuccess': True # LoRa 來的當然是 True
            })
    except Exception as e:
        print(f"Packet Error: {e}")

# --- 2. 裝置掃描 ---
def scan_for_meshtastic():
    patterns = ["/dev/ttyACM*", "/dev/ttyUSB*"]
    found_ports = []
    for p in patterns:
        found_ports.extend(glob.glob(p))
    return found_ports[0] if found_ports else None

# --- 3. 背景監聽迴圈 ---
def mesh_loop():
    global interface, current_dev_path, lora_connected
    print("啟動 Meshtastic 自動偵測與監聽...")
    
    while True:
        try:
            # === 狀態 A: 未連線 ===
            if interface is None:
                # 如果狀態改變了 (原本是 True 變成 False)，通知前端
                if lora_connected:
                    lora_connected = False
                    socketio.emit('lora_status', {'online': False})
                
                target_port = scan_for_meshtastic()
                if target_port:
                    print(f"發現裝置於: {target_port}，嘗試連線...")
                    interface = SerialInterface(devPath=target_port)
                    current_dev_path = target_port
                    pub.subscribe(onReceive, "meshtastic.receive")
                    
                    print(f">>> 成功連線至 {target_port} <<<")
                    
                    # 更新狀態並通知前端
                    lora_connected = True
                    socketio.emit('lora_status', {'online': True})
                else:
                    time.sleep(3)

            # === 狀態 B: 已連線 ===
            else:
                if current_dev_path and not os.path.exists(current_dev_path):
                    raise Exception(f"裝置路徑 {current_dev_path} 已消失")
                
                # 再次確保狀態同步 (防止極端情況)
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
            
            # 發生異常，標記斷線
            if lora_connected:
                lora_connected = False
                socketio.emit('lora_status', {'online': False})
            
            print("正在重置狀態... (3秒後重試)")
            time.sleep(3)
            
        eventlet.sleep(2)

# --- Flask & SocketIO ---
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
    # 新用戶連入時，立刻告訴他目前的 LoRa 狀態
    emit('lora_status', {'online': lora_connected})

@socketio.on('send_mesh')
def handle_msg(data):
    text = data.get('text', '')
    sender = data.get('sender', 'WebUser')
    user_id = data.get('userId', 'anon')
    
    if not text: return

    full_msg = f"[{sender}] {text}"
    print(f"[網頁發送] {full_msg}")

    # 預設發送結果
    is_sent_to_lora = False

    # 嘗試發送到 LoRa
    if interface and lora_connected:
        try:
            interface.sendText(full_msg)
            is_sent_to_lora = True
        except Exception as e:
            print(f"LoRa 發送失敗: {e}")
            is_sent_to_lora = False
    
    # 廣播回網頁 (包含 loraSuccess 標記)
    emit('new_message', {
        'text': text,
        'sender': sender,
        'userId': user_id,
        'time': get_time(),
        'source': 'local',
        'loraSuccess': is_sent_to_lora  # <--- 關鍵：告訴前端有沒有成功送出
    }, broadcast=True)

if __name__ == '__main__':
    socketio.start_background_task(target=mesh_loop)
    print("MeshBridge 伺服器啟動中 (Port 80)...")
    socketio.run(app, host='0.0.0.0', port=80, debug=False)