"""编译服务：latexmk 子进程 + SyncTeX 正反向定位。"""
from __future__ import annotations

import asyncio
import os
import signal
import shutil
import subprocess
import re
from pathlib import Path

COMPILE_TIMEOUT = 120  # 编译超时（秒）
LOG_TAIL_LINES = 600    # 返回给前端的日志行数
FORMAT_TIMEOUT = 20     # latexindent 超时（秒）
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".bmp", ".tif", ".tiff", ".svg"}
_BARE_IMAGE_RE = re.compile(
    r"^(?P<indent>\s*)(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:png|jpg|jpeg|pdf|eps|bmp|tif|tiff|svg))\s*$",
    re.IGNORECASE,
)
_CODE_ENVS = {"verbatim", "Verbatim", "lstlisting", "minted", "comment"}

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


def _prepare_graphic_aliases(proj: Path, main_file: str) -> list[Path]:
    """为子目录图片创建临时同名副本，使 \\includegraphics{a.jpg} 可以直接引用。"""
    main_dir = (proj / Path(main_file).parent).resolve()
    if not main_dir.is_relative_to(proj.resolve()):
        return []
    aliases: list[Path] = []
    for source in sorted(proj.rglob("*")):
        if (
            not source.is_file()
            or source.is_symlink()
            or ".git" in source.relative_to(proj).parts
            or source.suffix.lower() not in _IMAGE_EXTS
            or source.parent.resolve() == main_dir
        ):
            continue
        alias = main_dir / source.name
        if alias.exists():
            # 项目中已有同名文件时，遵守 LaTeX 原本的查找结果，不覆盖它。
            continue
        try:
            shutil.copy2(source, alias)
            aliases.append(alias)
        except OSError:
            # 单个图片无法建立临时映射时交给 LaTeX 报出具体缺图错误。
            continue
    return aliases


def _remove_graphic_aliases(aliases: list[Path]) -> None:
    for alias in aliases:
        try:
            alias.unlink()
        except OSError:
            pass


def _prepare_bare_image_references(proj: Path, main_file: str) -> list[tuple[Path, bytes]]:
    """把主文件中单独一行的图片名转换为 includegraphics，编译后恢复原文。"""
    main_path = (proj / main_file).resolve()
    if not main_path.is_file() or not main_path.is_relative_to(proj.resolve()):
        return []
    try:
        original_bytes = main_path.read_bytes()
        content = original_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    image_names = {
        p.name.casefold()
        for p in proj.rglob("*")
        if p.is_file() and not p.is_symlink()
        and ".git" not in p.relative_to(proj).parts
        and p.suffix.lower() in _IMAGE_EXTS
    }
    if not image_names:
        return []

    changed = False
    in_code = False
    in_math = False
    output: list[str] = []
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        begin = re.search(r"\\begin\{([^}]+)\}", stripped)
        end = re.search(r"\\end\{([^}]+)\}", stripped)
        if begin and begin.group(1) in _CODE_ENVS:
            in_code = True
        if end and end.group(1) in _CODE_ENVS:
            in_code = False
        if stripped.startswith(("%", "\\%")) or in_code or in_math:
            output.append(line)
            if stripped in {r"\]", "$$"}:
                in_math = False
            continue
        if stripped in {r"\[", "$$"}:
            in_math = True
            output.append(line)
            continue
        match = _BARE_IMAGE_RE.match(line.rstrip("\r\n"))
        if match and match.group("name").casefold() in image_names:
            ending = line[len(line.rstrip("\r\n")):]
            name = match.group("name")
            output.append(
                f"{match.group('indent')}\\includegraphics[width=0.8\\linewidth]{{{name}}}{ending}"
            )
            changed = True
        else:
            output.append(line)

    if not changed:
        return []
    rewritten = "".join(output)
    if not re.search(r"\\(?:usepackage|RequirePackage)(?:\[[^]]*\])?\{[^}]*\bgraphicx\b", rewritten):
        marker = re.search(r"^\\documentclass(?:\[[^]]*\])?\{[^}]+\}.*(?:\r?\n|$)", rewritten, re.M)
        if marker:
            rewritten = rewritten[:marker.end()] + "\\usepackage{graphicx}\n" + rewritten[marker.end():]
    try:
        with main_path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(rewritten)
    except OSError:
        return []
    return [(main_path, original_bytes)]


def _restore_source_files(files: list[tuple[Path, bytes]]) -> None:
    for path, content in files:
        try:
            path.write_bytes(content)
        except OSError:
            pass


async def compile_project(slug: str, proj: Path, main_file: str) -> dict:
    """编译项目，返回 {success, log, pdf, returncode, seconds, timed_out}。"""
    async with _lock_for(slug):
        pdf = pdf_path(proj, main_file)
        aliases = _prepare_graphic_aliases(proj, main_file)
        rewritten_sources = _prepare_bare_image_references(proj, main_file)
        cmd = [
            # -xelatex 必须在其他引擎选项之后、且不能再跟 -pdf（后者会覆盖回 pdflatex）
            "latexmk", "-xelatex", "-g",
            "-latexoption=-interaction=nonstopmode",
            "-latexoption=-file-line-error",
            "-latexoption=-synctex=1",
            main_file,
        ]
        started = asyncio.get_event_loop().time()
        try:
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
        finally:
            _restore_source_files(rewritten_sources)
            _remove_graphic_aliases(aliases)


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
