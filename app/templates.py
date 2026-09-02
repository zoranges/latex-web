"""内置 LaTeX 模板库。每个模板 = 一组文件 + 主文件。"""
from __future__ import annotations

ARTICLE = r"""\documentclass[UTF8]{ctexart}
\usepackage[a4paper,margin=2.5cm]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{hyperref}

\title{新文档}
\author{作者}
\date{\today}

\begin{document}

\maketitle

\section{开始写作}

你好，LaTeX！中文与公式可以混排：$E = mc^2$。

\begin{equation}
  \int_{-\infty}^{\infty} e^{-x^2}\,\mathrm{d}x = \sqrt{\pi}
\end{equation}

\end{document}
"""

REPORT = r"""\documentclass[UTF8,a4paper]{ctexart}
\usepackage[a4paper,margin=2.5cm]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}

\title{实验报告}
\author{姓名：\underline{\hspace{3cm}} \quad 学号：\underline{\hspace{3cm}}}
\date{\today}

\begin{document}

\maketitle

\section{实验目的}

\begin{enumerate}
  \item 理解实验的基本原理；
  \item 掌握相关工具的使用方法；
  \item 培养分析与解决问题的能力。
\end{enumerate}

\section{实验环境}

\begin{table}[htbp]
  \centering
  \begin{tabular}{ll}
    \toprule
    项目 & 说明 \\
    \midrule
    操作系统 & \\
    软件版本 & \\
    \bottomrule
  \end{tabular}
\end{table}

\section{实验内容与步骤}

\subsection{步骤一}

描述第一个步骤。

\subsection{步骤二}

描述第二个步骤。

\section{实验结果与分析}

记录实验数据并进行分析。

\section{实验总结}

总结本次实验的收获与不足。

\end{document}
"""

BEAMER = r"""\documentclass[UTF8,aspectratio=169]{ctexbeamer}
\usetheme{Madrid}
\usecolortheme{default}

\title{演示文稿标题}
\subtitle{副标题}
\author{报告人}
\date{\today}

\begin{document}

\begin{frame}
  \titlepage
\end{frame}

\begin{frame}{目录}
  \tableofcontents
\end{frame}

\section{背景介绍}
\begin{frame}{背景介绍}
  \begin{itemize}
    \item 第一点
    \item 第二点
    \item 第三点
  \end{itemize}
\end{frame}

\section{核心内容}
\begin{frame}{核心内容}
  关键公式：
  \[
    a^2 + b^2 = c^2
  \]
\end{frame}

\begin{frame}{总结}
  \begin{block}{结论}
    这里是结论内容。
  \end{block}
\end{frame}

\end{document}
"""

THESIS_MAIN = r"""\documentclass[UTF8,a4paper,12pt]{ctexbook}
\usepackage[a4paper,margin=2.5cm]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{hyperref}

\title{毕业论文}
\author{作者}
\date{\today}

\begin{document}

\maketitle
\tableofcontents

\include{chapters/intro}
\include{chapters/body}
\include{chapters/conclusion}

\end{document}
"""

THESIS_INTRO = r"""\chapter{绪论}

\section{研究背景}

介绍研究背景与意义。

\section{国内外研究现状}

综述相关研究工作。

\section{本文结构}

说明各章节安排。
"""

THESIS_BODY = r"""\chapter{正文}

\section{方法}

描述所提出的方法。

\begin{equation}
  f(x) = \sum_{n=0}^{\infty} \frac{f^{(n)}(a)}{n!}(x-a)^n
\end{equation}

\section{实验}

描述实验设置与结果。
"""

THESIS_CONCLUSION = r"""\chapter{总结与展望}

\section{总结}

概括全文工作。

\section{展望}

指出未来研究方向。
"""

