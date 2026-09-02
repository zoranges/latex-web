# LaTeX Web

轻量在线 LaTeX 编辑器（单用户），对标 Overleaf 核心编辑+编译体验，不依赖 Docker。

## 特性

- **Monaco 编辑器** — VS Code 同款，LaTeX 语法高亮、自动补全
- **自动编译** — 保存后自动运行 `latexmk -xelatex -synctex=1`，0.5~2 秒出 PDF
- **SyncTeX 双向定位** — 点击 PDF 跳转到源码行；编辑器光标定位到 PDF 位置
- **Git 版本历史** — 每次保存自动 commit，可查看 diff 并一键恢复任意版本
- **AI 排版** — 大模型分析并修正排版，可选标准（通用 / 数模国赛格式）；支持**定位修正**（选中哪段只改哪段）与排版要求指令交互；两阶段：diff 预览确认 → 应用 + 编译自愈，失败自动回滚
- **数模国赛论文模板** — 参考全国组委会格式规范和公开优秀论文组织方式的电子版论文骨架
- **文件上传** — 上传图片等资源到项目目录
- **内置模板** — 新建项目时可选 7 种模板（见下）
- **中文支持** — 使用 ctex/xeCJK + 系统字体，开箱即用
- **移动端自适应** — 侧栏收为抽屉、编辑/预览标签切换、图标化按钮
- **离线可用** — 所有前端依赖（Monaco、pdf.js）已本地化，无需外网

## 内置模板

| 模板 | 说明 |
|---|---|
| 中文文章 | 通用 ctexart 文章 |
| 数模国赛论文 | 电子版论文骨架：摘要、目录、正文、结果分析、参考文献和附录 |
| 实验报告 | 目的/环境/步骤/结果/总结 |
| Beamer 幻灯片 | 16:9 学术演示（ctexbeamer） |
| 毕业论文（多文件） | ctexbook + `chapters/` 子文件 |
| 个人简历 | 单页简历 |
| 书信 | 中文书信格式 |

模板定义在 `app/templates.py`，可自行增改。

### 数模国赛论文模板

模板默认面向电子版论文：不包含承诺书和编号专用页，第一页为摘要页，摘要后固定保留目录；纸质版打印时应在论文前另附当届官方专用页。正文按公开优秀论文常见方式组织为问题重述、问题分析、模型假设、符号说明、模型建立与求解、结果分析与模型检验、模型评价与推广；附录提供支撑材料文件列表和程序位置。题目、字体、行距等仅是本模板的默认样式，正式提交前应以当届全国组委会及所在赛区通知为准。

## 依赖

- Python ≥ 3.10
- TeX Live Full（需 `xelatex`、`latexmk`、`synctex`）
- 无需 Docker、Node.js、Nginx

## 快速启动

```bash
git clone <repo> /root/latex
cd /root/latex
bash run.sh
```

浏览器打开 `http://<主机>:8090`。

### 环境变量

| 变量 | 默认值 |
|---|---|
| `PORT` | `8090` |
| `HOST` | `0.0.0.0` |

## AI 排版

工具栏「AI排版」按钮：打开排版面板。**编辑器中有选区时为「定位修正」模式（只改选中行），无选区则为全文模式**。数模国赛标准会尽量保留原文措辞和信息，不代写内容，不新增公式边框，也不使用“·”切分自然段；后端还会清理 AI 返回内容中的行首圆点分行符。流程：

1. **交互分析** — 面板中可输入自然语言排版要求（如「改成三线表」「公式居中编号」）；模型返回改动说明 + 新内容，界面展示 unified diff；不满意可调整要求后「重新分析」，反复迭代
2. **应用** — 确认后写入（自动 git 提交）→ 编译；编译失败会把错误日志喂回模型自动修复（最多 2 轮）；仍失败则自动回滚到 AI 修改前的版本

选区模式的安全机制：模型只返回选中区域的替换文本（不动其余部分）；应用时校验选区内容与分析时一致，若期间编辑过文件则返回 409 要求重新分析。

**排版标准**：按钮旁的下拉框可选——

