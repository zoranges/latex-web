"""AI 排版服务：调用 OpenAI 兼容大模型 API（默认 DeepSeek）分析并修正 LaTeX 排版。

流程分两阶段（由 main.py 的两个端点驱动，中间有人工 diff 确认）：

1. analyze —— LLM 读源码，返回排版说明 + 排版后的完整新内容（附 unified diff）
2. apply   —— 写入新内容（storage 自动 git 提交）→ latexmk 编译
              → 编译失败则把错误日志喂回 LLM 修复（最多 MAX_REPAIR_ROUNDS 轮）
              → 仍失败则回滚到 AI 修改前的提交

模型配置（环境变量，均可省略走默认值）：
    DEEPSEEK_API_KEY / AI_API_KEY   —— API Key（也可写入 data/ai_key 文件）
    AI_BASE_URL / DEEPSEEK_BASE_URL —— OpenAI 兼容端点（默认 DeepSeek）
    AI_MODEL / DEEPSEEK_MODEL       —— 模型名（默认 deepseek-chat）
"""
from __future__ import annotations

import difflib
import json
import os
import re
from pathlib import Path

import httpx

from . import compile as compile_mod
from . import storage

BASE_DIR = Path(__file__).resolve().parent.parent
KEY_FILE = BASE_DIR / "data" / "ai_key"

API_TIMEOUT = 180.0       # 单次模型调用超时（秒）
MAX_REPAIR_ROUNDS = 2     # 编译失败后最多让 LLM 修复的轮数
MAX_ANALYZE_CHARS = 100_000  # 超过此长度的文件不做整体分析


class AIError(RuntimeError):
    """AI 服务相关错误（配置缺失、网络、模型返回异常）。"""


# ---------- 配置 ----------

def resolve_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("AI_API_KEY")
    if key and key.strip():
        return key.strip()
    if KEY_FILE.is_file():
        k = KEY_FILE.read_text(encoding="utf-8").strip()
        if k:
            return k
    raise AIError("未配置 AI API Key：请设置环境变量 DEEPSEEK_API_KEY 或在 data/ai_key 文件中写入 Key")


def _provider() -> tuple[str, str]:
    base = (
        os.environ.get("AI_BASE_URL")
        or os.environ.get("DEEPSEEK_BASE_URL")
        or "https://api.deepseek.com"
    )
    model = (
        os.environ.get("AI_MODEL")
        or os.environ.get("DEEPSEEK_MODEL")
        or "deepseek-chat"
    )
    return base.rstrip("/"), model


def describe() -> dict:
    """前端展示用：AI 是否已配置（不泄露 Key）。"""
    try:
        resolve_key()
        configured = True
    except AIError:
        configured = False
    base, model = _provider()
    return {"configured": configured, "base": base, "model": model}


# ---------- 模型调用 ----------

def _is_loopback(base: str) -> bool:
    """本地/回环地址的 AI 网关（如 ollama、mock）不应走系统代理。"""
    try:
        from urllib.parse import urlparse
        host = (urlparse(base).hostname or "").lower()
        return host in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
    except ValueError:
        return False


async def _chat(messages: list[dict], json_mode: bool = True) -> str:
    base, model = _provider()
    key = resolve_key()
    body: dict = {"model": model, "messages": messages, "temperature": 0.2}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        # trust_env=False 对回环地址直连，避免系统代理（如 Clash）拦截本地网关返回 502
        async with httpx.AsyncClient(
            timeout=API_TIMEOUT, trust_env=not _is_loopback(base)
        ) as client:
            r = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=body,
            )
    except httpx.HTTPError as e:
        raise AIError(f"连接 AI 服务失败: {e}")
    if r.status_code in (401, 403):
        raise AIError(f"AI API Key 无效（HTTP {r.status_code}），请检查配置")
    if r.status_code != 200:
        raise AIError(f"AI 服务返回 HTTP {r.status_code}: {r.text[:200]}")
    try:
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as e:
        raise AIError(f"AI 服务返回格式异常: {e}")


def _parse_json(raw: str) -> dict:
    """解析模型返回的 JSON，容忍 ```json 围栏。"""
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except ValueError as e:
        raise AIError(f"模型未返回合法 JSON: {e}")
    if not isinstance(data, dict):
        raise AIError("模型返回的 JSON 不是对象")
    return data


# ---------- 排版标准（style profile） ----------

STYLE_GENERAL = "general"
STYLE_CUMCM = "cumcm"

