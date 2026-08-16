"""
ePaper 獨立進程執行器 (Subprocess Runner)
專門處理透過獨立 Python 子進程 (subprocess) 呼叫 epaper_update.py 的執行邏輯。
避免在 app_noteboard_epaper.py、app_shutdown.py 等處重複寫 venv/bin/python3 與 subprocess.run 樣板。
"""

import os
import sys
import subprocess


def get_python_binary(project_root: str) -> str:
    """取得 Python 執行檔路徑 (優先使用 venv)"""
    venv_python = os.path.join(project_root, 'venv', 'bin', 'python3')
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable or 'python3'


def run_epaper_cmd(action: str, *args, timeout: int = 120, log_fn=print) -> bool:
    """
    執行 hardware/epaper/epaper_update.py 的命令 (如 'display' 或 'clear')。

    Args:
        action: 'display' 或 'clear'
        *args: 傳遞給腳本的額外參數 (例如圖檔路徑)
        timeout: 超時限制 (秒)
        log_fn: 日誌輸出函式 (預設為 print)

    Returns:
        bool: 成功回傳 True，失敗回傳 False
    """
    current_dir = os.path.dirname(os.path.realpath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
    script = os.path.join(current_dir, 'epaper_update.py')

    if not os.path.exists(script):
        log_fn(f"[ePaper Subprocess] 錯誤：找不到腳本 {script}")
        return False

    python_bin = get_python_binary(project_root)
    cmd = [python_bin, script, action] + list(args)

    log_fn(f"[ePaper Subprocess] 執行電子紙 {action} 作業...")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=project_root
        )

        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                if line:
                    log_fn(line)
        if result.stderr:
            for line in result.stderr.strip().split('\n'):
                if line:
                    log_fn(line)

        if result.returncode == 0:
            return True
        else:
            log_fn(f"[ePaper Subprocess] 子程序返回錯誤碼: {result.returncode}")
            return False

    except subprocess.TimeoutExpired:
        log_fn(f"[ePaper Subprocess] 執行超時（{timeout}秒）")
        return False
    except Exception as e:
        log_fn(f"[ePaper Subprocess] 執行失敗: {e}")
        return False
