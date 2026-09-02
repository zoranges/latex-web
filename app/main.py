"""LaTeX Web —— 轻量在线 LaTeX 编辑器后端。"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai as ai_mod
from . import auth
from . import compile as compile_mod
from . import storage

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"

app = FastAPI(title="LaTeX Web")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def require_login_for_api(request: Request, call_next):
    """所有项目、模板和 AI 接口统一要求登录，静态页面和认证接口保持公开。"""
    path = request.url.path
    protected = (
        path == "/api/templates"
        or path.startswith("/api/projects")
        or path.startswith("/api/ai/")
    )
    if protected and auth.current_user(request) is None:
        return JSONResponse({"detail": "请先登录"}, status_code=401)
    return await call_next(request)


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


class AuthBody(BaseModel):
    username: str
    password: str


# ---------- 账号 ----------

@app.get("/api/auth/me")
def api_auth_me(request: Request):
    user = auth.current_user(request)
    if user is None:
        return {"authenticated": False, "user": None}
    return {"authenticated": True, "user": user}


@app.post("/api/auth/register")
def api_auth_register(body: AuthBody, response: Response):
    try:
        user = auth.register(body.username, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    auth.start_session(response, user["id"])
    return {"authenticated": True, "user": user}


@app.post("/api/auth/login")
def api_auth_login(body: AuthBody, response: Response):
    try:
        user = auth.authenticate(body.username, body.password)
    except ValueError as e:
        raise HTTPException(401, str(e))
    auth.start_session(response, user["id"])
    return {"authenticated": True, "user": user}


@app.post("/api/auth/logout")
def api_auth_logout(request: Request, response: Response):
    auth.end_session(request, response)
    return {"authenticated": False}


def _require_user(request: Request) -> dict:
    try:
        return auth.require_user(request)
    except PermissionError as e:
        raise HTTPException(401, str(e))


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


class AIAnalyzeBody(BaseModel):
    path: str
    style: str = "general"
    instruction: str = ""
    start_line: int | None = None
    end_line: int | None = None


class AIApplyBody(BaseModel):
    path: str
    content: str
    compile: bool = True
    start_line: int | None = None
    end_line: int | None = None
    original: str = ""


def _err(e: Exception) -> HTTPException:
    if isinstance(e, HTTPException):
        return e
    if isinstance(e, FileNotFoundError):
        return HTTPException(404, str(e))
    return HTTPException(400, str(e))


# ---------- 模板 ----------

@app.get("/api/templates")
def api_templates(request: Request):
    _require_user(request)
    from .templates import TEMPLATES

    return [
        {"id": t["id"], "name": t["name"], "desc": t["desc"], "files": list(t["files"])}
        for t in TEMPLATES
    ]


# ---------- 项目 ----------

@app.get("/api/projects")
def api_projects(request: Request):
    user = _require_user(request)
    return storage.list_projects(user["id"])


@app.post("/api/projects")
def api_create_project(body: CreateProject, request: Request):
    if not body.name.strip():
        raise HTTPException(400, "项目名不能为空")
    user = _require_user(request)
    return storage.create_project(body.name, body.template, user["id"])


@app.delete("/api/projects/{slug}")
def api_delete_project(slug: str, request: Request):
    try:
        user = _require_user(request)
        storage.delete_project(slug, user["id"])
    except Exception as e:
        raise _err(e)
    return {"ok": True}


@app.put("/api/projects/{slug}/main")
def api_set_main(slug: str, body: MainFileBody, request: Request):
    try:
        user = _require_user(request)
        storage.set_main_file(slug, body.main_file, user["id"])
    except Exception as e:
        raise _err(e)
    return {"ok": True}


# ---------- 文件 ----------

@app.get("/api/projects/{slug}/files")
def api_files(slug: str, request: Request):
    try:
        user = _require_user(request)
        return storage.list_files(slug, user["id"])
    except Exception as e:
        raise _err(e)


@app.get("/api/projects/{slug}/file")
def api_read_file(slug: str, path: str, request: Request):
    try:
        user = _require_user(request)
        return {"content": storage.read_file(slug, path, user["id"])}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise _err(e)


@app.put("/api/projects/{slug}/file")
def api_write_file(slug: str, path: str, body: FileBody, request: Request):
    try:
        user = _require_user(request)
        storage.write_file(slug, path, body.content, user["id"])
    except Exception as e:
        raise _err(e)
    return {"ok": True}


@app.delete("/api/projects/{slug}/file")
def api_delete_file(slug: str, path: str, request: Request):
    try:
        user = _require_user(request)
        storage.delete_file(slug, path, user["id"])
    except Exception as e:
        raise _err(e)
    return {"ok": True}


@app.post("/api/projects/{slug}/rename")
def api_rename_file(slug: str, body: RenameBody, request: Request):
    try:
        user = _require_user(request)
        storage.rename_file(slug, body.old, body.new, user["id"])
    except Exception as e:
        raise _err(e)
    return {"ok": True}


@app.get("/api/projects/{slug}/file-raw")
def api_raw_file(slug: str, path: str, request: Request):
    try:
        user = _require_user(request)
        p = storage.resolve_file(slug, path, user["id"])
    except Exception as e:
        raise _err(e)
    if not p.is_file():
        raise HTTPException(404, "文件不存在")
    mt = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return FileResponse(p, media_type=mt, headers={"Cache-Control": "no-store"})


@app.post("/api/projects/{slug}/upload")
async def api_upload(
    slug: str, request: Request, file: UploadFile = File(...), subdir: str = Form("")
):
    try:
        user = _require_user(request)
        data = await file.read(storage.MAX_UPLOAD_BYTES + 1)
        rel = storage.save_upload(
            slug, subdir, file.filename or "upload.bin", data, user["id"]
        )
    except Exception as e:
        raise _err(e)
    return {"path": rel}


# ---------- 编译与 SyncTeX ----------

@app.post("/api/projects/{slug}/compile")
async def api_compile(slug: str, request: Request):
    try:
        user = _require_user(request)
        meta = storage.get_project(slug, user["id"])
        proj = storage._proj_dir(slug)
    except Exception as e:
        raise _err(e)
    return await compile_mod.compile_project(slug, proj, meta["main_file"])


def _pdf_response(slug: str, request: Request, download: bool = False):
    try:
        user = _require_user(request)
        meta = storage.get_project(slug, user["id"])
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
def api_pdf(slug: str, request: Request):
    return _pdf_response(slug, request)


@app.get("/api/projects/{slug}/download-pdf")
def api_download_pdf(slug: str, request: Request):
    return _pdf_response(slug, request, download=True)


@app.post("/api/projects/{slug}/sync-forward")
def api_sync_forward(slug: str, body: SyncForwardBody, request: Request):
    try:
        user = _require_user(request)
        meta = storage.get_project(slug, user["id"])
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
def api_sync_backward(slug: str, body: SyncBackwardBody, request: Request):
    try:
        user = _require_user(request)
        meta = storage.get_project(slug, user["id"])
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
def api_labels(slug: str, request: Request):
    r"""\ref / \cite 补全数据：.aux 中的标签 + .bib 中的条目 key。"""
    try:
        user = _require_user(request)
        return storage.collect_ref_data(slug, user["id"])
    except Exception as e:
        raise _err(e)


@app.post("/api/projects/{slug}/format")
async def api_format(slug: str, body: FormatBody, request: Request):
    """latexindent 格式化（无副作用，不写项目目录，由前端决定是否保存结果）。"""
    try:
        user = _require_user(request)
        storage.get_project(slug, user["id"])
    except Exception as e:
        raise _err(e)
    try:
        formatted = await compile_mod.format_content(body.content)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"content": formatted}


# ---------- AI 排版 ----------

@app.get("/api/ai/config")
def api_ai_config(request: Request):
    """AI 服务配置状态（不含 Key 本身）。"""
    _require_user(request)
    return ai_mod.describe()


@app.get("/api/ai/styles")
def api_ai_styles(request: Request):
    """可选的排版标准列表。"""
    _require_user(request)
    return [{"id": k, "name": v["name"]} for k, v in ai_mod.STYLES.items()]


@app.post("/api/projects/{slug}/ai/analyze")
async def api_ai_analyze(slug: str, body: AIAnalyzeBody, request: Request):
    """阶段 1：分析排版问题（全文或选区），返回说明 + 新内容 + diff（不写盘）。"""
    selection = None
    if body.start_line is not None and body.end_line is not None:
        selection = (body.start_line, body.end_line)
    try:
        user = _require_user(request)
        return await ai_mod.analyze(
            slug, body.path, body.style, selection, body.instruction, user["id"]
        )
    except ai_mod.AIError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise _err(e)


@app.post("/api/projects/{slug}/ai/apply")
async def api_ai_apply(slug: str, body: AIApplyBody, request: Request):
    """阶段 2：应用排版结果（全文或选区，自动提交 + 编译自愈，失败回滚）。"""
    try:
        user = _require_user(request)
        if body.start_line is not None and body.end_line is not None:
            return await ai_mod.apply_selection(
                slug, body.path, body.start_line, body.end_line,
                body.original, body.content, body.compile, user["id"],
            )
        return await ai_mod.apply(slug, body.path, body.content, body.compile, user["id"])
    except ai_mod.AIConflictError as e:
        raise HTTPException(409, str(e))
    except ai_mod.AIError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise _err(e)


# ---------- 历史版本 ----------

@app.get("/api/projects/{slug}/history")
def api_history(slug: str, request: Request):
    try:
        user = _require_user(request)
        return storage.history(slug, user["id"])
    except Exception as e:
        raise _err(e)


@app.get("/api/projects/{slug}/history/{sha}")
def api_commit_diff(slug: str, sha: str, request: Request):
    try:
        user = _require_user(request)
        return {"diff": storage.commit_diff(slug, sha, user["id"])}
    except Exception as e:
        raise _err(e)


@app.post("/api/projects/{slug}/history/{sha}/restore")
def api_restore_commit(slug: str, sha: str, request: Request):
    try:
        user = _require_user(request)
        storage.restore_commit(slug, sha, user["id"])
    except Exception as e:
        raise _err(e)
    return {"ok": True}
