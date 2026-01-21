import eventlet
eventlet.monkey_patch()

import time
import sys
import os
import glob
import logging
from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, emit
from meshtastic.serial_interface import SerialInterface
from pubsub import pub

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

app = Flask(__name__, 
               template_folder='templates/app_chat',
               static_folder='static/app_chat')
app.config['SECRET_KEY'] = 'meshbridge_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

interface = None
current_dev_path = None
lora_connected = False

def get_time():
    return time.strftime("%H:%M", time.localtime())

def onReceive(packet, interface):
    try:
        if 'decoded' in packet and packet['decoded']['portnum'] == 'TEXT_MESSAGE_APP':
            msg = packet['decoded']['text']
            raw_id = packet.get('fromId')
            if raw_id is None:
                from_num = packet.get('from')
                if from_num is not None:
                    raw_id = f"!{from_num:08x}"
                else:
                    raw_id = 'Unknown'
            sender_display = f"LoRa-{raw_id[-4:]}" if len(raw_id) > 4 else raw_id
            lora_uuid = f"lora-{raw_id}"

            print(f"[收到 LoRa] {sender_display}: {msg}")
            
            socketio.emit('new_message', {
                'text': msg,
                'sender': sender_display,
                'userId': lora_uuid,
                'time': get_time(),
                'source': 'lora',
                'loraSuccess': True
            })
    except Exception as e:
        print(f"Packet Error: {e}")

def scan_for_meshtastic():
    patterns = ["/dev/ttyACM*", "/dev/ttyUSB*"]
    found_ports = []
    for p in patterns:
        found_ports.extend(glob.glob(p))
    return found_ports[0] if found_ports else None

def mesh_loop():
    global interface, current_dev_path, lora_connected
    print("啟動 Meshtastic 自動偵測與監聽...")
    
    while True:
        try:
            if interface is None:
                if lora_connected:
                    lora_connected = False
                    socketio.emit('lora_status', {'online': False})
                
                target_port = scan_for_meshtastic()
                if target_port:
                    print(f"發現裝置於: {target_port}，嘗試連線...")
                    
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
    
    emit('new_message', {
        'text': text,
        'sender': sender,
        'userId': user_id,
        'time': get_time(),
        'source': 'local',
        'loraSuccess': is_sent_to_lora
    }, broadcast=True)

def run_chat_app():
    socketio.start_background_task(target=mesh_loop)
    print("MeshBridge Chat 伺服器啟動中 (Port 80)...")
    socketio.run(app, host='0.0.0.0', port=80, debug=False)
