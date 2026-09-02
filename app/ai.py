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


class AIConflictError(AIError):
    """应用时文件内容与分析快照不一致（用户在分析后又编辑了文件）。"""


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


def _decode_jsonish_fragment(fragment: str) -> str:
    """解码常见的 JSON 非严格字符串，保留 LaTeX 中的反斜杠。"""
    escaped: list[str] = []
    i = 0
    while i < len(fragment):
        ch = fragment[i]
        if ch == "\\":
            if i + 1 < len(fragment) and fragment[i + 1] in '"\\/bfnrt':
                escaped.append(ch + fragment[i + 1])
                i += 2
                continue
            if (
                i + 5 < len(fragment)
                and fragment[i + 1] == "u"
                and re.fullmatch(r"[0-9a-fA-F]{4}", fragment[i + 2 : i + 6])
            ):
                escaped.append(fragment[i : i + 6])
                i += 6
                continue
            # 模型有时把 LaTeX 的 \section 当成 JSON 转义，补一层反斜杠。
            escaped.append("\\\\")
            i += 1
            continue
        if ch == '"':
            escaped.append('\\"')
        elif ch == "\n":
            escaped.append("\\n")
        elif ch == "\r":
            escaped.append("\\r")
        elif ch == "\t":
            escaped.append("\\t")
        elif ord(ch) < 0x20:
            escaped.append(f"\\u{ord(ch):04x}")
        else:
            escaped.append(ch)
        i += 1
    return json.loads('"' + "".join(escaped) + '"')


def _recover_json_object(text: str) -> dict | None:
    """恢复含原始换行或 LaTeX 反斜杠的两字段 JSON。"""
    content_key = re.search(r'"content"\s*:\s*"', text)
    if not content_key:
        return None

    # content 按约定是最后一个字段，取对象结束花括号前的最后一个引号。
    object_end = text.rfind("}")
    if object_end <= content_key.end():
        return None
    content_end = text.rfind('"', content_key.end(), object_end)
    if content_end < content_key.end():
        return None

    try:
        content = _decode_jsonish_fragment(text[content_key.end() : content_end])
    except (TypeError, ValueError):
        return None

    summary = ""
    summary_key = re.search(r'"summary"\s*:\s*"', text)
    if summary_key and summary_key.end() < content_key.start():
        # summary 比 content 短，取 content 键之前的最后一个引号。
        summary_end = text.rfind('"', summary_key.end(), content_key.start())
        if summary_end >= summary_key.end():
            try:
                summary = _decode_jsonish_fragment(
                    text[summary_key.end() : summary_end]
                )
            except (TypeError, ValueError):
                summary = ""
    return {"summary": summary, "content": content}


def _parse_json(raw: str) -> dict:
    """解析模型返回的 JSON，容忍代码围栏及常见的非严格 JSON。"""
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except ValueError as e:
        recovered = _recover_json_object(text)
        if recovered is not None:
            return recovered
        raise AIError(
            "模型返回的 JSON 不完整或格式错误，可能是输出过长导致接口截断；"
            f"请改用选区模式分段处理（原错误：{e}）"
        )
    if not isinstance(data, dict):
        raise AIError("模型返回的 JSON 不是对象")
    return data


# AI 偶尔会把自然段写成“· 内容”或“• 内容”。这些符号不属于论文排版，
# 只清理行首的分行标记，不触碰正文中可能有实际语义的普通字符。
_LINE_START_DOT = re.compile(r"^([ \t]*)(?:·|•|●|▪|‧|∙|⋅)[ \t]*")


