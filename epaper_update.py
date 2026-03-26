#!/usr/bin/env python3
"""
ePaper 顯示更新獨立腳本。
透過 subprocess 呼叫，避免 eventlet monkey_patch 與 lgpio 的衝突。

用法:
    python3 epaper_update.py display <image_path>
    python3 epaper_update.py clear
"""

import sys
import os

# 加入 ePaper 驅動庫路徑
basedir = os.path.dirname(os.path.realpath(__file__))
driverdir = os.path.join(basedir, 'epaper_driver')
if driverdir not in sys.path:
    sys.path.insert(0, driverdir)


# 支援的裝置對應表：device_id -> (模組名稱, 清屏參數)
DEVICE_DRIVERS = {
    'weshare-epd7in3e': {'module': 'epd7in3e', 'clear_arg': 0x11},
    'weshare-epd7in5_V2': {'module': 'epd7in5_V2', 'clear_arg': None},
}


def get_driver(device_id):
    """根據 device_id 載入對應的驅動模組並建立 EPD 實例"""
    info = DEVICE_DRIVERS.get(device_id)
    if info is None:
        print(f'[ePaper] 不支援的裝置: {device_id}')
        return None, None
    module = __import__(info['module'])
    return module.EPD(), info


def display_image(image_path, device_id):
    """將圖檔顯示到電子紙"""
    epd = None
    try:
        from PIL import Image as PILImage

        epd, info = get_driver(device_id)
        if epd is None:
            return 1

        print(f'[ePaper] 初始化 {info["module"]}...')
        if epd.init() != 0:
            print('[ePaper] 錯誤：無法初始化電子紙模組')
            return 1

        print(f'[ePaper] 載入圖檔: {image_path}')
        image = PILImage.open(image_path)

        print('[ePaper] 轉換圖檔並傳送至電子紙模組...')
        buf = epd.getbuffer(image)
        epd.display(buf)

        print('[ePaper] 電子紙進入休眠模式...')
        epd.sleep()

        print('[ePaper] 電子紙顯示更新完成！')
        return 0

    except Exception as e:
        print(f'[ePaper] 電子紙顯示錯誤: {e}')
        import traceback
        traceback.print_exc()
        try:
            if epd: epd.sleep()
        except Exception:
            pass
        return 1


def clear_display(device_id):
    """清屏（刷白）"""
    epd = None
    try:
        epd, info = get_driver(device_id)
        if epd is None:
            return 1

        print(f'[ePaper] 清屏：初始化 {info["module"]}...')
        if epd.init() != 0:
            print('[ePaper] 清屏失敗：無法初始化電子紙模組')
            return 1

        print('[ePaper] 清屏：刷白屏幕...')
        clear_arg = info['clear_arg']
        if clear_arg is not None:
            epd.Clear(clear_arg)
        else:
            epd.Clear()

        print('[ePaper] 清屏：進入休眠模式...')
        epd.sleep()

        print('[ePaper] 清屏完成，屏幕已刷白可安全存放')
        return 0

    except Exception as e:
        print(f'[ePaper] 清屏錯誤: {e}')
        import traceback
        traceback.print_exc()
        try:
            if epd: epd.sleep()
        except Exception:
            pass
        return 1


def check_epaper_enabled():
    """檢查 config.py 是否啟用 ePaper 功能"""
    try:
        sys.path.insert(0, basedir)
        import config
        module_id = getattr(config, 'EPAPER_MODULE_ID', None)
        if not module_id or not module_id.strip():
            return None
        return module_id.strip()
    except ImportError:
        return None


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('用法: python3 epaper_update.py display <image_path>')
        print('      python3 epaper_update.py clear')
        sys.exit(1)

    command = sys.argv[1]

    # 檢查是否啟用 ePaper，未啟用時靜默成功退出
    device_id = check_epaper_enabled()
    if device_id is None:
        print('[ePaper] 未設定 EPAPER_MODULE_ID，跳過')
        sys.exit(0)

    if command == 'display':
        if len(sys.argv) < 3:
            print('錯誤: 請指定圖檔路徑')
            sys.exit(1)
        sys.exit(display_image(sys.argv[2], device_id))

    elif command == 'clear':
        sys.exit(clear_display(device_id))

    else:
        print(f'未知命令: {command}')
        sys.exit(1)
