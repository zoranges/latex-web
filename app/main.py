"""LaTeX Web —— 轻量在线 LaTeX 编辑器后端（单用户）。"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import compile as compile_mod
from . import storage

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"

app = FastAPI(title="LaTeX Web")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def no_cache_app_code(request, call_next):
    """自己的代码（index/app.js/style.css）禁缓存，vendor 大库走正常缓存。"""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or (path.startswith("/static") and not path.startswith("/static/vendor")):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def api_health():
    return {"ok": True}


# ---------- 请求体模型 ----------

class CreateProject(BaseModel):
    name: str
    template: str = "article"


class FileBody(BaseModel):
    content: str


class RenameBody(BaseModel):
    old: str
    new: str


class MainFileBody(BaseModel):
    main_file: str


class SyncForwardBody(BaseModel):
    file: str
    line: int
    col: int = 0


class SyncBackwardBody(BaseModel):
    page: int
    x: float
    y: float


class FormatBody(BaseModel):
    content: str


def _err(e: Exception) -> HTTPException:
    if isinstance(e, FileNotFoundError):
        return HTTPException(404, str(e))
    return HTTPException(400, str(e))


# ---------- 模板 ----------

@app.get("/api/templates")
def api_templates():
    from .templates import TEMPLATES

    return [
        {"id": t["id"], "name": t["name"], "desc": t["desc"], "files": list(t["files"])}
        for t in TEMPLATES
    ]


# ---------- 项目 ----------

@app.get("/api/projects")
def api_projects():
    return storage.list_projects()


@app.post("/api/projects")
def api_create_project(body: CreateProject):
    if not body.name.strip():
        raise HTTPException(400, "项目名不能为空")
    return storage.create_project(body.name, body.template)


@app.delete("/api/projects/{slug}")
def api_delete_project(slug: str):
    try:
        storage.delete_project(slug)
    except Exception as e:
        raise _err(e)
    return {"ok": True}


@app.put("/api/projects/{slug}/main")
def api_set_main(slug: str, body: MainFileBody):
    try:
        storage.set_main_file(slug, body.main_file)
    except Exception as e:
        raise _err(e)
    return {"ok": True}


# ---------- 文件 ----------

@app.get("/api/projects/{slug}/files")
def api_files(slug: str):
    try:
        return storage.list_files(slug)
    except Exception as e:
        raise _err(e)


@app.get("/api/projects/{slug}/file")
def api_read_file(slug: str, path: str):
    try:
        return {"content": storage.read_file(slug, path)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise _err(e)


@app.put("/api/projects/{slug}/file")
def api_write_file(slug: str, path: str, body: FileBody):
    try:
        storage.write_file(slug, path, body.content)
    except Exception as e:
        raise _err(e)
    return {"ok": True}


@app.delete("/api/projects/{slug}/file")
def api_delete_file(slug: str, path: str):
    try:
        storage.delete_file(slug, path)
    except Exception as e:
        raise _err(e)
    return {"ok": True}


@app.post("/api/projects/{slug}/rename")
def api_rename_file(slug: str, body: RenameBody):
    try:
        storage.rename_file(slug, body.old, body.new)
    except Exception as e:
        raise _err(e)
    return {"ok": True}


@app.get("/api/projects/{slug}/file-raw")
def api_raw_file(slug: str, path: str):
    try:
        p = storage.resolve_file(slug, path)
    except Exception as e:
        raise _err(e)
    if not p.is_file():
        raise HTTPException(404, "文件不存在")
    mt = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return FileResponse(p, media_type=mt, headers={"Cache-Control": "no-store"})


@app.post("/api/projects/{slug}/upload")
async def api_upload(slug: str, file: UploadFile = File(...), subdir: str = Form("")):
    data = await file.read()
    try:
        rel = storage.save_upload(slug, subdir, file.filename or "upload.bin", data)
    except Exception as e:
        raise _err(e)
    return {"path": rel}


# ---------- 编译与 SyncTeX ----------

@app.post("/api/projects/{slug}/compile")
async def api_compile(slug: str):
    try:
        meta = storage.get_project(slug)
        proj = storage._proj_dir(slug)
    except Exception as e:
        raise _err(e)
    return await compile_mod.compile_project(slug, proj, meta["main_file"])


def _pdf_response(slug: str, download: bool = False):
    try:
        meta = storage.get_project(slug)
        proj = storage._proj_dir(slug)
        pdf = compile_mod.pdf_path(proj, meta["main_file"])
    except Exception as e:
        raise _err(e)
    if not pdf.is_file():
        raise HTTPException(404, "尚未编译出 PDF")
    headers = {"Cache-Control": "no-store"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{pdf.name}"'
    return FileResponse(pdf, media_type="application/pdf", headers=headers)


@app.get("/api/projects/{slug}/pdf")
def api_pdf(slug: str):
    return _pdf_response(slug)


@app.get("/api/projects/{slug}/download-pdf")
def api_download_pdf(slug: str):
    return _pdf_response(slug, download=True)


@app.post("/api/projects/{slug}/sync-forward")
def api_sync_forward(slug: str, body: SyncForwardBody):
    try:
        meta = storage.get_project(slug)
        proj = storage._proj_dir(slug)
        result = compile_mod.sync_forward(
            proj, meta["main_file"], body.file, body.line, body.col
        )
    except Exception as e:
        raise _err(e)
    if result is None:
        raise HTTPException(404, "定位失败：可能尚未编译，或该行未出现在 PDF 中")
    return result


@app.post("/api/projects/{slug}/sync-backward")
def api_sync_backward(slug: str, body: SyncBackwardBody):
    try:
        meta = storage.get_project(slug)
        proj = storage._proj_dir(slug)
        result = compile_mod.sync_backward(
            proj, meta["main_file"], body.page, body.x, body.y
        )
    except Exception as e:
        raise _err(e)
    if result is None:
        raise HTTPException(404, "定位失败：PDF 中该位置没有对应的源码")
    return result


@app.get("/api/projects/{slug}/labels")
def api_labels(slug: str):
    r"""\ref / \cite 补全数据：.aux 中的标签 + .bib 中的条目 key。"""
    try:
        return storage.collect_ref_data(slug)
    except Exception as e:
        raise _err(e)


@app.post("/api/projects/{slug}/format")
async def api_format(slug: str, body: FormatBody):
    """latexindent 格式化（无副作用，不写项目目录，由前端决定是否保存结果）。"""
    try:
        storage._proj_dir(slug)  # 校验项目存在
    except Exception as e:
        raise _err(e)
    try:
        formatted = await compile_mod.format_content(body.content)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"content": formatted}


# ---------- 历史版本 ----------

@app.get("/api/projects/{slug}/history")
def api_history(slug: str):
    try:
        return storage.history(slug)
    except Exception as e:
        raise _err(e)


@app.get("/api/projects/{slug}/history/{sha}")
def api_commit_diff(slug: str, sha: str):
    try:
        return {"diff": storage.commit_diff(slug, sha)}
    except Exception as e:
        raise _err(e)


@app.post("/api/projects/{slug}/history/{sha}/restore")
def api_restore_commit(slug: str, sha: str):
    try:
        storage.restore_commit(slug, sha)
    except Exception as e:
        raise _err(e)
    return {"ok": True}
