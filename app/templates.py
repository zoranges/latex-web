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

CUMCM = r"""\documentclass[UTF8,zihao=-4]{ctexart}  % 正文小四号宋体
\usepackage[a4paper,top=2.5cm,bottom=2.5cm,left=2.5cm,right=2.5cm]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{caption}
\usepackage{enumitem}
\usepackage{float}

% 西文使用 Times New Roman（缺少时退回 TeX Gyre Termes）
\IfFontExistsTF{Times New Roman}%
  {\setmainfont{Times New Roman}}%
  {\setmainfont{TeX Gyre Termes}}

% 图表标题：图题小五宋体、位于图下方；表题小五黑体、位于表上方
\DeclareCaptionFont{wusong}{\zihao{5}}
\DeclareCaptionFont{wuhei}{\zihao{5}\heiti}
\captionsetup[figure]{font={wusong},position=below,labelsep=quad}
\captionsetup[table]{font={wuhei},position=above,labelsep=quad}

% 标题：一级四号黑体居中；二/三级小四黑体左对齐
\ctexset{
  section/format      = \centering\heiti\zihao{4},
  subsection/format   = \heiti\zihao{-4},
  subsubsection/format = \heiti\zihao{-4},
}

\begin{document}

% ==================== 第一页：承诺书 ====================
% 注意：正式提交时请替换为当届官方组委会发布的承诺书原文
\thispagestyle{empty}
\begin{center}
  {\heiti\zihao{3} 全国大学生数学建模竞赛承诺书}\par
  \vspace{1.5em}
\end{center}

我们仔细阅读了全国大学生数学建模竞赛的竞赛规则。

我们完全明白，在竞赛开始后，竞赛题将公布在竞赛网站上。

我们承诺：

\begin{enumerate}[label=\arabic*.]
  \item 我们的参赛队号为：\underline{\hspace{4cm}}；
  \item 我们的论文是独立完成的，除引用文献外不含他人成果；
  \item 论文中不出现任何可能显示答题人身份的标志。
\end{enumerate}

\vfill
\begin{flushright}
  参赛队员（签名）：\underline{\hspace{3cm}}、\underline{\hspace{3cm}}、\underline{\hspace{3cm}}\\[1em]
  \underline{\hspace{3cm}} 年 \underline{\hspace{1.5cm}} 月 \underline{\hspace{1.5cm}} 日
\end{flushright}

\newpage

% ==================== 第二页：编号专用页 ====================
\thispagestyle{empty}
\begin{center}
  {\heiti\zihao{3} 编号专用页}\par
  \vspace{2em}
\end{center}

\begin{center}
\begin{tabular}{|p{3.5cm}|p{3.5cm}|p{3.5cm}|}
  \hline
  赛区评阅编号（由赛区组委会评阅前进行编号）： & & \\
  \hline
\end{tabular}
\vspace{2em}

\begin{tabular}{|p{3.5cm}|p{3.5cm}|p{3.5cm}|}
  \hline
  赛区送全国评阅编号（由赛区组委会评阅后进行编号）： & & \\
  \hline
\end{tabular}
\end{center}

\newpage

% ==================== 第三页：题目 + 摘要（页码从 1 开始） ====================
\setcounter{page}{1}

\begin{center}
  {\heiti\zihao{3} 论文题目（请替换）}\par
  \vspace{1em}
\end{center}

\begin{center}
  {\heiti\zihao{4} 摘要}\par
\end{center}

这里是摘要正文。摘要应是一份简明扼要的详细摘要：说明所研究的问题、
建立的模型、使用的算法、主要结果与结论。摘要篇幅不超过一页，无需译成英文。

\vspace{0.8em}
\noindent{\heiti 关键词：}关键词一；关键词二；关键词三

\newpage

% ==================== 正文 ====================

\section{问题重述}

用自己的语言复述题目要求。

\section{模型假设}

\begin{enumerate}[label=（\arabic*）]
  \item 假设一；
  \item 假设二。
\end{enumerate}

\section{符号说明}

\begin{table}[htbp]
  \centering
  \caption{主要符号说明}
  \begin{tabular}{cll}
    \toprule
    序号 & 符号 & 含义 \\
    \midrule
    1 & $x$ & 决策变量 \\
    2 & $f(x)$ & 目标函数 \\
    \bottomrule
  \end{tabular}
\end{table}

\section{模型的建立与求解}

\subsection{模型建立}

正文为小四号宋体、单倍行距。核心公式必须编号，例如：
\begin{equation}
  \min f(x) \quad \text{s.t.} \quad g_i(x) \leq 0,\ i = 1, \ldots, m
\end{equation}

\subsection{模型求解}

引用公式用~\ref{eq:demo}，引用图表用图~\ref{fig:demo}、表~\ref{tab:demo}。
引用文献用方括号编号，如~\cite{ref1}。

\begin{equation}\label{eq:demo}
  \int_0^1 x^2\,\mathrm{d}x = \frac{1}{3}
\end{equation}

\begin{figure}[htbp]
  \centering
  % \includegraphics[width=0.7\linewidth]{figs/example.png}
  \fbox{\parbox{0.6\linewidth}{\centering\vspace{2em}（此处放置图片）\vspace{2em}}}
  \caption{示例图题（位于图下方）}
  \label{fig:demo}
\end{figure}

\begin{table}[htbp]
  \centering
  \caption{示例表题（位于表上方）}
  \label{tab:demo}
  \begin{tabular}{ccc}
    \toprule
    列一 & 列二 & 列三 \\
    \midrule
    数据 & 数据 & 数据 \\
    \bottomrule
  \end{tabular}
\end{table}

\section{模型评价与推广}

分析模型的优缺点、灵敏度与改进方向。

% ==================== 参考文献 ====================
% 按正文引用次序列出；正文引用处用 [编号]
\begin{thebibliography}{99}
  \bibitem{ref1} 作者，书名，出版地：出版社，出版年。
  \bibitem{ref2} 作者，论文名，杂志名，卷期号：起止页码，出版年。
  \bibitem{ref3} 作者，资源标题，网址，访问时间（年月日）。
\end{thebibliography}

% ==================== 附录：程序源代码 ====================
\appendix
\section{程序源代码}

\begin{verbatim}
# 在此粘贴可运行的程序代码（Python / MATLAB 等）
print("hello, cumcm")
\end{verbatim}

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
        "desc": "高教社杯全国大学生数学建模竞赛格式：承诺书/编号页/摘要页 + 三号黑体题目、四号黑体一级标题",
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
