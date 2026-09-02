"""项目与文件存储：文件系统 + git 版本控制 + SQLite 元数据。"""
from __future__ import annotations

import os
import re
import secrets
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROJECTS_DIR = DATA_DIR / "projects"
DB_PATH = DATA_DIR / "meta.db"

_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# 编译产物，不在文件树中显示（PDF 通过预览/下载按钮获取）
_ARTIFACT_EXTS = {
    ".aux", ".bbl", ".bcf", ".blg", ".fdb_latexmk", ".fls", ".idx", ".ilg",
    ".ind", ".lof", ".log", ".lol", ".lot", ".nav", ".out", ".pdf",
    ".run.xml", ".snm", ".synctex.gz", ".thm", ".toc", ".vrb", ".xdv",
}

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
               id            INTEGER PRIMARY KEY AUTOINCREMENT,
               username      TEXT NOT NULL COLLATE NOCASE UNIQUE,
               password_hash TEXT NOT NULL,
               created_at    TEXT NOT NULL
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
               token_hash TEXT PRIMARY KEY,
               user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               created_at INTEGER NOT NULL,
               expires_at INTEGER NOT NULL
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS projects (
               slug       TEXT PRIMARY KEY,
               name       TEXT NOT NULL,
               main_file  TEXT NOT NULL DEFAULT 'main.tex',
               created_at TEXT NOT NULL,
               user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE
           )"""
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    if "user_id" not in columns:
        # 兼容旧版单用户数据库；首次注册时再把这些项目交给首个用户。
        conn.execute("ALTER TABLE projects ADD COLUMN user_id INTEGER REFERENCES users(id)")
    conn.commit()
    return conn


# ---------- 用户与会话 ----------

def create_user(username: str, password_hash: str) -> dict:
    conn = _connect()
    try:
        first_user = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        now = _now()
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?,?,?)",
                (username, password_hash, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError("用户名已存在")
        user_id = int(cur.lastrowid)
        if first_user:
            # 保留升级前单用户实例中的项目，避免升级后历史数据消失。
            conn.execute("UPDATE projects SET user_id = ? WHERE user_id IS NULL", (user_id,))
        conn.commit()
        return {"id": user_id, "username": username, "created_at": now}
    finally:
        conn.close()


def find_user_by_username(username: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, username, password_hash, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {"id": row[0], "username": row[1], "password_hash": row[2], "created_at": row[3]}


def find_user_by_id(user_id: int) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, username, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {"id": row[0], "username": row[1], "created_at": row[2]}


def create_session(token_hash: str, user_id: int, created_at: int, expires_at: int) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (token_hash, user_id, created_at, expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def find_user_by_session(token_hash: str, now: int) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            """SELECT u.id, u.username, u.created_at
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ?""",
            (token_hash, now),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {"id": row[0], "username": row[1], "created_at": row[2]}


def delete_session(token_hash: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        conn.commit()
    finally:
        conn.close()


def purge_expired_sessions(now: int) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.commit()
    finally:
        conn.close()


def _git(proj: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=proj, capture_output=True, text=True, check=check,
        encoding="utf-8", errors="replace",  # git 输出按 UTF-8 解码，避免 GBK  locale 下中文提交信息解码崩溃
    )


def _commit(proj: Path, message: str) -> bool:
    """提交所有变更；无变更时返回 False。"""
    _git(proj, "add", "-A")
    r = _git(proj, "commit", "-m", message, check=False)
    return r.returncode == 0


def _make_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-").lower()
    if not slug:  # 纯中文/无 ASCII 字符时用随机后缀保证唯一
        slug = f"project-{secrets.token_hex(3)}"
    base, i = slug, 2
    while (PROJECTS_DIR / slug).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


def _proj_dir(slug: str) -> Path:
    if not _SLUG_RE.match(slug):
        raise ValueError("非法项目标识")
    p = PROJECTS_DIR / slug
    if not p.is_dir():
        raise FileNotFoundError("项目不存在")
    return p


def _safe(proj: Path, rel: str) -> Path:
    """把项目内相对路径解析为绝对路径，防止路径穿越。"""
    p = (proj / rel).resolve()
    if not p.is_relative_to(proj):
        raise ValueError("非法路径")
    return p


def resolve_file(slug: str, path: str, user_id: int) -> Path:
    get_project(slug, user_id)
    return _safe(_proj_dir(slug), path)


# ---------- 项目 ----------

def list_projects(user_id: int) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT slug, name, main_file, created_at
               FROM projects WHERE user_id = ? ORDER BY created_at DESC""",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"slug": r[0], "name": r[1], "main_file": r[2], "created_at": r[3]}
        for r in rows
        if (PROJECTS_DIR / r[0]).is_dir()
    ]