RESUME = r"""\documentclass[UTF8,a4paper,10pt]{ctexart}
\usepackage[margin=0.8in]{geometry}
\usepackage{enumitem}
\setlist{nosep}
\usepackage{hyperref}

\begin{document}

\begin{center}
  {\Huge\bfseries 张三} \\[4pt]
  \large 求职意向：软件工程师 \\[2pt]
  \normalsize
  电话：138-0000-0000 \quad
  邮箱：zhangsan@example.com \quad
   GitHub：github.com/zhangsan
\end{center}

\vspace{4pt}
\hrule
\section*{教育背景}
\textbf{某某大学} \hfill 2020.09 -- 2024.06 \\
计算机科学与技术 \quad 本科 \quad GPA：3.8/4.0

\vspace{6pt}
\hrule
\section*{专业技能}
\begin{itemize}
  \item 熟练掌握 Python / C++，了解数据结构与算法；
  \item 熟悉 Linux 开发环境与 Git 协作流程；
  \item 了解机器学习基础。
\end{itemize}

\vspace{6pt}
\hrule
\section*{项目经历}
\textbf{项目名称} \hfill 2023.03 -- 2023.06
\begin{itemize}
  \item 负责模块 A 的设计与实现；
  \item 优化性能，提升 30\%。
\end{itemize}

\vspace{6pt}
\hrule
\section*{荣誉奖项}
\begin{itemize}
  \item 校级一等奖学金（2022）；
  \item 程序设计竞赛二等奖（2021）。
\end{itemize}

\end{document}
"""

LETTER = r"""\documentclass[UTF8]{ctexart}
\usepackage[a4paper,margin=2.5cm]{geometry}

\begin{document}

\begin{flushright}
\today
\end{flushright}

\vspace{1em}

\noindent 尊敬的\hspace{2em}：

\vspace{1em}

您好！

这里是信件正文。可以在这里书写多段内容，表达您的想法。

第二段内容，继续展开叙述。

\vspace{2em}

\noindent 此致 \\
敬礼！

\vspace{2em}

\begin{flushright}
署名：\underline{\hspace{3cm}}
\end{flushright}

\end{document}
"""

CUMCM = r"""\documentclass[UTF8,a4paper]{ctexart}
% 本模板默认面向电子版论文：不包含承诺书和编号专用页。
% 纸质版打印时请在论文前另附当届官方专用页，电子版不要加入这两页。
\usepackage[a4paper,top=2.5cm,bottom=2.5cm,left=2.5cm,right=2.5cm]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{caption}
\usepackage{subcaption}   % 并排子图：\begin{subfigure}...\end{subfigure}
\usepackage{enumitem}
\usepackage{float}        % 提供 [H]：图片精确定位

% 西文使用 Times New Roman（缺少时退回 TeX Gyre Termes）
\IfFontExistsTF{Times New Roman}%
  {\setmainfont{Times New Roman}}%
  {\setmainfont{TeX Gyre Termes}}

% 图表标题：图题小五宋体、位于图下方；表题小五黑体、位于表上方
\DeclareCaptionFont{wusong}{\zihao{5}}
\DeclareCaptionFont{wuhei}{\zihao{5}\heiti}
\captionsetup[figure]{font={wusong},position=below,labelsep=quad}
\captionsetup[table]{font={wuhei},position=above,labelsep=quad}

% 放宽浮动比例限制，减少图片被积压到文档末尾
\renewcommand{\topfraction}{0.9}
\renewcommand{\textfraction}{0.05}
\renewcommand{\floatpagefraction}{0.85}

% 以下是本模板的默认排版样式，仅作参考，不代表全国统一字号要求
\ctexset{
  section/format      = \centering\heiti\zihao{4},
  subsection/format   = \heiti\zihao{-4},
  subsubsection/format = \heiti\zihao{-4},
}

% 正文：单倍行距，首行缩进约两个汉字；不设置页眉
\linespread{1.0}
\setlength{\parindent}{2em}
\setlength{\parskip}{0pt}

\begin{document}

% ==================== 电子版第一页：题目 + 摘要 ====================
\pagenumbering{arabic}
\setcounter{page}{1}
\pagestyle{plain}

% 纸质版的承诺书和编号专用页请使用当届官方专用页，不能直接使用自制文本。
% 电子版论文不包含这两页。

% ==================== 摘要页（电子版第一页） ====================

\begin{center}
  {\heiti\zihao{3} 论文题目}\par
  \vspace{1em}
\end{center}

\begin{center}
  {\heiti\zihao{4} 摘要}\par
\end{center}

% 摘要应说明研究问题、建模思路、求解方法、主要结果和结论，控制在一页内。

\vspace{0.8em}
\noindent{\heiti 关键词：}

% 目录：按项目统一要求保留，置于摘要之后、正文之前。
\tableofcontents

\newpage

% ==================== 正文 ====================

\section{问题重述}
% 准确重述题目要求，明确需要解决的任务和评价目标。

\section{问题分析}
% 结合题目背景说明各小问之间的关系、关键变量和主要难点。

\section{模型假设}
% 只列出确有必要且能够解释的假设，避免堆砌与题目无关的条件。

\section{符号说明}

\begin{table}[htbp]
  \centering
  \caption{主要符号说明}
  \begin{tabular}{cll}
    \toprule
    序号 & 符号 & 含义 \\
    \midrule
    % 1 & $x$ & 决策变量 \\
    \bottomrule
  \end{tabular}
\end{table}

\section{模型建立与求解}

\subsection{问题一}
% 说明问题一的变量、目标函数、约束条件、模型建立和求解过程。

\subsection{问题二}
% 说明问题二的模型、算法、参数设置和结果。按实际小问增删本节。

% \subsection{问题三}
% \subsection{问题四}

\section{结果分析与模型检验}
% 给出关键结果，说明误差、对比实验、稳定性或敏感性分析。

% 图片示例（仅在项目中有对应文件时取消注释）：
% \begin{figure}[htbp]
%   \centering
%   \includegraphics[width=0.8\linewidth]{figs/example.png}
%   \caption{图题}
%   \label{fig:example}
% \end{figure}

% 表格示例：
% \begin{table}[htbp]
%   \centering
%   \caption{表题}
%   \label{tab:example}
%   \begin{tabular}{ccc}
%     \toprule
%     列一 & 列二 & 列三 \\
%     \midrule
%     数据 & 数据 & 数据 \\
%     \bottomrule
%   \end{tabular}
% \end{table}

\section{模型评价与推广}
% 结合结果讨论模型的适用范围、优点、局限和可推广方向。

% ==================== AI 工具使用声明 ====================
% 2026 年起使用 AI 工具时，须根据实际情况填写下列声明，并删除本提示。
\section*{AI工具使用声明}
请根据实际使用情况填写本节，并在提交前删除本行。
% 未使用 AI 时：本参赛队在竞赛过程中未使用任何AI工具。
% 使用 AI 时：本参赛队在竞赛过程中使用了AI工具，主要用于〖简要用途〗，详细使用情况见支撑材料。

% ==================== 参考文献 ====================
% 按正文引用次序列出；正文引用处用 [编号]
\begin{thebibliography}{99}
  % \bibitem{ref1} 按正文首次引用顺序填写参考文献。
\end{thebibliography}

% ==================== 附录 ====================
\appendix
\section{支撑材料文件列表}
% 列出支撑材料压缩包中的文件名及用途。若没有支撑材料，请填写：本论文没有支撑材料。

\section{程序源代码}
% 粘贴完整、可运行的源程序（含 EXCEL、SPSS 等软件的交互命令）。
% 如果确实没有使用程序，请填写：本论文没有用到程序。

\end{document}
"""

