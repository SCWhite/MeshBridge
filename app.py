import subprocess
from config import LOCAL_APP

def get_power_status():
    """
    檢查 Raspberry Pi 的電力狀態
    
    使用 vcgencmd get_throttled 指令來檢查設備的電力和溫度狀態
    
    回傳值:
        dict: {
            'is_normal': bool,  # True 表示正常，False 表示異常
            'error_code': str,  # 錯誤碼 (十六進位)，正常時為 '0x0'
            'error_message': str,  # 錯誤訊息，正常時為空字串
            'details': dict  # 詳細狀態資訊
        }
    
    錯誤碼說明:
        Bit 0: 目前電壓不足
        Bit 1: 目前 ARM 頻率上限
        Bit 2: 目前過熱
        Bit 3: 目前軟性溫度限制
        Bit 16: 曾經電壓不足
        Bit 17: 曾經 ARM 頻率上限
        Bit 18: 曾經過熱
        Bit 19: 曾經軟性溫度限制
    """
    try:
        result = subprocess.run(
            ['vcgencmd', 'get_throttled'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return {
                'is_normal': False,
                'error_code': 'CMD_ERROR',
                'error_message': f'指令執行失敗: {result.stderr.strip()}',
                'details': {}
            }
        
        output = result.stdout.strip()
        
        if not output.startswith('throttled='):
            return {
                'is_normal': False,
                'error_code': 'PARSE_ERROR',
                'error_message': f'無法解析輸出: {output}',
                'details': {}
            }
        
        throttled_hex = output.split('=')[1]
        throttled_value = int(throttled_hex, 16)
        
        details = {
            'under_voltage_now': bool(throttled_value & 0x1),
            'arm_frequency_capped_now': bool(throttled_value & 0x2),
            'currently_throttled': bool(throttled_value & 0x4),
            'soft_temp_limit_now': bool(throttled_value & 0x8),
            'under_voltage_occurred': bool(throttled_value & 0x10000),
            'arm_frequency_capped_occurred': bool(throttled_value & 0x20000),
            'throttling_occurred': bool(throttled_value & 0x40000),
            'soft_temp_limit_occurred': bool(throttled_value & 0x80000)
        }
        
        is_normal = throttled_value == 0
        
        error_messages = []
        if details['under_voltage_now']:
            error_messages.append('目前電壓不足')
        if details['arm_frequency_capped_now']:
            error_messages.append('目前 ARM 頻率受限')
        if details['currently_throttled']:
            error_messages.append('目前過熱降頻')
        if details['soft_temp_limit_now']:
            error_messages.append('目前達到軟性溫度限制')
        if details['under_voltage_occurred']:
            error_messages.append('曾經電壓不足')
        if details['arm_frequency_capped_occurred']:
            error_messages.append('曾經 ARM 頻率受限')
        if details['throttling_occurred']:
            error_messages.append('曾經過熱降頻')
        if details['soft_temp_limit_occurred']:
            error_messages.append('曾經達到軟性溫度限制')
        
        return {
            'is_normal': is_normal,
            'error_code': throttled_hex,
            'error_message': '、'.join(error_messages) if error_messages else '',
            'details': details
        }
        
    except FileNotFoundError:
        return {
            'is_normal': False,
            'error_code': 'NOT_FOUND',
            'error_message': 'vcgencmd 指令不存在 (可能不是在 Raspberry Pi 上執行)',
            'details': {}
        }
    except subprocess.TimeoutExpired:
        return {
            'is_normal': False,
            'error_code': 'TIMEOUT',
            'error_message': '指令執行逾時',
            'details': {}
        }
    except Exception as e:
        return {
            'is_normal': False,
            'error_code': 'EXCEPTION',
            'error_message': f'發生錯誤: {str(e)}',
            'details': {}
        }

if __name__ == '__main__':
    print("=" * 50)
    print("MeshBridge 應用程式啟動器")
    print("=" * 50)
    print(f"目前配置模式: {LOCAL_APP}")
    print()
    print("如需切換模式，請編輯 config.py 中的 LOCAL_APP 設定：")
    print("  - LOCAL_APP = 'chat'      → 聊天室模式")
    print("  - LOCAL_APP = 'noteboard' → 留言板模式")
    print("=" * 50)
    print()
    
    if LOCAL_APP == "chat":
        print(">>> 啟動聊天室模式 <<<")
        from app_chat import run_chat_app
        run_chat_app()
    elif LOCAL_APP == "noteboard":
        print(">>> 啟動留言板模式 <<<")
        from app_noteboard import run_noteboard_app
        run_noteboard_app()
    else:
        print(f"❌ 錯誤：未知的 LOCAL_APP 設定值 '{LOCAL_APP}'")
        print("請在 config.py 中設定 LOCAL_APP 為 'chat' 或 'noteboard'")
        exit(1)