_CUMCM_RULES = """该文档是全国大学生数学建模竞赛（高教社杯）论文，必须严格按以下官方格式规范排版：

【论文结构】
1. 第一页为承诺书，第二页为编号专用页（若已有则原样保留，不要改动或增删这两页）；
2. 论文题目与摘要写在摘要页，其后是正文；页码从题目/摘要页起用阿拉伯数字从 1 连续编号，位于页脚中部。

【字体与版面】
3. A4 纸，上下左右页边距 2.5cm；
4. 论文题目：三号黑体、居中；
5. 一级标题（\\section）：四号黑体、居中、阿拉伯数字编号；
6. 二级/三级标题（\\subsection/\\subsubsection）：小四号黑体、左端对齐（不居中）；
7. 正文：小四号宋体，西文 Times New Roman，单倍行距，首行缩进 2 字符；
8. 不得出现任何可能显示答题人身份的标志（学校名、姓名等），若发现须删除。

【摘要】
9. 摘要简明扼要且详细，篇幅不超过一页，末尾须有“关键词：”行，无需英文摘要。

【图表与公式】
10. 图、表必须有标题且编号：图题位于图下方，表题位于表上方；表格用 booktabs 三线表；
11. 图片用 figure 环境（[htbp] 浮动位置 + \\label），核心公式必须编号（equation/align 环境）；
12. 正文引用图表用 \\ref。

【参考文献与附录】
13. 参考文献按正文引用次序列出，正文引用处用方括号编号（如 [1][3]），格式：
    书籍：[编号] 作者，书名，出版地：出版社，出版年。
    期刊：[编号] 作者，论文名，杂志名，卷期号：起止页码，出版年。
    网上资源：[编号] 作者，资源标题，网址，访问时间（年月日）。
14. 程序源代码放在附录（\\appendix + verbatim）。

【导言区】
15. 若文件缺少符合竞赛标准的导言区，请补齐：\\documentclass[UTF8,zihao=-4]{ctexart}、
    geometry 四边 2.5cm、amsmath、amssymb、graphicx、booktabs、caption
    （图题小五宋体位于图下方、表题小五黑体位于表上方），并用 \\ctexset 设置
    一级标题四号黑体居中、二三级标题小四黑体左对齐。不要加页眉。"""

STYLES: dict[str, dict] = {
    STYLE_GENERAL: {"name": "通用排版", "rules": ""},
    STYLE_CUMCM: {"name": "数模国赛（高教杯）", "rules": _CUMCM_RULES},
}


def get_style(style: str) -> dict:
    if style not in STYLES:
        raise AIError(f"未知排版标准: {style}（可选: {', '.join(STYLES)}）")
    return STYLES[style]


# ---------- 阶段 1：分析 ----------

_ANALYZE_BASE = """你是 LaTeX 排版专家。用户会给你一个 LaTeX 源文件，请你对其进行排版整理。

要求：
1. 严格保留原文的全部内容与含义：不得删减或概括正文，不得改动公式内容、数据、\\cite/\\ref 的 key。
2. 修正排版与结构问题：
   - 段落、列表、表格使用合适的环境（itemize/enumerate/tabular 等）；表格优先 booktabs 三线表风格
   - 数学公式使用合适的环境（行内 $...$、行间方程用 equation/align 等）
   - 图片使用 figure 环境，带 [htbp] 浮动位置、\\caption 与 \\label
   - 章节层级使用 \\section/\\subsection 等合理划分
   - 若文件含导言区（\\documentclass），可按需在导言区补充 \\usepackage（如 booktabs、graphicx）
   - 规范缩进与空行
3. 如果输入是未结构化的纯文本，把它转换为结构良好的 LaTeX；若原文件已有 documentclass，保持原有文档框架。
4. 如果排版已经很好，content 原样返回并在 summary 中说明。"""

_ANALYZE_OUTPUT = """
必须输出严格 JSON（不要任何额外文字）：
   {"summary": "排版改动的中文说明", "content": "排版后的完整文件内容（不得省略任何部分）"}"""


def _analyze_system(style: str) -> str:
    rules = get_style(style)["rules"]
    block = f"\n\n【排版标准：{get_style(style)['name']}】\n{rules}" if rules else ""
    return _ANALYZE_BASE + block + "\n" + _ANALYZE_OUTPUT


async def analyze(slug: str, path: str, style: str = STYLE_GENERAL) -> dict:
    """分析单个文件的排版问题，返回 {summary, content, diff, changed, style}。"""
    sty = get_style(style)
    storage.get_project(slug)  # 校验项目存在
    content = storage.read_file(slug, path)
    if len(content) > MAX_ANALYZE_CHARS:
        raise AIError(f"文件过大（{len(content)} 字符），暂不支持整体分析")

    user_msg = (
        f"文件路径: {path}\n"
        f"文件内容（在 <<<LATEX 与 >>>LATEX 之间）:\n"
        f"<<<LATEX\n{content}\n>>>LATEX\n"
        "请按要求输出 JSON。"
    )
    raw = await _chat(
        [
            {"role": "system", "content": _analyze_system(style)},
            {"role": "user", "content": user_msg},
        ]
    )
    data = _parse_json(raw)
    new_content = data.get("content")
    if not isinstance(new_content, str) or not new_content.strip():
        raise AIError("模型返回缺少有效的 content 字段")
    if not new_content.endswith("\n"):
        new_content += "\n"

    summary = str(data.get("summary") or "").strip() or "（模型未给出说明）"
    changed = new_content.strip() != content.strip()
    return {
        "summary": summary,
        "content": new_content,
        "diff": _make_diff(content, new_content, path),
        "changed": changed,
        "style": style,
        "style_name": sty["name"],
    }


