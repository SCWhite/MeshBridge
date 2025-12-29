from config import LOCAL_APP

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