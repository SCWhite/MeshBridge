#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import re
import sqlite3
from pathlib import Path
from typing import List, Tuple, Dict, Optional


DEFAULT_LIMIT_MB = 99  # 留一點 buffer，避免壓線


def connect_ro(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def connect_rw(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,)
    )
    return cur.fetchone() is not None


def get_mbtiles_schema_type(conn: sqlite3.Connection) -> str:
    """
    Return:
      - "tiles" if tiles table exists
      - "map_images" if map + images exist
    """
    if table_exists(conn, "tiles"):
        return "tiles"
    if table_exists(conn, "map") and table_exists(conn, "images"):
        return "map_images"
    raise RuntimeError(
        "Unsupported MBTiles schema. Expected 'tiles' table or ('map' + 'images')."
    )


def sanitize_name(s: str) -> str:
    s = re.sub(r"[^\w\-.]+", "_", s.strip())
    return s or "output"


def get_zoom_levels(conn: sqlite3.Connection, schema: str) -> List[int]:
    if schema == "tiles":
        rows = conn.execute("SELECT DISTINCT zoom_level FROM tiles ORDER BY zoom_level").fetchall()
    else:
        rows = conn.execute("SELECT DISTINCT zoom_level FROM map ORDER BY zoom_level").fetchall()
    return [int(r[0]) for r in rows]


def estimate_zoom_sizes_bytes(conn: sqlite3.Connection, schema: str) -> Dict[int, int]:
    """
    Estimate per-zoom payload size by summing tile_data blob lengths.
    This is an estimate, not exact file size.
    """
    if schema == "tiles":
        q = """
        SELECT zoom_level, SUM(LENGTH(tile_data)) AS bytes
        FROM tiles
        GROUP BY zoom_level
        ORDER BY zoom_level
        """
        rows = conn.execute(q).fetchall()
        return {int(r["zoom_level"]): int(r["bytes"] or 0) for r in rows}

    # map/images schema: blob is in images, so join via tile_id
    q = """
    SELECT m.zoom_level AS zoom_level, SUM(LENGTH(i.tile_data)) AS bytes
    FROM map m
    JOIN images i ON m.tile_id = i.tile_id
    GROUP BY m.zoom_level
    ORDER BY m.zoom_level
    """
    rows = conn.execute(q).fetchall()
    return {int(r["zoom_level"]): int(r["bytes"] or 0) for r in rows}


def group_zooms_by_limit(
    zooms: List[int],
    zoom_bytes: Dict[int, int],
    limit_bytes: int,
    overhead_factor: float = 1.25,
) -> List[List[int]]:
    """
    Greedy grouping: pack consecutive zoom levels into a file until estimated size hits limit.
    overhead_factor accounts for sqlite overhead/index/metadata.
    """
    groups: List[List[int]] = []
    current: List[int] = []
    current_est = 0

    for z in zooms:
        est = int(zoom_bytes.get(z, 0) * overhead_factor)

        # If this single zoom is already too big, we still output it as its own group,
        # but caller should warn user.
        if not current:
            current = [z]
            current_est = est
            continue

        if current_est + est <= limit_bytes:
            current.append(z)
            current_est += est
        else:
            groups.append(current)
            current = [z]
            current_est = est

    if current:
        groups.append(current)
    return groups


def copy_metadata(src: sqlite3.Connection, dst: sqlite3.Connection):
    dst.execute("CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)")
    dst.execute("DELETE FROM metadata")
    if table_exists(src, "metadata"):
        for row in src.execute("SELECT name, value FROM metadata"):
            dst.execute("INSERT INTO metadata(name, value) VALUES(?, ?)", (row["name"], row["value"]))


def upsert_metadata(dst: sqlite3.Connection, name: str, value: str):
    dst.execute("DELETE FROM metadata WHERE name=?", (name,))
    dst.execute("INSERT INTO metadata(name, value) VALUES(?, ?)", (name, value))


def create_schema_tiles(dst: sqlite3.Connection):
    dst.execute("""
      CREATE TABLE IF NOT EXISTS tiles (
        zoom_level INTEGER,
        tile_column INTEGER,
        tile_row INTEGER,
        tile_data BLOB
      )
    """)
    dst.execute("CREATE UNIQUE INDEX IF NOT EXISTS tile_index ON tiles (zoom_level, tile_column, tile_row)")


def create_schema_map_images(dst: sqlite3.Connection):
    dst.execute("""
      CREATE TABLE IF NOT EXISTS map (
        zoom_level INTEGER,
        tile_column INTEGER,
        tile_row INTEGER,
        tile_id TEXT
      )
    """)
    dst.execute("""
      CREATE TABLE IF NOT EXISTS images (
        tile_id TEXT PRIMARY KEY,
        tile_data BLOB
      )
    """)
    dst.execute("CREATE UNIQUE INDEX IF NOT EXISTS map_index ON map (zoom_level, tile_column, tile_row)")
    # images already has PK


def vacuum_and_size(path: str, conn: sqlite3.Connection) -> int:
    conn.execute("VACUUM")
    conn.commit()
    return os.path.getsize(path)