def _remove_ai_line_markers(content: str) -> tuple[str, int]:
    """移除 AI 在论文源文件中生成的行首圆点分行符。"""
    lines = content.splitlines()
    cleaned: list[str] = []
    removed = 0
    list_depth = 0
    for line in lines:
        match = _LINE_START_DOT.match(line)
        if match:
            removed += 1
            text = line[match.end():]
            if list_depth:
                # 如果模型已经放在列表环境中，恢复为合法的 LaTeX 列表项。
                line = match.group(1) + r"\item " + text
            else:
                # 把被圆点切开的行恢复成独立自然段，避免只删符号后仍挤在同一段中。
                if cleaned and cleaned[-1].strip():
                    cleaned.append("")
                line = match.group(1) + text
        cleaned.append(line)

        begins = re.findall(r"\\begin\{(?:itemize|enumerate|description)\}", line)
        ends = re.findall(r"\\end\{(?:itemize|enumerate|description)\}", line)
        list_depth = max(0, list_depth + len(begins) - len(ends))
    result = "\n".join(cleaned)
    if content.endswith("\n"):
        result += "\n"
    return result, removed


def _append_cleanup_notice(summary: str, removed: int) -> str:
    if not removed:
        return summary
    return f"{summary}；已自动移除 {removed} 处 AI 生成的行首圆点分行符"


# ---------- 排版标准（style profile） ----------

STYLE_GENERAL = "general"
STYLE_CUMCM = "cumcm"

_CUMCM_RULES = r"""这是全国大学生数学建模竞赛（高教社杯）论文的排版任务。以下内容包含官方要求和本项目统一的论文排版约定；未列出的字号、字体、行距和颜色不要擅自当作全国统一要求：

【硬性格式要求】
1. A4 纸，上下左右页边距至少 2.5cm；论文必须包含目录，目录放在摘要之后、正文之前。
2. 纸质版的承诺书和编号专用页由当届官方专用页提供，位于论文前两页；电子版论文和支撑材料中都不要放这两页。
3. 电子版论文第一页为摘要页；摘要含标题和关键词，原则上不超过一页，不需要英文摘要。
4. 纸质版正文从第四页开始，正文不超过 30 页；正文之后可有页数不限的附录。
5. 摘要、正文、附录及支撑材料中不得出现姓名、学校、赛区等身份信息。
6. 参考资料必须按科技论文规范列出，并在正文对应位置标注。
7. 附录应包含支撑材料文件列表和完整、可运行的源程序；确实没有使用程序时，按规定写明“本论文没有用到程序”。

【参考公开优秀论文的组织方式（仅为写作建议，不是统一硬性格式）】
8. 摘要直接交代问题、方法、关键结果和结论，少用空泛的背景套话；不要凭空补数据、结果或结论。
9. 正文围绕题目各小问组织，可使用“问题分析、模型假设、符号说明、模型建立与求解、结果分析、模型评价”等自然结构，不要机械套满固定章节。
10. 每个公式都要在正文中说明变量和作用；图表只引用项目中真实存在且确有必要的内容，图表应有编号、标题，并在正文中被引用。
11. 数学公式保持朴素、清晰，禁止新增 \\boxed、\\fbox、\\framebox、\\colorbox 等包围公式的写法；不要为了强调公式添加边框、底色或装饰。
12. 不得使用中文中点“·”、圆点或短横线把正文切成碎片或代替分段；自然段用空行，分点使用规范列表环境。

【电子版与 AI 排版】
13. 本工具默认生成电子版论文内容：不主动新增承诺书和编号专用页，但必须保留目录。若输入文件已有这两页，不要擅自改写其内容，应在 summary 中提醒用户提交电子版时移除，并另附当届官方专用页用于纸质版。
14. 若使用 AI，应在参考文献前设置 AI 工具使用声明，并按当届 AI 规定准备“AI工具使用详情.pdf”；AI 只能辅助，核心建模与分析必须由参赛队主导并人工核验。"""

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
1. 严格保留原文的全部内容与含义：默认逐字保留正文，不得删减、概括或润色成另一种文风；不得改动公式内容、数据、\\cite/\\ref 的 key。
2. 修正排版与结构问题：
   - 段落、列表、表格使用合适的环境（itemize/enumerate/tabular 等）；表格优先 booktabs 三线表风格
   - 数学公式使用合适的环境（行内 $...$、行间方程用 equation/align 等）
   - 图片使用 figure 环境，带 [htbp] 浮动位置、\\caption 与 \\label；
     \\includegraphics 必须带宽度约束（如 width=0.8\\linewidth），禁止超出文本宽度
   - 章节层级使用 \\section/\\subsection 等合理划分
   - Python、R、MATLAB 等程序只能放在附录的代码环境中（如 Verbatim/VerbatimInput 或 listings），或作为项目中的独立支撑材料；禁止把原始程序直接写进普通正文或数学环境
   - 若文件含导言区（\\documentclass），可按需在导言区补充 \\usepackage（如 booktabs、graphicx）
   - 规范缩进与空行
