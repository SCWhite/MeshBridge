#!/usr/bin/env python3
"""
一次性資料庫遷移腳本
新增欄位：
- is_temp_parent_note: 0 | 1 (預設 0)
- is_pined_note: 0 | 1 (預設 0)
- resent_priority: INT (預設 0)
- grid_mode: STRING (預設 '')
- grid_x: INT (預設 0)
- grid_y: INT (預設 0)

重新命名欄位：
- reply_id → reply_lora_msg_id

使用方式：
    python3 migration.py
"""

import sqlite3
import os
import sys
from datetime import datetime

DB_PATH = 'noteboard.db'
BACKUP_SUFFIX = datetime.now().strftime('_%Y%m%d_%H%M%S.backup')

def check_column_exists(cursor, table_name, column_name):
    """檢查欄位是否已存在"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns

def backup_database():
    """備份資料庫"""
    if not os.path.exists(DB_PATH):
        print(f"❌ 資料庫檔案不存在: {DB_PATH}")
        return False
    
    backup_path = DB_PATH + BACKUP_SUFFIX
    try:
        import shutil
        shutil.copy2(DB_PATH, backup_path)
        print(f"✅ 資料庫已備份至: {backup_path}")
        return True
    except Exception as e:
        print(f"❌ 備份失敗: {e}")
        return False

def rename_column_sqlite(cursor, table_name, old_column, new_column):
    """重新命名欄位 (SQLite 需要重建表格)"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    
    column_defs = []
    for col in columns:
        col_id, name, col_type, not_null, default_val, pk = col
        if name == old_column:
            name = new_column
        
        col_def = f"{name} {col_type}"
        if not_null:
            col_def += " NOT NULL"
        if default_val is not None:
            col_def += f" DEFAULT {default_val}"
        if pk:
            col_def += " PRIMARY KEY"
        column_defs.append(col_def)
    
    old_column_names = [col[1] for col in columns]
    new_column_names = [new_column if name == old_column else name for name in old_column_names]
    
    cursor.execute(f"ALTER TABLE {table_name} RENAME TO {table_name}_old")
    
    cursor.execute(f"CREATE TABLE {table_name} ({', '.join(column_defs)})")
    
    cursor.execute(f"INSERT INTO {table_name} ({', '.join(new_column_names)}) SELECT {', '.join(old_column_names)} FROM {table_name}_old")
    
    cursor.execute(f"DROP TABLE {table_name}_old")

def migrate_database():
    """執行資料庫遷移"""
    if not os.path.exists(DB_PATH):
        print(f"❌ 資料庫檔案不存在: {DB_PATH}")
        print("   請先執行應用程式以建立資料庫")
        return False
    
    print(f"開始遷移資料庫: {DB_PATH}")
    print("-" * 60)
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        if check_column_exists(cursor, 'notes', 'reply_id') and not check_column_exists(cursor, 'notes', 'reply_lora_msg_id'):
            print("🔄 重新命名欄位: reply_id → reply_lora_msg_id")
            rename_column_sqlite(cursor, 'notes', 'reply_id', 'reply_lora_msg_id')
            print("✅ 欄位重新命名完成")
            conn.commit()
        elif check_column_exists(cursor, 'notes', 'reply_lora_msg_id'):
            print("⏭️  欄位 reply_lora_msg_id 已存在，跳過重新命名")
        else:
            print("⏭️  找不到 reply_id 欄位，跳過重新命名")
        
        print()
        
        new_columns = [
            ('is_temp_parent_note', 'INTEGER NOT NULL DEFAULT 0'),
            ('is_pined_note', 'INTEGER NOT NULL DEFAULT 0'),
            ('resent_priority', 'INTEGER NOT NULL DEFAULT 0'),
            ('grid_mode', 'TEXT NOT NULL DEFAULT \'\''),
            ('grid_x', 'INTEGER NOT NULL DEFAULT 0'),
            ('grid_y', 'INTEGER NOT NULL DEFAULT 0'),
        ]
        
        added_columns = []
        skipped_columns = []
        
        for column_name, column_type in new_columns:
            if check_column_exists(cursor, 'notes', column_name):
                print(f"⏭️  欄位已存在，跳過: {column_name}")
                skipped_columns.append(column_name)
            else:
                sql = f"ALTER TABLE notes ADD COLUMN {column_name} {column_type}"
                cursor.execute(sql)
                print(f"✅ 已新增欄位: {column_name} ({column_type})")
                added_columns.append(column_name)
        
        conn.commit()
        
        print("-" * 60)
        print("遷移完成摘要:")
        print(f"  - 新增欄位數: {len(added_columns)}")
        print(f"  - 跳過欄位數: {len(skipped_columns)}")
        
        if added_columns:
            print(f"\n新增的欄位:")
            for col in added_columns:
                print(f"  • {col}")
        
        if skipped_columns:
            print(f"\n已存在的欄位:")
            for col in skipped_columns:
                print(f"  • {col}")
        
        cursor.execute("PRAGMA table_info(notes)")
        all_columns = cursor.fetchall()
        print(f"\n目前 notes 表格共有 {len(all_columns)} 個欄位")
        
        conn.close()
        print("\n✅ 資料庫遷移成功完成！")
        return True
        
    except Exception as e:
        print(f"\n❌ 遷移失敗: {e}")
        import traceback
        traceback.print_exc()
        return False

def verify_migration():
    """驗證遷移結果"""
    print("\n" + "=" * 60)
    print("驗證遷移結果...")
    print("=" * 60)
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(notes)")
        columns = cursor.fetchall()
        
        print("\nnotes 表格結構:")
        print(f"{'欄位名稱':<25} {'類型':<20} {'預設值':<15}")
        print("-" * 60)
        for col in columns:
            col_id, name, col_type, not_null, default_val, pk = col
            default_str = str(default_val) if default_val is not None else 'NULL'
            print(f"{name:<25} {col_type:<20} {default_str:<15}")
        
        cursor.execute("SELECT COUNT(*) FROM notes")
        count = cursor.fetchone()[0]
        print(f"\n總記錄數: {count}")
        
        conn.close()
        print("\n✅ 驗證完成")
        return True
        
    except Exception as e:
        print(f"\n❌ 驗證失敗: {e}")
        return False

def main():
    print("=" * 60)
    print("MeshBridge NoteBoard 資料庫遷移工具")
    print("=" * 60)
    print()
    
    if not backup_database():
        print("\n⚠️  備份失敗，是否繼續？(y/N): ", end='')
        response = input().strip().lower()
        if response != 'y':
            print("已取消遷移")
            return 1
    
    print()
    
    if not migrate_database():
        print("\n❌ 遷移失敗，請檢查錯誤訊息")
        return 1
    
    if not verify_migration():
        print("\n⚠️  驗證失敗，但遷移可能已完成")
        return 1
    
    print("\n" + "=" * 60)
    print("遷移程序全部完成！")
    print("=" * 60)
    return 0

if __name__ == '__main__':
    sys.exit(main())