def split_tiles_schema(src_path: str, out_path: str, zooms: List[int], limit_bytes: int) -> int:
    src = connect_ro(src_path)
    dst = connect_rw(out_path)

    # speed pragmas (safe for one-off generation)
    dst.execute("PRAGMA journal_mode=OFF")
    dst.execute("PRAGMA synchronous=OFF")
    dst.execute("PRAGMA temp_store=MEMORY")

    copy_metadata(src, dst)
    create_schema_tiles(dst)

    zmin, zmax = min(zooms), max(zooms)
    upsert_metadata(dst, "minzoom", str(zmin))
    upsert_metadata(dst, "maxzoom", str(zmax))

    # Copy tiles
    placeholders = ",".join(["?"] * len(zooms))
    q = f"""
      INSERT INTO tiles(zoom_level, tile_column, tile_row, tile_data)
      SELECT zoom_level, tile_column, tile_row, tile_data
      FROM tiles
      WHERE zoom_level IN ({placeholders})
    """
    dst.execute("BEGIN")
    dst.execute(q, zooms)
    dst.commit()

    size = vacuum_and_size(out_path, dst)

    dst.close()
    src.close()

    if size > limit_bytes:
        print(f"  ⚠️  Output still over limit: {size/1024/1024:.1f} MB > {limit_bytes/1024/1024:.1f} MB")
    return size


def split_map_images_schema(src_path: str, out_path: str, zooms: List[int], limit_bytes: int) -> int:
    src = connect_ro(src_path)
    dst = connect_rw(out_path)

    dst.execute("PRAGMA journal_mode=OFF")
    dst.execute("PRAGMA synchronous=OFF")
    dst.execute("PRAGMA temp_store=MEMORY")

    copy_metadata(src, dst)
    create_schema_map_images(dst)

    zmin, zmax = min(zooms), max(zooms)
    upsert_metadata(dst, "minzoom", str(zmin))
    upsert_metadata(dst, "maxzoom", str(zmax))

    placeholders = ",".join(["?"] * len(zooms))

    # Copy map rows for zooms
    dst.execute("BEGIN")
    dst.execute(
        f"""
        INSERT INTO map(zoom_level, tile_column, tile_row, tile_id)
        SELECT zoom_level, tile_column, tile_row, tile_id
        FROM map
        WHERE zoom_level IN ({placeholders})
        """,
        zooms,
    )
    dst.commit()

    # Copy only referenced images
    dst.execute("BEGIN")
    dst.execute(
        """
        INSERT OR IGNORE INTO images(tile_id, tile_data)
        SELECT i.tile_id, i.tile_data
        FROM images i
        JOIN (SELECT DISTINCT tile_id FROM map) m ON i.tile_id = m.tile_id
        """
    )
    dst.commit()

    size = vacuum_and_size(out_path, dst)

    dst.close()
    src.close()

    if size > limit_bytes:
        print(f"  ⚠️  Output still over limit: {size/1024/1024:.1f} MB > {limit_bytes/1024/1024:.1f} MB")
    return size


def main():
    ap = argparse.ArgumentParser(
        description="Split a .mbtiles into multiple files grouped by zoom level, each under GitHub file limit."
    )
    ap.add_argument("input", help="Path to input .mbtiles")
    ap.add_argument("-o", "--outdir", default=".", help="Output directory (default: current)")
    ap.add_argument("--prefix", default=None, help="Output filename prefix (default: input filename without extension)")
    ap.add_argument("--limit-mb", type=float, default=DEFAULT_LIMIT_MB, help=f"Max output file size in MB (default: {DEFAULT_LIMIT_MB})")
    ap.add_argument("--overhead", type=float, default=1.25, help="Overhead factor for grouping estimate (default: 1.25)")
    args = ap.parse_args()

    in_path = args.input
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    prefix = args.prefix or Path(in_path).stem
    prefix = sanitize_name(prefix)

    limit_bytes = int(args.limit_mb * 1024 * 1024)

    src = connect_ro(in_path)
    schema = get_mbtiles_schema_type(src)
    zooms = get_zoom_levels(src, schema)
    if not zooms:
        raise RuntimeError("No zoom levels found in mbtiles.")

    zoom_bytes = estimate_zoom_sizes_bytes(src, schema)
    src.close()

    # Warn if any single zoom is likely over limit
    for z in zooms:
        est = int(zoom_bytes.get(z, 0) * args.overhead)
        if est > limit_bytes:
            print(f"⚠️  Zoom {z} estimated payload too large ({est/1024/1024:.1f} MB est).")
            print("    This zoom alone may exceed GitHub limit; you may need to split by region/tile range or use Git LFS.\n")

    groups = group_zooms_by_limit(zooms, zoom_bytes, limit_bytes, overhead_factor=args.overhead)

    print(f"Input: {in_path}")
    print(f"Schema: {schema}")
    print(f"Zooms: {zooms[0]}..{zooms[-1]} ({len(zooms)} levels)")
    print(f"Limit: {args.limit_mb} MB")
    print(f"Planned outputs: {len(groups)} file(s)\n")

    splitter = split_tiles_schema if schema == "tiles" else split_map_images_schema

    produced = []
    for i, g in enumerate(groups, start=1):
        zmin, zmax = min(g), max(g)
        out_path = outdir / f"{prefix}_z{zmin}-{zmax}.mbtiles"
        if out_path.exists():
            out_path.unlink()

        print(f"[{i}/{len(groups)}] Writing {out_path.name} (zooms {zmin}-{zmax}) ...")
        size = splitter(in_path, str(out_path), g, limit_bytes)
        print(f"  -> {size/1024/1024:.1f} MB\n")
        produced.append((str(out_path), size, zmin, zmax))

    print("Done. Outputs:")
    for p, s, zmin, zmax in produced:
        ok = "OK" if s <= limit_bytes else "OVER"
        print(f"  {ok:4}  {s/1024/1024:8.1f} MB   z{zmin}-{zmax}   {p}")

    print("\nTip: If any output is still OVER, reduce --limit-mb or use Git LFS / split by region.")


if __name__ == "__main__":
    main()