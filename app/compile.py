"""编译服务：latexmk 子进程 + SyncTeX 正反向定位。"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from pathlib import Path

COMPILE_TIMEOUT = 120  # 编译超时（秒）
LOG_TAIL_LINES = 600    # 返回给前端的日志行数
FORMAT_TIMEOUT = 20     # latexindent 超时（秒）

_locks: dict[str, asyncio.Lock] = {}


def _lock_for(slug: str) -> asyncio.Lock:
    """每个项目一把锁，串行化同一项目的编译。"""
    lock = _locks.get(slug)
    if lock is None:
        lock = _locks[slug] = asyncio.Lock()
    return lock


def pdf_path(proj: Path, main_file: str) -> Path:
    stem = main_file[:-4] if main_file.endswith(".tex") else main_file
    return proj / f"{stem}.pdf"


async def compile_project(slug: str, proj: Path, main_file: str) -> dict:
    """编译项目，返回 {success, log, pdf, returncode, seconds, timed_out}。"""
    async with _lock_for(slug):
        pdf = pdf_path(proj, main_file)
        cmd = [
            # -xelatex 必须在其他引擎选项之后、且不能再跟 -pdf（后者会覆盖回 pdflatex）
            "latexmk", "-xelatex", "-g",
            "-latexoption=-interaction=nonstopmode",
            "-latexoption=-file-line-error",
            "-latexoption=-synctex=1",
            main_file,
        ]
        started = asyncio.get_event_loop().time()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=proj,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=COMPILE_TIMEOUT)
            timed_out = False
        except asyncio.TimeoutError:
            timed_out = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, _ = await proc.communicate()

        log = stdout.decode("utf-8", errors="replace")
        elapsed = asyncio.get_event_loop().time() - started
        success = (not timed_out) and proc.returncode == 0 and pdf.is_file()
        return {
            "success": success,
            "log": "\n".join(log.splitlines()[-LOG_TAIL_LINES:]),
            "pdf": pdf.name,
            "returncode": proc.returncode,
            "seconds": round(elapsed, 1),
            "timed_out": timed_out,
        }


async def format_content(content: str) -> str:
    """用 latexindent 格式化 LaTeX 源码；失败时抛 RuntimeError。"""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="latexweb-fmt-") as td:
        src = Path(td) / "input.tex"
        src.write_text(content, encoding="utf-8")
        # cwd 放临时目录：latexindent 会在工作目录写 indent.log 等副产品
        try:
            proc = await asyncio.create_subprocess_exec(
                "latexindent", "-stdout", "-g", str(Path(td) / "indent.log"), src.name,
                cwd=td,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=FORMAT_TIMEOUT)
        except FileNotFoundError:
            raise RuntimeError("latexindent 不可用")
        except asyncio.TimeoutError:
            raise RuntimeError("格式化超时")
        if proc.returncode != 0:
            msg = stderr.decode("utf-8", errors="replace").strip()[-300:]
            raise RuntimeError("latexindent 失败: " + (msg or f"exit {proc.returncode}"))
        formatted = stdout.decode("utf-8", errors="replace")
    return formatted if formatted.strip() else content


def sync_forward(proj: Path, main_file: str, file: str, line: int, col: int = 0) -> dict | None:
    """正向定位：源文件行号 → PDF 页码与坐标（PDF 坐标系，原点左下）。"""
    pdf = pdf_path(proj, main_file)
    if not pdf.is_file():
        return None
    r = subprocess.run(
        ["synctex", "view", "-i", f"{line}:{col}:{file}", "-o", pdf.name],
        cwd=proj, capture_output=True, text=True,
    )
    page = x = y = None
    for ln in r.stdout.splitlines():
        if ln.startswith("Page:"):
            try:
                page = int(ln.split(":", 1)[1])
            except ValueError:
                pass
        elif ln.startswith("x:"):
            try:
                x = float(ln.split(":", 1)[1])
            except ValueError:
                pass
        elif ln.startswith("y:"):
            try:
                y = float(ln.split(":", 1)[1])
            except ValueError:
                pass
    if page is None:
        return None
    return {"page": page, "x": x, "y": y}


def sync_backward(proj: Path, main_file: str, page: int, x: float, y: float) -> dict | None:
    """反向定位：PDF 页码与坐标 → 源文件与行列。"""
    pdf = pdf_path(proj, main_file)
    if not pdf.is_file():
        return None
    r = subprocess.run(
        ["synctex", "edit", "-o", f"{page}:{x}:{y}:{pdf.name}"],
        cwd=proj, capture_output=True, text=True,
    )
    file = line = col = None
    for ln in r.stdout.splitlines():
        # edit 模式结果中 Output: 是查询回显，真正的源码在 Input: 字段
        if ln.startswith("Input:") and file is None:
            file = ln.split(":", 1)[1].strip()
        elif ln.startswith("Line:") and line is None:
            try:
                line = int(ln.split(":", 1)[1])
            except ValueError:
                pass
        elif ln.startswith("Column:") and col is None:
            try:
                col = int(ln.split(":", 1)[1])
            except ValueError:
                pass
    if not file:
        return None
    # 转为项目内相对路径
    try:
        rel = Path(file).resolve().relative_to(proj.resolve()).as_posix()
    except ValueError:
        rel = Path(file).name
    return {"file": rel, "line": line, "col": col}