3. 如果输入是未结构化的纯文本，把它转换为结构良好的 LaTeX；若原文件已有 documentclass，保持原有文档框架。
4. 如果排版已经很好，content 原样返回并在 summary 中说明。
5. 引用图片时只能使用项目目录中真实存在的文件（见用户提供的文件清单）；
   没有合适的图片文件时，用占位框（\\fbox）或注释掉图片，并在 summary 中说明。"""

_ANALYZE_OUTPUT = """
必须输出严格 JSON（不要任何额外文字）：
   {"summary": "排版改动的中文说明", "content": "排版后的完整文件内容（不得省略任何部分）"}"""


_WRITING_GUARDRAILS = r"""

【文风与输出约束】
- 只做排版整理，不代写论文，不擅自补充数据、实验结果、结论、方法、引用或作者信息。
- 尽量保留原文的措辞和信息密度。不要把普通句子改成空泛、模板化的表达，例如“本文旨在……”“具有重要意义”“为……提供参考”等。
- 不要为了显得正式强行加入“首先、其次、最后、综上所述、值得注意的是”等套话；只有原文确有对应逻辑时才保留。
- 对论文类文档必须保留目录；若没有目录，在摘要或题名等前置部分之后加入 \\tableofcontents，目录不得用手写点线拼接。
- 不得使用中文中点“·”、圆点或短横线把正文切成碎片或代替分段。自然段用空行，分点使用 enumerate/itemize，层次使用 section/subsection。
- 公式不得新增 \\boxed、\\fbox、\\framebox、\\colorbox 等边框或底色；公式按正常 equation/align 等环境排版。
"""


def _analyze_system(style: str) -> str:
    rules = get_style(style)["rules"]
    block = f"\n\n【排版标准：{get_style(style)['name']}】\n{rules}" if rules else ""
    return _ANALYZE_BASE + _WRITING_GUARDRAILS + block + "\n" + _ANALYZE_OUTPUT


_SELECTION_OUTPUT = """
必须输出严格 JSON（不要任何额外文字）：
   {"summary": "改动说明（中文）", "content": "选中区域排版后的完整替换文本"}
