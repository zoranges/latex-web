# LaTeX Web

轻量在线 LaTeX 编辑器（单用户），对标 Overleaf 核心编辑+编译体验，不依赖 Docker。

## 特性

- **Monaco 编辑器** — VS Code 同款，LaTeX 语法高亮、自动补全
- **自动编译** — 保存后自动运行 `latexmk -xelatex -synctex=1`，0.5~2 秒出 PDF
- **SyncTeX 双向定位** — 点击 PDF 跳转到源码行；编辑器光标定位到 PDF 位置
- **Git 版本历史** — 每次保存自动 commit，可查看 diff 并一键恢复任意版本
- **文件上传** — 上传图片等资源到项目目录
- **内置模板** — 新建项目时可选 6 种模板（见下）
- **中文支持** — 使用 ctex/xeCJK + 系统字体，开箱即用
- **移动端自适应** — 侧栏收为抽屉、编辑/预览标签切换、图标化按钮
- **离线可用** — 所有前端依赖（Monaco、pdf.js）已本地化，无需外网

## 内置模板

| 模板 | 说明 |
|---|---|
| 中文文章 | 通用 ctexart 文章 |
| 实验报告 | 目的/环境/步骤/结果/总结 |
| Beamer 幻灯片 | 16:9 学术演示（ctexbeamer） |
| 毕业论文（多文件） | ctexbook + `chapters/` 子文件 |
| 个人简历 | 单页简历 |
| 书信 | 中文书信格式 |

模板定义在 `app/templates.py`，可自行增改。

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
| GET | `/api/projects/{slug}/history` | 提交列表 |
| GET | `/api/projects/{slug}/history/{sha}` | 提交 diff |
| POST | `/api/projects/{slug}/history/{sha}/restore` | 恢复版本 |

## 键盘快捷键

| 快捷键 | 功能 |
|---|---|
| `Ctrl+S` | 立即保存 |
| `Ctrl+Enter` | 立即编译 |