- `通用排版` — 常规 LaTeX 排版整理
- `数模国赛` — 按全国组委会硬性要求和公开优秀论文的常见组织方式整理；保留原文信息，不新增公式边框，不用“·”切分自然段，不擅自代写模型结果，自动清理 AI 生成的行首圆点分行符

标准定义在 `app/ai.py` 的 `STYLES`，可自行扩充新标准。

未配置模型 Key 时「AI排版」会提示配置。配置方式（环境变量，或把 Key 写入 `data/ai_key` 文件）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY`（或 `AI_API_KEY`） | — | 模型 API Key |
| `AI_BASE_URL`（或 `DEEPSEEK_BASE_URL`） | `https://api.deepseek.com` | OpenAI 兼容端点 |
| `AI_MODEL`（或 `DEEPSEEK_MODEL`） | `deepseek-chat` | 模型名 |

示例：

```bash
export DEEPSEEK_API_KEY=***
# 或者换用其它 OpenAI 兼容服务（如阿里云 DashScope）：
# export AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# export AI_MODEL=qwen-plus
```

也可用本地模型网关（如 ollama 的 OpenAI 兼容端点）：`AI_BASE_URL` 指向回环地址时会自动绕过系统代理直连。

## 配置 systemd 开机自启

```bash
cp latex-web.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now latex-web
```

## 数据存储

```
data/
├── meta.db           # 项目元数据（SQLite）
└── projects/         # 每个项目一个目录，同时也是 git 仓库
    └── <slug>/
        ├── main.tex
        ├── main.pdf
        └── .git/
```

## 目录结构

```
├── app/
│   ├── main.py       # FastAPI 路由
│   ├── storage.py    # 项目/文件存储、git、SQLite
│   ├── compile.py    # latexmk 编译、SyncTeX
│   └── static/
│       ├── index.html
│       ├── app.js
│       ├── style.css
│       └── vendor/
│           ├── monaco/   # Monaco Editor 0.52
│           └── pdfjs/    # pdf.js 3.11
├── data/             # 运行时数据
├── run.sh            # 启动脚本
├── latex-web.service # systemd 单元
├── requirements.txt
└── test_e2e.py       # 端到端测试
```

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/templates` | 内置模板列表 |
| GET/POST | `/api/projects` | 列表 / 创建项目（POST 可传 `template`） |
| DELETE | `/api/projects/{slug}` | 删除项目 |
| GET/PUT | `/api/projects/{slug}/file?path=` | 读 / 写文件 |
| DELETE | `/api/projects/{slug}/file?path=` | 删除文件 |
| POST | `/api/projects/{slug}/rename` | `{old, new}` |
| POST | `/api/projects/{slug}/upload` | multipart 上传 |
| POST | `/api/projects/{slug}/compile` | 编译 |
| GET | `/api/projects/{slug}/pdf` | PDF 预览 |
| POST | `/api/projects/{slug}/sync-forward` | SyncTeX 正向 `{file,line,col}` |
| POST | `/api/projects/{slug}/sync-backward` | SyncTeX 反向 `{page,x,y}` |
| GET | `/api/ai/config` | AI 服务配置状态（是否已配置、模型名） |
| GET | `/api/ai/styles` | 可选排版标准列表 |
| POST | `/api/projects/{slug}/ai/analyze` | AI 排版阶段 1：分析 `{path, style, instruction, start_line?, end_line?}`，全文或选区，返回说明/新内容/diff（不写盘） |
| POST | `/api/projects/{slug}/ai/apply` | AI 排版阶段 2：应用 `{path, content, compile, start_line?, end_line?, original?}`，选区带错位校验（409），编译自愈失败自动回滚 |
| GET | `/api/projects/{slug}/history` | 提交列表 |
| GET | `/api/projects/{slug}/history/{sha}` | 提交 diff |
| POST | `/api/projects/{slug}/history/{sha}/restore` | 恢复版本 |

## 键盘快捷键

| 快捷键 | 功能 |
|---|---|
| `Ctrl+S` | 立即保存 |
| `Ctrl+Enter` | 立即编译 |