注意：content 只是选中区域的替换文本，不要包含选中区域以外的任何内容，也不要输出整个文件。"""


def _analyze_system_selection(style: str) -> str:
    """选区模式：只允许改写选中区域。"""
    sty = get_style(style)
    block = f"\n\n【排版标准：{sty['name']}】\n{sty['rules']}" if sty["rules"] else ""
    return (
        "你是 LaTeX 排版专家。用户给你一份 LaTeX 文件的完整内容（仅作上下文）和其中的一个选中区域。\n"
        "你的任务：只改写选中区域的排版，选中区域以外的部分绝对不动。\n\n"
        "要求：\n"
        "1. 保留选中区域的全部内容与含义，只调整排版与结构（环境、公式、图表、标题层级等）。\n"
        "2. 如果用户给出了具体排版要求，优先满足用户要求。\n"
        "3. 不要修改选中区域以外的内容（包括导言区）；若确实需要补 \\usepackage，在 summary 中提醒用户。\n"
        "4. 输出的 content 必须能直接替换原选中区域，注意与上下文衔接的换行和缩进。\n"
        "5. 若选中区域排版已无需修改，content 原样返回并在 summary 中说明。"
        + _WRITING_GUARDRAILS + block + "\n" + _SELECTION_OUTPUT
    )


def _validate_selection(content: str, start: int, end: int) -> int:
    n = len(content.splitlines())
    if start < 1 or end > n or start > end:
        raise AIError(f"选区超出文件范围（文件共 {n} 行）")
    return n


async def analyze(
    slug: str,
    path: str,
    style: str = STYLE_GENERAL,
    selection: tuple[int, int] | None = None,
    instruction: str = "",
) -> dict:
    """分析排版问题。

    selection 为 None → 全文模式，content = 排版后的完整文件；
    selection = (start, end)（1 基、闭区间行号）→ 选区模式，
    content = 选中区域的替换文本。
    """
    sty = get_style(style)
    storage.get_project(slug)  # 校验项目存在
    content = storage.read_file(slug, path)
    if len(content) > MAX_ANALYZE_CHARS:
        raise AIError(f"文件过大（{len(content)} 字符），暂不支持整体分析")
    instruction = (instruction or "").strip()

    # 注入项目文件清单：模型只能引用真实存在的图片文件，杜绝编造文件名
    try:
        files = storage.list_files(slug)
    except Exception:
        files = []
    file_lines = "\n".join(f"  - {f['path']}" for f in files[:200]) or "  （空项目）"

    if selection:
        start, end = selection
        _validate_selection(content, start, end)
        region = "\n".join(content.splitlines()[start - 1 : end])
        system_prompt = _analyze_system_selection(style)
        user_msg = (
            f"文件路径: {path}\n"
            f"项目目录当前全部文件清单（\\includegraphics 只能引用此清单中的文件，不得编造文件名）:\n"
            f"{file_lines}\n"
            f"完整文件内容（仅供上下文参考，禁止修改选中区域以外的部分，在 <<<LATEX 与 >>>LATEX 之间）:\n"
            f"<<<LATEX\n{content}\n>>>LATEX\n"
            f"选中区域：第 {start} 行 ~ 第 {end} 行（在 <<<SELECTED 与 >>>SELECTED 之间）:\n"
            f"<<<SELECTED\n{region}\n>>>SELECTED\n"
            f"用户排版要求：{instruction or '（无，按排版标准整理）'}\n"
            "请按要求输出 JSON。"
        )
    else:
        system_prompt = _analyze_system(style)
        user_msg = (
            f"文件路径: {path}\n"
            f"项目目录当前全部文件清单（\\includegraphics 只能引用此清单中的文件，不得编造文件名）:\n"
            f"{file_lines}\n"
            f"文件内容（在 <<<LATEX 与 >>>LATEX 之间）:\n"
            f"<<<LATEX\n{content}\n>>>LATEX\n"
            f"用户排版要求：{instruction or '（无，按排版标准整理）'}\n"
            "请按要求输出 JSON。"
        )

    raw = await _chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]
    )
    data = _parse_json(raw)
    new_content = data.get("content")
    if not isinstance(new_content, str) or not new_content.strip():
        raise AIError("模型返回缺少有效的 content 字段")

    summary = str(data.get("summary") or "").strip() or "（模型未给出说明）"
    new_content, removed_markers = _remove_ai_line_markers(new_content)
    summary = _append_cleanup_notice(summary, removed_markers)

    if selection:
        start, end = selection
        original = "\n".join(content.splitlines()[start - 1 : end])
        replacement = new_content.rstrip("\n")
        return {
            "summary": summary,
            "content": replacement,
            "diff": _make_diff(original, replacement, f"{path} 第{start}-{end}行"),
            "changed": replacement.strip() != original.strip(),
            "style": style,
            "style_name": sty["name"],
            "mode": "selection",
            "start_line": start,
            "end_line": end,
            "original": original,
        }

    if not new_content.endswith("\n"):
        new_content += "\n"
    return {
        "summary": summary,
        "content": new_content,
        "diff": _make_diff(content, new_content, path),
        "changed": new_content.strip() != content.strip(),
        "style": style,
        "style_name": sty["name"],
        "mode": "full",
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
   缺少 \\begin{document}/\\end{document}、图片文件不存在（可注释掉该 figure）。如果发现裸露的 Python、R、MATLAB 等程序，必须将其放入 Verbatim/VerbatimInput 或 listings 环境，不能当作普通 LaTeX 正文解析。
3. 不要新增公式边框或底色（如 \\boxed、\\fbox、\\framebox、\\colorbox），也不要用“·”代替自然分段。
4. 必须输出严格 JSON：{"analysis": "错误原因与修复方法的中文说明", "content": "修复后的完整文件内容"}"""


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
            fixed, _ = _remove_ai_line_markers(fixed)
            return fixed if fixed.endswith("\n") else fixed + "\n"
    except AIError:
        pass
    return None


