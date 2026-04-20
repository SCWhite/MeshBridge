#!/usr/bin/env python3
"""
transceive_stats.py — 查詢過去 N 分鐘內本機 LoRa sent 的 note 及其 ack_records

用法：
  sudo venv/bin/python3 transceive_stats.py 120
  sudo venv/bin/python3 transceive_stats.py 120 "小巨蛋"
  sudo venv/bin/python3 transceive_stats.py 120 "長壽公園,小巨蛋"
"""

import sys
import sqlite3
import time
from datetime import datetime

DB_PATH = 'noteboard.db'
USER_ACK_DELAY = 30  # seconds
ONLY_FIRST_SEND_TIMING = True  # True: 僅 resent_count=0 才計入時間統計


def ts_ms_to_str(ts_ms):
    """將毫秒時間戳轉為可讀字串"""
    if ts_ms is None:
        return '-'
    return datetime.fromtimestamp(ts_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')


def main():
    if len(sys.argv) < 2:
        print("用法: python3 transceive_stats.py <分鐘數> [關鍵字]")
        print("範例: sudo venv/bin/python3 transceive_stats.py 120")
        print("範例: sudo venv/bin/python3 transceive_stats.py 120 \"小巨蛋\"")
        print("範例: sudo venv/bin/python3 transceive_stats.py 120 \"4長壽公園,5小巨蛋\"")
        sys.exit(1)

    try:
        minutes = int(sys.argv[1])
    except ValueError:
        print(f"錯誤: '{sys.argv[1]}' 不是有效的數字")
        sys.exit(1)

    keyword_arg = sys.argv[2] if len(sys.argv) >= 3 else None
    keywords = [k.strip() for k in keyword_arg.split(',')] if keyword_arg else []

    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - minutes * 60 * 1000

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 查詢過去 N 分鐘內 status='LoRa sent' 的所有 note
    cursor.execute('''
        SELECT note_id, board_id, body, status, created_at, updated_at,
               lora_msg_id, lora_node_id, resent_count, bg_color,
               reply_lora_msg_id, is_pined_note, transmit_st_at
        FROM notes
        WHERE status = 'LoRa sent'
          AND deleted = 0
          AND created_at >= ?
        ORDER BY created_at DESC
    ''', (cutoff_ms,))
    all_notes = cursor.fetchall()

    # 決定要處理的關鍵字清單（無關鍵字時處理全部 notes 一次）
    keyword_list = keywords if keywords else [None]

    # 關鍵字統計 CSV header（多組時最後統一印）
    csv_summary_lines = []

    for kw in keyword_list:
        if kw:
            notes = [n for n in all_notes if kw in n['body']]
        else:
            notes = list(all_notes)

        filter_info = f'，關鍵字="{kw}"' if kw else ''
        print(f"=== LoRa sent notes（過去 {minutes} 分鐘{filter_info}） ===")
        print(f"查詢時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"起始時間: {ts_ms_to_str(cutoff_ms)}")
        print(f"共找到 {len(notes)} 筆 note")
        print()

        if not notes:
            if kw:
                csv_summary_lines.append(f'"{kw}",,,,,,,,,,,')
            continue

        for i, note in enumerate(notes, 1):
            note_id = note['note_id']

            print(f"--- Note #{i} ---")
            print(f"  note_id        : {note_id}")
            print(f"  board_id       : {note['board_id']}")
            print(f"  lora_msg_id    : {note['lora_msg_id'] or '-'}")
            print(f"  lora_node_id   : {note['lora_node_id'] or '-'}")
            print(f"  body           : {note['body'][:80]}{'...' if len(note['body']) > 80 else ''}")
            print(f"  status         : {note['status']}")
            print(f"  created_at     : {ts_ms_to_str(note['created_at'])}")
            print(f"  updated_at     : {ts_ms_to_str(note['updated_at'])}")
            print(f"  resent_count   : {note['resent_count']}")
            print(f"  reply_lora_msg_id : {note['reply_lora_msg_id'] or '-'}")
            print(f"  is_pined_note  : {note['is_pined_note']}")

            # 查詢該 note 對應的 ack_records
            cursor.execute('''
                SELECT ack_id, note_id, created_at, updated_at, lora_node_id, hop_limit, hop_start
                FROM ack_records
                WHERE note_id = ?
                ORDER BY created_at ASC
            ''', (note_id,))

            acks = cursor.fetchall()
            print(f"  ack_records    : {len(acks)} 筆")

            for j, ack in enumerate(acks, 1):
                hop_info = ''
                if ack['hop_limit'] is not None or ack['hop_start'] is not None:
                    hl = ack['hop_limit'] if ack['hop_limit'] is not None else 0
                    hop_info = f"  hop_limit={hl}, hop_start={ack['hop_start']}"
                print(f"    [{j}] node={ack['lora_node_id']}, "
                      f"created={ts_ms_to_str(ack['created_at'])}, "
                      f"updated={ts_ms_to_str(ack['updated_at'])}{hop_info}")

            print()

        # === CSV 總表 ===
        print("=== CSV 總表 ===")
        print("body,resent_count,is_ack,first_node_ack_sec,duration_sec,used_hop")

        total_rows = 0
        ack_rows = 0
        durations_sec = []
        first_node_ack_secs = []
        hops = []
        resent_counts = []
        transmit_success = 0
        transmit_total = 0

        for note in notes:
            note_id = note['note_id']
            body_escaped = note['body'].replace('"', '""')
            resent = note['resent_count']

            cursor.execute('''
                Select updated_at, lora_node_id, hop_limit, hop_start
                FROM ack_records
                WHERE note_id = ?
                ORDER BY updated_at ASC
            ''', (note_id,))
            acks = cursor.fetchall()

            tx_st = note['transmit_st_at']
            fn_ack_sec = ''
            if tx_st is not None and note['updated_at'] is not None:
                fn_ack_val = (note['updated_at'] - tx_st) / 1000
                fn_ack_sec = round(fn_ack_val, 1)
                if not ONLY_FIRST_SEND_TIMING or resent == 0:
                    first_node_ack_secs.append(fn_ack_val)

            if not acks:
                total_rows += 1
                transmit_total += resent + 1
                print(f'"{body_escaped}",{resent},0,{fn_ack_sec},,')
            else:
                transmit_success += 1
                transmit_total += resent + 1
                for ack in acks:
                    total_rows += 1
                    ack_rows += 1
                    dur_sec = (ack['updated_at'] - tx_st) / 1000 - USER_ACK_DELAY if tx_st else 0
                    if not ONLY_FIRST_SEND_TIMING or resent == 0:
                        durations_sec.append(dur_sec)
                    resent_counts.append(resent)
                    duration_sec = round(dur_sec, 1)
                    if ack['hop_start'] is not None:
                        hl = ack['hop_limit'] if ack['hop_limit'] is not None else 0
                        used_hop = ack['hop_start'] - hl
                        hops.append(used_hop)
                    else:
                        used_hop = ''
                    print(f'"{body_escaped}",{resent},1,{fn_ack_sec},{duration_sec},{used_hop}')

        # === 關鍵字統計 ===
        if kw:
            print()
            print("=== 關鍵字統計 ===")
            print(f"  keyword              : {kw}")
            rate = (ack_rows / total_rows * 100) if total_rows > 0 else 0
            print(f"  success_rate (task)      : {ack_rows}/{total_rows} ({rate:.1f}%)")
            t_rate = (transmit_success / transmit_total * 100) if transmit_total > 0 else 0
            print(f"  success_rate (transmit)  : {transmit_success}/{transmit_total} ({t_rate:.1f}%)")
            if resent_counts:
                avg_resent = sum(resent_counts) / len(resent_counts)
                print(f"  avg_resent_count     : {round(avg_resent, 1)}")
                print(f"  max_resent_count     : {max(resent_counts)}")
                print(f"  min_resent_count     : {min(resent_counts)}")
            else:
                print(f"  avg_resent_count     : -")
                print(f"  max_resent_count     : -")
                print(f"  min_resent_count     : -")
            if first_node_ack_secs:
                print(f"  avg_first_node_ack   : {round(sum(first_node_ack_secs) / len(first_node_ack_secs), 1)} sec")
                print(f"  max_first_node_ack   : {round(max(first_node_ack_secs), 1)} sec")
                print(f"  min_first_node_ack   : {round(min(first_node_ack_secs), 1)} sec")
            else:
                print(f"  avg_first_node_ack   : -")
                print(f"  max_first_node_ack   : -")
                print(f"  min_first_node_ack   : -")
            if durations_sec:
                avg_sec = sum(durations_sec) / len(durations_sec)
                max_sec = max(durations_sec)
                min_sec = min(durations_sec)
                print(f"  avg_round_trip       : {round(avg_sec, 1)} sec")
                print(f"  max_round_trip       : {round(max_sec, 1)} sec")
                print(f"  min_round_trip       : {round(min_sec, 1)} sec")
            else:
                print(f"  avg_round_trip       : -")
                print(f"  max_round_trip       : -")
                print(f"  min_round_trip       : -")
            if hops:
                print(f"  avg_used_hop         : {round(sum(hops) / len(hops), 1)}")
                print(f"  max_used_hop         : {max(hops)}")
                print(f"  min_used_hop         : {min(hops)}")
            else:
                print(f"  avg_used_hop         : -")
                print(f"  max_used_hop         : -")
                print(f"  min_used_hop         : -")

            # 收集 CSV summary line
            csv_avg_resent = round(sum(resent_counts) / len(resent_counts), 1) if resent_counts else ''
            csv_max_resent = max(resent_counts) if resent_counts else ''
            csv_min_resent = min(resent_counts) if resent_counts else ''
            csv_avg_fna = round(sum(first_node_ack_secs) / len(first_node_ack_secs), 1) if first_node_ack_secs else ''
            csv_max_fna = round(max(first_node_ack_secs), 1) if first_node_ack_secs else ''
            csv_min_fna = round(min(first_node_ack_secs), 1) if first_node_ack_secs else ''
            csv_avg_rt_sec = round(sum(durations_sec) / len(durations_sec), 1) if durations_sec else ''
            csv_max_rt_sec = round(max(durations_sec), 1) if durations_sec else ''
            csv_min_rt_sec = round(min(durations_sec), 1) if durations_sec else ''
            csv_avg_hop = round(sum(hops) / len(hops), 1) if hops else ''
            csv_max_hop = max(hops) if hops else ''
            csv_min_hop = min(hops) if hops else ''

            csv_summary_lines.append(
                f'"{kw}",{rate:.1f}%,{t_rate:.1f}%,{csv_avg_resent},{csv_max_resent},{csv_min_resent},{csv_avg_fna},{csv_max_fna},{csv_min_fna},{csv_avg_rt_sec},{csv_max_rt_sec},{csv_min_rt_sec},{csv_avg_hop},{csv_max_hop},{csv_min_hop}'
            )

        print()

    # === 關鍵字統計 CSV（統一印出） ===
    if csv_summary_lines:
        print("=== 關鍵字統計 CSV ===")
        print("keyword,success_rate_task,success_rate_transmit,avg_resent_count,max_resent_count,min_resent_count,avg_first_node_ack_sec,max_first_node_ack_sec,min_first_node_ack_sec,avg_round_trip_sec,max_round_trip_sec,min_round_trip_sec,avg_used_hop,max_used_hop,min_used_hop")
        for line in csv_summary_lines:
            print(line)

    conn.close()


if __name__ == '__main__':
    main()
