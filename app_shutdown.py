#!/usr/bin/env python3
"""
MeshBridge 關機前置作業腳本。
由 systemd ExecStop 呼叫，在服務停止或系統關機時執行必要的清理工作。

目前功能：
    1. ePaper 電子紙清屏（刷白）

未來可擴充其他關機前的動作。
"""

import subprocess
import sys
import os
from datetime import datetime

basedir = os.path.dirname(os.path.realpath(__file__))
python_bin = os.path.join(basedir, 'venv', 'bin', 'python3')
if not os.path.exists(python_bin):
    python_bin = 'python3'

LOGFILE = os.path.join(basedir, 'shutdown.log')


def log(msg):
    """同時輸出到 stdout 和 shutdown.log"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{timestamp}] {msg}'
    print(line)
    try:
        with open(LOGFILE, 'a') as f:
            f.write(line + '\n')
    except Exception:
        pass


def shutdown_epaper():
    """呼叫 epaper_update.py clear 進行電子紙清屏"""
    from hardware.epaper import run_epaper_cmd
    success = run_epaper_cmd('clear', timeout=90, log_fn=log)
    if success:
        log('[Shutdown] 電子紙清屏完成')
    else:
        log('[Shutdown] 電子紙清屏未完成或發生錯誤')


if __name__ == '__main__':
    log('[Shutdown] MeshBridge 關機前置作業開始...')

    # 1. ePaper 電子紙清屏
    shutdown_epaper()

    # 未來可在此新增其他關機動作
    # 2. ...

    log('[Shutdown] MeshBridge 關機前置作業完成')