def _make_diff(old: str, new: str, path: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
    )
    return "\n".join(lines)[:60_000]


# ---------- 阶段 2：应用 + 编译自愈 ----------

_REPAIR_SYSTEM = """你是 LaTeX 编译错误修复专家。用户给你一份编译失败的 LaTeX 源文件和编译错误日志，
请你修复错误并输出完整的新文件内容。

要求：
1. 只修编译错误，不要改动内容与排版风格。
2. 常见问题：缺少 \\usepackage、环境未闭合、$ 不配对、特殊字符未转义（& % # _ 等）、
   缺少 \\begin{document}/\\end{document}、图片文件不存在（可注释掉该 figure）。
3. 必须输出严格 JSON：{"analysis": "错误原因与修复方法的中文说明", "content": "修复后的完整文件内容"}"""


def _error_tail(log: str, max_chars: int = 3000) -> str:
    """从编译日志中提取错误相关行，供修复提示词使用。"""
    pat = re.compile(r"^(\S+\.(?:tex|sty|cls|bib|aux):\d+:|! )")
    hits = [ln for ln in log.splitlines() if pat.match(ln)]
    text = "\n".join(hits) if hits else "\n".join(log.splitlines()[-60:])
    return text[-max_chars:]


async def _repair(content: str, errors: str) -> str | None:
    """让模型根据编译错误修复源码；失败返回 None。"""
    user_msg = (
        f"编译错误日志:\n<<<LOG\n{errors}\n>>>LOG\n\n"
        f"当前源文件内容:\n<<<LATEX\n{content}\n>>>LATEX\n"
        "请输出 JSON。"
    )
    try:
        raw = await _chat(
            [
                {"role": "system", "content": _REPAIR_SYSTEM},
                {"role": "user", "content": user_msg},
            ]
        )
        data = _parse_json(raw)
        fixed = data.get("content")
        if isinstance(fixed, str) and fixed.strip():
            return fixed if fixed.endswith("\n") else fixed + "\n"
    except AIError:
        pass
    return None


def _git_head(proj: Path) -> str | None:
    r = storage._git(proj, "rev-parse", "HEAD", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


async def apply(slug: str, path: str, new_content: str, do_compile: bool = True) -> dict:
    """应用排版结果：写入（自动提交）→ 编译 → 失败则自愈 → 彻底失败则回滚。"""
    meta = storage.get_project(slug)
    proj = storage._proj_dir(slug)
    pre_sha = _git_head(proj)

    storage.write_file(slug, path, new_content)  # 自动 git 提交
    if not do_compile:
        return {"applied": True, "success": None, "compile_unavailable": False,
                "rolled_back": False, "rounds": [], "log": ""}

    current = new_content
    rounds: list[dict] = []
    last_log = ""
    for round_idx in range(MAX_REPAIR_ROUNDS + 1):
        try:
            result = await compile_mod.compile_project(slug, proj, meta["main_file"])
        except FileNotFoundError:
            # latexmk 不存在（如未安装 TeX Live 的开发机）：无法验证，保留改动
            return {"applied": True, "success": None, "compile_unavailable": True,
                    "rolled_back": False, "rounds": rounds, "log": ""}
        last_log = result["log"]
        rounds.append({
            "round": round_idx, "success": result["success"],
            "seconds": result["seconds"], "timed_out": result["timed_out"],
        })
        if result["success"]:
            return {"applied": True, "success": True, "compile_unavailable": False,
                    "rolled_back": False, "rounds": rounds,
                    "log": "\n".join(last_log.splitlines()[-30:])}
        if round_idx >= MAX_REPAIR_ROUNDS:
            break
        fixed = await _repair(current, _error_tail(last_log))
        if fixed is None or fixed.strip() == current.strip():
            break
        current = fixed
        storage.write_file(slug, path, current)

    # 自愈失败 → 回滚到 AI 修改之前
    if pre_sha:
        storage._git(proj, "checkout", "-q", pre_sha, "--", ".", check=False)
        storage._commit(proj, "AI 排版失败，已回滚")
    return {"applied": True, "success": False, "compile_unavailable": False,
            "rolled_back": bool(pre_sha), "rounds": rounds,
            "log": "\n".join(last_log.splitlines()[-60:])}
