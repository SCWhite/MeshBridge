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
    script = os.path.join(basedir, 'epaper_update.py')
    if not os.path.exists(script):
        log('[Shutdown] epaper_update.py 不存在，跳過電子紙清屏')
        return

    log('[Shutdown] 執行電子紙清屏...')
    try:
        result = subprocess.run(
            [python_bin, script, 'clear'],
            capture_output=True, text=True, timeout=90, cwd=basedir
        )
        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                log(line)
        if result.stderr:
            for line in result.stderr.strip().split('\n'):
                log(line)

        if result.returncode == 0:
            log('[Shutdown] 電子紙清屏完成')
        else:
            log(f'[Shutdown] 電子紙清屏失敗 (exit code: {result.returncode})')
    except subprocess.TimeoutExpired:
        log('[Shutdown] 電子紙清屏超時（90秒）')
    except Exception as e:
        log(f'[Shutdown] 電子紙清屏執行錯誤: {e}')


if __name__ == '__main__':
    log('[Shutdown] MeshBridge 關機前置作業開始...')

    # 1. ePaper 電子紙清屏
    shutdown_epaper()

    # 未來可在此新增其他關機動作
    # 2. ...

    log('[Shutdown] MeshBridge 關機前置作業完成')