# id -> 模板定义
TEMPLATES: list[dict] = [
    {
        "id": "article",
        "name": "中文文章",
        "desc": "通用中文文章（ctexart），适合日常写作",
        "main": "main.tex",
        "files": {"main.tex": ARTICLE},
    },
    {
        "id": "cumcm",
        "name": "数模国赛论文",
        "desc": "电子版论文骨架：摘要、目录、正文、结果分析、参考文献和附录；纸质版附页请使用当届官方专用页",
        "main": "main.tex",
        "files": {"main.tex": CUMCM},
    },
    {
        "id": "report",
        "name": "实验报告",
        "desc": "实验报告结构：目的/环境/步骤/结果/总结",
        "main": "main.tex",
        "files": {"main.tex": REPORT},
    },
    {
        "id": "beamer",
        "name": "Beamer 幻灯片",
        "desc": "16:9 学术演示文稿（ctexbeamer）",
        "main": "main.tex",
        "files": {"main.tex": BEAMER},
    },
    {
        "id": "thesis",
        "name": "毕业论文（多文件）",
        "desc": "ctexbook 多章节结构，含 chapters/ 子文件",
        "main": "main.tex",
        "files": {
            "main.tex": THESIS_MAIN,
            "chapters/intro.tex": THESIS_INTRO,
            "chapters/body.tex": THESIS_BODY,
            "chapters/conclusion.tex": THESIS_CONCLUSION,
        },
    },
    {
        "id": "resume",
        "name": "个人简历",
        "desc": "单页简历：教育/技能/项目/荣誉",
        "main": "main.tex",
        "files": {"main.tex": RESUME},
    },
    {
        "id": "letter",
        "name": "书信",
        "desc": "中文书信格式",
        "main": "main.tex",
        "files": {"main.tex": LETTER},
    },
]


def get_template(tid: str) -> dict:
    for t in TEMPLATES:
        if t["id"] == tid:
            return t
    return TEMPLATES[0]
