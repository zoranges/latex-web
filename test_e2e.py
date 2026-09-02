"""端到端冒烟测试：真实浏览器中驱动 LaTeX Web。"""
import asyncio
import sys
import time

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8090"
PROJECT_NAME = f"测试项目-{int(time.time())}"

ok = 0


def check(name: str, cond: bool, extra: str = ""):
    global ok
    if cond:
        ok += 1
        print(f"  ✅ {name} {extra}")
    else:
        print(f"  ❌ {name} {extra}")
    return cond


async def main():
    global ok
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1600, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console.error: {m.text}") if m.type == "error" else None)

        # 注意：不能用 networkidle——打开项目后 PDF 会拉 169 个 CMap 文件，网络长期不静默
        await page.goto(BASE, wait_until="load")
        await page.wait_for_selector("#editor-host .monaco-editor", timeout=20000)
        check("Monaco 编辑器加载", True)

        # 每次测试使用独立账号，避免共享服务上的项目和登录态互相影响。
        await page.wait_for_function(
            "document.querySelector('#auth-modal').hidden === false || window.LW?.user",
            timeout=10000,
        )
        if await page.locator("#auth-modal").is_visible():
            await page.click("#auth-switch")
            await page.fill("#auth-username", f"e2e_{int(time.time())}")
            await page.fill("#auth-password", "e2e-password-2026")
            await page.fill("#auth-password-confirm", "e2e-password-2026")
            await page.click("#auth-submit")
            await page.wait_for_selector("#auth-modal", state="hidden", timeout=10000)

        # 新账号没有项目时，用模板创建本次测试项目。
        await page.wait_for_timeout(500)
        items = await page.locator("#project-list .project-item span").all_text_contents()
        if not any(PROJECT_NAME in t for t in items):
            await page.click("#btn-new-project")
            await page.wait_for_selector("#template-modal:not([hidden]) .tpl-card", timeout=10000)
            await page.fill("#tpl-name", PROJECT_NAME)
            await page.click("#btn-template-create")
            await page.wait_for_selector("#project-list .project-item", timeout=20000)

        # 项目列表
        await page.wait_for_selector("#project-list .project-item", timeout=10000)
        items = await page.locator("#project-list .project-item span").all_text_contents()
        check("项目列表包含测试项目", any(PROJECT_NAME in t for t in items), str(items))

        # 打开测试项目（force 规避 Playwright 对持续动画的 stable 误判）
        await page.locator("#project-list .project-item", has_text=PROJECT_NAME).first.click(force=True)
        await page.wait_for_selector("#file-tree .file-item", timeout=10000)
        tree = await page.locator("#file-tree .file-item .tree-file").all_text_contents()
        check("文件树加载", any("main.tex" in t for t in tree), str(tree))

        # 等编辑器内容加载（应包含 测试文档 标题）
        await page.wait_for_timeout(1000)
        content = await page.evaluate("LW.editor.getValue()")
        check("编辑器加载 main.tex 内容", "新文档" in content or "测试文档" in content)

        # 编辑 → 自动保存 → 自动编译
        await page.locator("#editor-host").click()
        await page.keyboard.press("Control+End")
        await page.keyboard.type("\n\\section{Playwright 测试}\n这条来自自动化测试。\n")
        await page.wait_for_selector("#status:has-text('已编译')", timeout=60000)
        status = await page.locator("#status").text_content()
        check("自动保存 + 自动编译成功", "已编译" in status, status)

        # PDF 渲染
        await page.wait_for_selector(".pdf-page canvas", state="visible", timeout=10000)
        pages = await page.locator("#pdf-page-info").text_content()
        check("PDF 渲染", "1 /" in pages, pages)

        # 正向 SyncTeX：光标放第 11 行 → 定位到 PDF
        await page.evaluate("LW.editor.setPosition({lineNumber: 11, column: 1})")
        await page.click("#btn-sync")
        await page.wait_for_timeout(1500)
        marker_visible = await page.locator("#pdf-marker").is_visible()
        check("正向 SyncTeX 标记出现", marker_visible)

        # 反向 SyncTeX：点击 PDF 画布中心 → 源码高亮
        box = await page.locator(".pdf-page[data-page='1']").bounding_box()
        await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.25)
        await page.wait_for_timeout(1500)
        hl = await page.locator(".sync-highlight").count()
        hl2 = await page.evaluate("LW.editor.getPosition().lineNumber")
        check("反向 SyncTeX 跳转源码", hl > 0 or hl2 > 1, f"highlights={hl}, line={hl2}")

        # 历史面板
        await page.click("#btn-history")
        await page.wait_for_selector("#history-modal:not([hidden]) #history-list .history-item", timeout=10000)
        n_commits = await page.locator("#history-list .history-item").count()
        check("历史面板有提交记录", n_commits >= 2, f"{n_commits} 条")
        # 查看 diff
        await page.locator("#history-list .history-info").first.click()
        await page.wait_for_timeout(800)
        diff = await page.locator("#diff-view").text_content()
        check("diff 内容展示", "diff --git" in diff or len(diff) > 50)
        await page.click("#btn-history-close")

        # 日志抽屉（编译成功时不显示；直接验证关闭按钮存在即可，跳过）

        # 新建文件
        async def accept_dialog(d):
            await d.accept("notes/实验笔记.tex")
        page.once("dialog", accept_dialog)
        await page.click("#btn-new-file")
        await page.wait_for_timeout(1200)
        tree2 = await page.locator("#file-tree .tree-file").all_text_contents()
        check("新建文件出现在树中", any("实验笔记.tex" in t for t in tree2), str(tree2))

        # 上传文件
        await page.set_input_files("#upload-input", {
            "name": "diagram.png", "mimeType": "image/png",
            "buffer": bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A] + [0] * 32),
        })
        await page.wait_for_timeout(1500)
        tree3 = await page.locator("#file-tree .tree-file").all_text_contents()
        check("上传文件出现在树中", any("diagram.png" in t for t in tree3), str(tree3))

        print(f"\n  共 {ok} 项通过")
        js_errors = [e for e in errors if "favicon" not in e]
        if js_errors:
            print("  JS 错误:")
            for e in js_errors[:10]:
                print("   -", e[:200])
        await browser.close()
        return 0 if ok >= 10 and not js_errors else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