def get_project(slug: str, user_id: int) -> dict:
    conn = _connect()
    try:
        row = conn.execute(
            """SELECT slug, name, main_file, created_at
               FROM projects WHERE slug = ? AND user_id = ?""",
            (slug, user_id),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise FileNotFoundError("项目不存在")
    return {"slug": row[0], "name": row[1], "main_file": row[2], "created_at": row[3]}


def create_project(name: str, template_id: str, user_id: int) -> dict:
    from .templates import get_template

    tpl = get_template(template_id)
    slug = _make_slug(name)
    proj = PROJECTS_DIR / slug
    proj.mkdir(parents=True)
    for rel, content in tpl["files"].items():
        p = _safe(proj, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    main_file = tpl["main"]
    _git(proj, "init", "-q", "-b", "main")
    _git(proj, "config", "user.name", "latex-web")
    _git(proj, "config", "user.email", "latex-web@localhost")
    _commit(proj, f"初始提交（模板：{tpl['name']}）")
    now = _now()
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO projects
               (slug, name, main_file, created_at, user_id) VALUES (?,?,?,?,?)""",
            (slug, name.strip(), main_file, now, user_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"slug": slug, "name": name.strip(), "main_file": main_file, "created_at": now}


def _rm_readonly(func, path, exc_info):
    """Windows 上 git 对象文件是只读的，清除只读属性后重试删除。"""
    import stat

    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def delete_project(slug: str, user_id: int) -> None:
    get_project(slug, user_id)
    shutil.rmtree(PROJECTS_DIR / slug, onerror=_rm_readonly)
    conn = _connect()
    try:
        conn.execute("DELETE FROM projects WHERE slug = ? AND user_id = ?", (slug, user_id))
        conn.commit()
    finally:
        conn.close()


def set_main_file(slug: str, main_file: str, user_id: int) -> None:
    get_project(slug, user_id)
    proj = _proj_dir(slug)
    if not _safe(proj, main_file).is_file():
        raise FileNotFoundError("主文件不存在")
    conn = _connect()
    try:
        conn.execute(
            "UPDATE projects SET main_file = ? WHERE slug = ? AND user_id = ?",
            (main_file, slug, user_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------- 文件 ----------

def list_files(slug: str, user_id: int) -> list[dict]:
    get_project(slug, user_id)
    proj = _proj_dir(slug)
    items = []
    for p in sorted(proj.rglob("*")):
        if p.is_dir():
            continue
        rel = p.relative_to(proj)
        if ".git" in rel.parts or any(p.name.endswith(ext) for ext in _ARTIFACT_EXTS):
            continue
        st = p.stat()
        items.append({"path": rel.as_posix(), "size": st.st_size, "mtime": st.st_mtime})
    return items


# ---------- 补全数据（\ref / \cite） ----------

_NEWLABEL_RE = re.compile(r"\\newlabel\{([^}]*)\}")
_BIBENTRY_RE = re.compile(r"^\s*@(\w+)\{\s*([^,\s{}]+)\s*,", re.M)


def collect_ref_data(slug: str, user_id: int) -> dict:
    """从 .aux 收集 \\newlabel 标签名、从 .bib 收集文献条目 key，供编辑器补全。"""
    get_project(slug, user_id)
    proj = _proj_dir(slug)
    labels: list[str] = []
    seen: set[str] = set()
    for aux in sorted(proj.rglob("*.aux")):
        try:
            text = aux.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name in _NEWLABEL_RE.findall(text):
            if name and name not in seen:
                seen.add(name)
                labels.append(name)
    bibkeys: list[str] = []
    seen_b: set[str] = set()
    for bib in sorted(proj.rglob("*.bib")):
        try:
            text = bib.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for _type, key in _BIBENTRY_RE.findall(text):
            if key not in seen_b:
                seen_b.add(key)
                bibkeys.append(key)
    return {"labels": labels[:500], "bibkeys": bibkeys[:500]}


def read_file(slug: str, path: str, user_id: int) -> str:
    p = resolve_file(slug, path, user_id)
    if not p.is_file():
        raise FileNotFoundError("文件不存在")
    data = p.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("二进制文件无法在编辑器中打开")


def write_file(slug: str, path: str, content: str, user_id: int) -> None:
    get_project(slug, user_id)
    proj = _proj_dir(slug)
    p = _safe(proj, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # 浏览器或外部编辑器复制长文本时，偶尔会把换行写成垂直制表符/换页符。
    # 这两类控制字符会被 XeLaTeX 当成非法字符，统一恢复为普通换行。
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = content.replace("\x0b", "\n").replace("\x0c", "\n")
    p.write_text(content, encoding="utf-8")
    _commit(proj, f"更新 {path}")


def delete_file(slug: str, path: str, user_id: int) -> None:
    get_project(slug, user_id)
    proj = _proj_dir(slug)
    p = _safe(proj, path)
    if not p.is_file():
        raise FileNotFoundError("文件不存在")
    p.unlink()
    _commit(proj, f"删除 {path}")


def rename_file(slug: str, old: str, new: str, user_id: int) -> None:
    get_project(slug, user_id)
    proj = _proj_dir(slug)
    src = _safe(proj, old)
    dst = _safe(proj, new)
    if not src.is_file():
        raise FileNotFoundError("文件不存在")
    if dst.exists():
        raise ValueError("目标文件已存在")
    dst.parent.mkdir(parents=True, exist_ok=True)
    _git(proj, "mv", old, new)
    _commit(proj, f"重命名 {old} → {new}")


def save_upload(slug: str, subdir: str, filename: str, data: bytes, user_id: int) -> str:
    """保存上传文件，返回项目内相对路径。"""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("上传文件不能超过 50 MB")
    get_project(slug, user_id)
    proj = _proj_dir(slug)
    filename = Path(filename.replace("\\", "/")).name or "upload.bin"
    rel = f"{subdir.strip('/')}/{filename}" if subdir.strip("/") else filename
    target = _safe(proj, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    _commit(proj, f"上传 {target.relative_to(proj).as_posix()}")
    return target.relative_to(proj).as_posix()


# ---------- 历史版本 ----------

def history(slug: str, user_id: int, limit: int = 200) -> list[dict]:
    get_project(slug, user_id)
    proj = _proj_dir(slug)
    r = _git(
        proj, "log", "--pretty=format:%H%x1f%h%x1f%ad%x1f%s",
        "--date=format:%Y-%m-%d %H:%M", f"-n{limit}",
    )
    commits = []
    for line in r.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            commits.append(
                {"sha": parts[0], "short": parts[1], "date": parts[2], "message": parts[3]}
            )
    return commits


def commit_diff(slug: str, sha: str, user_id: int) -> str:
    get_project(slug, user_id)
    proj = _proj_dir(slug)
    try:
        r = _git(
            proj, "show", "--stat", "--patch",
            "--format=commit %h%nDate: %ad%n    %s",
            "--date=format:%Y-%m-%d %H:%M", sha,
        )
    except subprocess.CalledProcessError:
        raise ValueError("提交不存在")
    return r.stdout[:300_000]


def restore_commit(slug: str, sha: str, user_id: int) -> None:
    get_project(slug, user_id)
    proj = _proj_dir(slug)
    try:
        _git(proj, "checkout", "-q", sha, "--", ".")
    except subprocess.CalledProcessError:
        raise ValueError("提交不存在")
    _commit(proj, f"恢复到 {sha[:8]}")
