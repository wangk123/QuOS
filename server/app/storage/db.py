# server/app/storage/db.py
# MySQL 元数据索引：可重建缓存而非真相源（真相源是 data/ 目录扫描）。
# 未配置 QUOS_DB_HOST = 禁用；不可达 = 本次调用降级（返回 None/{} 并 log 警告）。
import logging
import os
from pathlib import Path

import pymysql

log = logging.getLogger("quos.db")
_schema_ready = False

_COLS = "slug,name,description,status,created_at,last_opened_at,archived_at"


def connect():
    """返回已连库的 Connection；未配置或不可达返回 None（调用方一律判 None 降级）"""
    if not os.environ.get("QUOS_DB_HOST"):
        return None
    try:
        return pymysql.connect(
            host=os.environ["QUOS_DB_HOST"],
            port=int(os.environ.get("QUOS_DB_PORT", "3306")),
            user=os.environ.get("QUOS_DB_USER", ""),
            password=os.environ.get("QUOS_DB_PASSWORD", ""),
            database=os.environ.get("QUOS_DB_NAME", "quos"),
            charset="utf8mb4", connect_timeout=2, autocommit=True,
        )
    except pymysql.MySQLError as e:
        log.warning("MySQL 不可达，索引降级: %s", e)
        return None


def _safe_connect():
    """connect 的防御壳：任何异常（连接器炸裂、测试注入）一律降级为 None，不向上抛"""
    try:
        return connect()
    except Exception as e:  # noqa: BLE001 —— 降级语义优先于精确捕获
        log.warning("MySQL 连接异常，索引降级: %s", e)
        return None


def ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    conn = _safe_connect()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                  id             INT AUTO_INCREMENT PRIMARY KEY,
                  slug           VARCHAR(191) NOT NULL UNIQUE,
                  name           VARCHAR(191) NOT NULL,
                  description    TEXT,
                  status         ENUM('active','archived') NOT NULL DEFAULT 'active',
                  created_at     DATETIME NOT NULL,
                  last_opened_at DATETIME NULL,
                  archived_at    DATETIME NULL
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""")
    except pymysql.MySQLError as e:
        log.warning("建表降级: %s", e)
        return
    finally:
        conn.close()
    _schema_ready = True


def reconcile(rows):
    """文件系统扫描行对账进 DB；返回 {slug: {last_opened_at}}（禁用/失败返回 {}）。

    幽灵行清理限定在传入行的 status 域内：单侧列表（active 或 archived）对账
    不得互删另一侧的行，否则交替调用列表会反复丢 last_opened_at。
    rows 为空 = 纯查询语义，不清任何幽灵行。
    """
    ensure_schema()
    conn = _safe_connect()
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            slugs = {r["slug"] for r in rows}
            statuses = {r["status"] for r in rows}
            if statuses:
                ph = ",".join(["%s"] * len(statuses))
                cur.execute(
                    f"SELECT slug FROM projects WHERE status IN ({ph})",
                    tuple(statuses))
                for (ghost,) in cur.fetchall():
                    if ghost not in slugs:
                        cur.execute("DELETE FROM projects WHERE slug=%s", (ghost,))
            for r in rows:
                if not r.get("created_at"):
                    continue  # 手工目录无元信息：不进索引，也不阻塞其他行
                cur.execute("""
                    INSERT INTO projects (slug,name,description,status,created_at)
                    VALUES (%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      name=VALUES(name), description=VALUES(description),
                      status=VALUES(status), created_at=VALUES(created_at)""",
                    (r["slug"], r["name"], r["description"] or "",
                     r["status"], r["created_at"]))
            cur.execute("SELECT slug, IFNULL(last_opened_at,'') FROM projects")
            return {s: {"last_opened_at": t.isoformat() if hasattr(t, "isoformat") else (t or None)}
                    for s, t in cur.fetchall()}
    except pymysql.MySQLError as e:
        log.warning("对账降级: %s", e)
        return {}
    finally:
        conn.close()


def touch_opened(slug):
    conn = _safe_connect()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE projects SET last_opened_at=NOW() WHERE slug=%s", (slug,))
    except pymysql.MySQLError as e:
        log.warning("touch 降级: %s", e)
    finally:
        conn.close()


def delete_row(slug):
    conn = _safe_connect()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE slug=%s", (slug,))
    except pymysql.MySQLError as e:
        log.warning("删行降级: %s", e)
    finally:
        conn.close()


def _reset_for_test():
    """测试用：清 schema 缓存，让 env 变化重新生效"""
    global _schema_ready
    _schema_ready = False