def _git_head(proj: Path) -> str | None:
    r = storage._git(proj, "rev-parse", "HEAD", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


async def _apply_content(slug: str, path: str, new_content: str,
                         do_compile: bool, mode: str) -> dict:
    """写入新内容（自动提交）→ 编译 → 失败则自愈 → 彻底失败则回滚。"""
    meta = storage.get_project(slug)
    proj = storage._proj_dir(slug)
    pre_sha = _git_head(proj)

    # 最后一层保护：即使用户编辑了预览内容，也不把行首圆点分行写入论文。
    new_content, _ = _remove_ai_line_markers(new_content)
    storage.write_file(slug, path, new_content)  # 自动 git 提交
    base = {"applied": True, "mode": mode}
    if not do_compile:
        return {**base, "success": None, "compile_unavailable": False,
                "rolled_back": False, "rounds": [], "log": ""}

    current = new_content
    rounds: list[dict] = []
    last_log = ""
    for round_idx in range(MAX_REPAIR_ROUNDS + 1):
        try:
            result = await compile_mod.compile_project(slug, proj, meta["main_file"])
        except FileNotFoundError:
            # latexmk 不存在（如未安装 TeX Live 的开发机）：无法验证，保留改动
            return {**base, "success": None, "compile_unavailable": True,
                    "rolled_back": False, "rounds": rounds, "log": ""}
        last_log = result["log"]
        rounds.append({
            "round": round_idx, "success": result["success"],
            "seconds": result["seconds"], "timed_out": result["timed_out"],
        })
        if result["success"]:
            return {**base, "success": True, "compile_unavailable": False,
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
    return {**base, "success": False, "compile_unavailable": False,
            "rolled_back": bool(pre_sha), "rounds": rounds,
            "log": "\n".join(last_log.splitlines()[-60:])}


async def apply(slug: str, path: str, new_content: str, do_compile: bool = True) -> dict:
    """应用全文排版结果。"""
    storage.get_project(slug)
    return await _apply_content(slug, path, new_content, do_compile, mode="full")


async def apply_selection(
    slug: str, path: str, start: int, end: int,
    original: str, replacement: str, do_compile: bool = True,
) -> dict:
    """应用选区排版结果：校验区域未变 → 行级替换 → 编译自愈。"""
    storage.get_project(slug)
    content = storage.read_file(slug, path)
    _validate_selection(content, start, end)

    # 错位保护：分析后用户又编辑了文件，则拒绝应用
    current_region = "\n".join(content.splitlines()[start - 1 : end])
    if current_region.strip() != (original or "").strip():
        raise AIConflictError("文件内容与分析时不一致（分析后发生过编辑），请重新分析")

    lines = content.splitlines()
    rep_lines = replacement.splitlines()
    new_content = "\n".join(lines[: start - 1] + rep_lines + lines[end:]) + "\n"
    result = await _apply_content(slug, path, new_content, do_compile, mode="selection")
    result["start_line"] = start
    result["end_line"] = start + len(rep_lines) - 1 if rep_lines else start
    return result
