"""
ePaper 裝置驅動與規格統一對照表 (Device Registry)
整合不同 ePaper 模組的驅動程式名稱、清屏參數、色彩模式與螢幕尺寸。
"""

DEVICE_REGISTRY = {
    'weshare-epd7in3e': {
        'module': 'epd7in3e',
        'clear_arg': 0x11,
        'color_mode': 'full_color',
        'screen_width': 800,
        'screen_height': 480,
    },
    'weshare-epd7in5_V2': {
        'module': 'epd7in5_V2',
        'clear_arg': None,
        'color_mode': 'mono',
        'screen_width': 800,
        'screen_height': 480,
    },
}

# 相容層：供 app_noteboard_epaper.py 使用
DEVICE_COLOR_MODE_MAPPING = {
    dev_id: {
        'color_mode': info['color_mode'],
        'screen_width': info['screen_width'],
        'screen_height': info['screen_height'],
    }
    for dev_id, info in DEVICE_REGISTRY.items()
}

# 相容層：供 epaper_update.py 使用
DEVICE_DRIVERS = {
    dev_id: {
        'module': info['module'],
        'clear_arg': info['clear_arg'],
    }
    for dev_id, info in DEVICE_REGISTRY.items()
}
