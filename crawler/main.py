# -*- coding: utf-8 -*-
"""
学习通（超星）习题采集爬虫
=================================================================
功能说明：
  1. 通过 Chrome DevTools Protocol（CDP）连接用户本机【已经打开并登录】的 Edge 浏览器，
     复用浏览器里已有的学习通登录会话 —— 程序本身【不实现任何登录逻辑】。
  2. 用户手动在 Edge 里打开目标习题页面（课程页面 / 章节测验 / 作业），复制地址栏 URL，
     粘贴给本程序；程序【只采集这一个 URL 页面】里的习题，
     不自动翻页、不遍历整个课程、不自动答题。
  3. 提取字段：课程名称、章节名称、题型（单选/多选/判断等）、题干、A~F 选项、
     参考答案、解析。
  4. 提取结果写入 output/日期_作业名称.xlsx（每次采集生成独立文件，不覆盖旧题库）。

兼容的页面结构：
  - 作业页面（mooc2/work/view 等）：题目容器为 .questionLi，
    题干 .qtContent、题型 .colorShallow、选项 .qtDetail li、
    正确答案 .rightAnswerContent、解析 .qtAnalysis。
  - 章节测验页面（exam-ans/examTest 等）：题目容器为 .TiMu，
    题干 .Zy_TItle_t / .Zy_TItle、选项 .Zy_ulTop li、
    答案 .marking_da 等、解析 .marking_exam 等。

运行前置条件（详见 README.md）：
  - 已用远程调试模式启动 Edge（msedge.exe --remote-debugging-port=9222），
    并在该 Edge 中手动完成学习通登录。
  - 已安装依赖：pip install -r requirements.txt

用法：
  python main.py                  # 交互式粘贴 URL
  python main.py "https://..."    # 直接传 URL 参数
"""

import asyncio
import base64
import logging
import random
import re
import sys
from datetime import datetime
from html import unescape as html_unescape
from pathlib import Path
from typing import Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from playwright.async_api import async_playwright

# ---------------------------------------------------------------------------
# 全局配置
# ---------------------------------------------------------------------------
# 本机 Edge 远程调试端口（启动 Edge 时使用 --remote-debugging-port=9222）
CDP_URL = "http://127.0.0.1:9222"

# 项目根目录（crawler 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 输出目录：存放题库 Excel
OUTPUT_DIR = PROJECT_ROOT / "output"
# 日志目录
LOG_DIR = PROJECT_ROOT / "logs"

# 页面加载后、滚动前的基础等待时间范围（秒）——防风控
WAIT_BASE_MIN = 2.0
WAIT_BASE_MAX = 3.5
# 每次滚动后的等待时间范围（秒）
WAIT_SCROLL_MIN = 1.2
WAIT_SCROLL_MAX = 2.2
# 最大滚动次数（只用于把当前页面的懒加载内容加载完，不是翻页）
MAX_SCROLL_TIMES = 6

# 题目容器候选（按优先级排列）：
#   作业页面 -> .questionLi；章节测验/考试 -> .TiMu；其他备用 -> .question 等
CONTAINER_PRIORITY = [".questionLi", ".TiMu", ".question", ".questLi"]

# 题型关键词 -> 统一题型名
TYPE_KEYWORDS = {
    "单选题": "单选",
    "多选题": "多选",
    "判断题": "判断",
    "填空题": "填空",
    "简答题": "简答",
    "名词解释题": "名词解释",
    "论述题": "论述",
    "计算题": "计算",
    "综合题": "综合",
    "问答题": "问答",
    "程序设计题": "编程",
    "翻译题": "翻译",
}

# 学习通字体加密（font-cxsecret）已知码点映射表。
# 学习通部分页面用自定义字体把题干汉字“乱码码点”渲染成正常字形，
# 爬虫拿到的 DOM 文本因此是乱码。本表是经过视觉核对的
# {加密码点: 真实汉字}。不同页面的字体可能不同，运行时先从页面动态
# 提取字体，内置表未覆盖的码点再用系统黑体自动匹配。
CX_FONT_MAP: Dict[int, str] = {
    0x6236: "关", 0x6299: "的", 0x629D: "达", 0x629E: "值", 0x62A3: "为",
    0x62A6: "学", 0x62A7: "数", 0x62A8: "法", 0x62A9: "是", 0x62AA: "合",
    0x62AE: "不", 0x62B0: "下", 0x62B2: "出", 0x62B3: "句", 0x62B6: "结",
    0x62B7: "语", 0x62B8: "果", 0x62BA: "中", 0x62BB: "行", 0x62BE: "则",
    0x62BF: "符", 0x62C0: "字", 0x62C1: "串", 0x62C3: "若", 0x62C4: "价",
    0x62C7: "等", 0x62CA: "计", 0x6473: "表", 0x66F3: "输", 0x6CAC: "列",
    0x7197: "正", 0x7832: "以", 0x79E5: "算", 0x83D7: "执", 0x9B26: "式",
}

# 判断题答案的“中文表述”会被归一化为这些标准值
TRUE_WORDS = ("正确", "对", "√", "是", "true", "t", "yes")
FALSE_WORDS = ("错误", "错", "×", "x", "否", "false", "f", "no")


def setup_logger() -> logging.Logger:
    """配置日志：同时输出到控制台和 logs/crawler_YYYYMMDD_HHMMSS.log"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("chaoxing_crawler")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # 控制台输出
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
    logger.addHandler(console)

    # 文件输出（UTF-8，避免中文乱码）
    log_file = LOG_DIR / f"crawler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(file_handler)
    return logger


logger = setup_logger()


# ---------------------------------------------------------------------------
# 文本 / 正则工具
# ---------------------------------------------------------------------------
def clean_text(text: str) -> str:
    """清理文本：去掉首尾空白、把连续空白折叠为单个空格"""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_type_from_title(title: str) -> Optional[str]:
    """从题干文本中识别题型，例如“（单选题）……”或“【单选题】……” -> “单选”"""
    if not title:
        return None
    # 支持中文/英文括号、方括号包裹的题型（学习通部分页面用【单选题】）
    m = re.search(
        r"[（(【]\s*(单选题|多选题|判断题|填空题|简答题|名词解释题|论述题|"
        r"计算题|综合题|问答题|程序设计题|翻译题)\s*[)）】]",
        title,
    )
    if m:
        return TYPE_KEYWORDS[m.group(1)]
    return None


def strip_question_no(stem: str) -> str:
    """去掉题干开头的题号，例如 “1. xxx” / “1、xxx” / “1 xxx” -> “xxx”"""
    # 先处理 “1. xxx / 1、xxx / 1：xxx”，再处理 “1 xxx / 1【单选题】xxx”
    s = re.sub(r"^\s*\d+\s*[.、．:：]\s*", "", stem)
    s = re.sub(r"^\s*\d+\s+(?=\S)", "", s)
    return s


def strip_type_tag(stem: str) -> str:
    """去掉题干开头的题型标签，例如 “（单选题）xxx” / “【单选题】xxx” -> “xxx”"""
    return re.sub(r"^\s*[（(【]\s*(?:单选题|多选题|判断题|填空题|简答题|名词解释题|"
                  r"论述题|计算题|综合题|问答题|程序设计题|翻译题)\s*[)）】]\s*", "", stem)


def normalize_answer(raw: str) -> str:
    """
    归一化参考答案：
      - 字母答案：去掉分隔符，统一为大写，例如 “a、b” -> “AB”
      - 判断题：中文“正确/错误”等原样保留
    """
    if not raw:
        return ""
    text = clean_text(raw)
    # 去掉答案前后多余的标点与“答案/正确答案/参考答案”等前缀
    text = re.sub(r"^(?:正确|参考)?答案\s*[:：]?\s*", "", text, flags=re.IGNORECASE)
    # 字母型答案：a、b / a,b / a;b / a b / AB 均归一化为 AB
    letters = re.findall(r"[A-Ha-h]", text)
    if letters:
        # 只保留有意义的字母（排除题干中偶然出现的字母，因此仅当文本较短时视为答案）
        if len(text) <= 12:
            return "".join(sorted(set(letter.upper() for letter in letters)))
    # 判断题中文答案：保留第一个有效词
    for word in TRUE_WORDS + FALSE_WORDS:
        if text.lower().startswith(word.lower()):
            return word
    return text


def parse_options(block_text: str) -> List[str]:
    """
    从文本中解析选项列表（兜底方案，DOM 提取失败时使用）。
    学习通选项常见格式：每行 “A 选项内容” 或 “A、选项内容”。
    返回按字母顺序（A,B,C...）排列的选项内容列表。
    """
    options = []
    pattern = re.compile(
        r"(?:^|[\n\r])"
        r"\s*([A-Ha-h])\s*[.、:：)]\s*"
        r"(.+?)(?=(?:[\n\r]\s*[A-Ha-h]\s*[.、:：)])|$)",
        re.S,
    )
    for m in pattern.finditer(block_text):
        letter = m.group(1).upper()
        content = clean_text(m.group(2))
        if content:
            options.append(content)

    if not options:
        for line in block_text.splitlines():
            line = clean_text(line)
            m = re.match(r"^([A-Ha-h])\s*[.、:：)]\s*(.+)$", line)
            if m:
                content = clean_text(m.group(2))
                if content:
                    options.append(content)
    return options


# ---------------------------------------------------------------------------
# 页面解析：定位题目容器
# ---------------------------------------------------------------------------
async def wait_random(lo: float, hi: float):
    """随机等待，模拟人工操作节奏，降低被平台风控识别的概率"""
    await asyncio.sleep(random.uniform(lo, hi))


async def _container_is_real_question(frame, sel: str) -> bool:
    """
    校验容器是否真的是题目块。
    作业页面的头部信息卡也带 .TiMu class（只有作业标题、题量等，没有题干/选项），
    必须排除这种“假题目块”。
    判断标准：容器内部存在题干或选项等题目特征元素。
    """
    try:
        el = frame.locator(sel).first
        if await el.count() == 0:
            return False
        # 题目特征选择器：题干 / 选项 / 题号+题型
        feature_sels = [".qtContent", ".Zy_TItle", ".Zy_TItle_t", ".qtDetail", ".mark_name"]
        for f in feature_sels:
            if await el.locator(f).count() > 0:
                return True
        return False
    except Exception:
        return False


async def find_question_container(page) -> tuple:
    """
    在主页面及其所有 iframe 中寻找包含题目的容器。
    学习通页面（章节测验/作业）的题目可能渲染在主页面或 iframe 内部，
    因此需要遍历所有 frame 与候选容器。
    返回 (目标frame, 容器选择器, 题目块数量)；找不到则返回 (None, None, 0)。
    """
    frames = [page.main_frame] + page.frames
    logger.info(f"当前页面共发现 {len(frames)} 个 frame（含主 frame）")
    best = (None, None, 0)
    for idx, frame in enumerate(frames):
        try:
            for sel in CONTAINER_PRIORITY:
                count = await frame.locator(sel).count()
                if count == 0:
                    continue
                # 校验该容器确实是题目块（过滤头部信息卡等干扰）
                if not await _container_is_real_question(frame, sel):
                    logger.debug(f"frame[{idx}] {sel} 存在 {count} 个但非题目块，跳过")
                    continue
                logger.info(f"在 frame[{idx}] 的 {sel} 中找到 {count} 个题目块")
                # 记录题目数量最多的容器（防止只找到少量干扰项）
                if count > best[2]:
                    best = (frame, sel, count)
        except Exception as exc:  # frame 可能已失效，跳过即可
            logger.debug(f"frame[{idx}] 检查失败: {exc}")
    if best[0] is None:
        return None, None, 0
    return best


# ---------------------------------------------------------------------------
# 页面解析：课程/章节名称
# ---------------------------------------------------------------------------
async def extract_meta(page, frame, url: str) -> Dict[str, str]:
    """
    提取课程名称与章节名称。
    作业页面（work/view）的标题“mark_title”通常是章节/作业名（如“第二章 选择题”），
    页面本身往往不显示课程名，此时课程名标为“未知课程”（可在 Excel 中手动补充）。
    """
    course_name = ""
    chapter_name = ""

    # 1) 作业/测验标题（mark_title 等）-> 章节名
    for sel in [".mark_title", ".colorfont", ".cur", ".qt_title"]:
        try:
            el = frame.locator(sel).first
            if await el.count() > 0:
                txt = clean_text(await el.inner_text())
                if txt and len(txt) < 80:
                    chapter_name = txt
                    break
        except Exception:
            continue

    # 1.5) 新版作业页（doHomeWorkNew）：正文形如 “第二章 单元测验\n题量: 16 满分: 100”
    if not chapter_name:
        try:
            body_text = await frame.locator("body").inner_text()
            m = re.search(r"^\s*([^\n]{1,50})\s*\n\s*题量\s*[:：]", body_text, re.M)
            if m:
                cand = clean_text(m.group(1))
                # 过滤“待完成/已完成/章节测验/测验”等状态/类型词
                if cand and cand not in ("待完成", "已完成", "章节测验", "测验", "考试"):
                    chapter_name = cand
        except Exception:
            pass

    # 2) 课程名候选：面包屑 / 课程名元素
    course_sels = [
        ".courseName", ".course-name", ".courseTitle", ".course-title",
        "#courseName", ".topTitle", ".nav-title",
        ".crumb", ".breadcrumb",
    ]
    for sel in course_sels:
        try:
            el = frame.locator(sel).first
            if await el.count() > 0:
                txt = clean_text(await el.inner_text())
                if txt and len(txt) < 80:
                    # 面包屑可能形如 “课程名 / 章节名”
                    parts = re.split(r"[/>›»|｜丨]", txt)
                    parts = [p.strip() for p in parts if p.strip()]
                    if len(parts) >= 2:
                        course_name = parts[0]
                        if not chapter_name:
                            chapter_name = parts[-1]
                    elif not course_name:
                        course_name = parts[0]
                    break
        except Exception:
            continue

    # 3) 页面标题兜底（排除无信息量的标题）
    if not course_name and not chapter_name:
        try:
            title = (await page.title() or "").strip()
            title = re.sub(r"[-_|丨]\s*(超星学习通|学习通|超星|泛雅平台).*$", "", title)
            title = title.strip(" _-|丨>›")
            # “作业详情”“测验”这类标题无信息量，跳过
            if title and title not in ("作业详情", "测验", "考试", "章节测验"):
                parts = re.split(r"[>›»|｜丨_-]", title)
                parts = [p.strip() for p in parts if p.strip()]
                if parts:
                    course_name = parts[0]
                    if len(parts) >= 2:
                        chapter_name = parts[-1]
        except Exception:
            pass

    if not course_name:
        course_name = "未知课程"
        # 从 URL 里带出 courseId 便于用户定位课程
        m = re.search(r"courseId[=/:](\d+)", url)
        if m:
            course_name = f"未知课程(courseId={m.group(1)})"
    if not chapter_name:
        chapter_name = "未知章节"
    if "未知课程" in course_name:
        logger.info("页面未显示课程名，已标记为“未知课程”，可在 Excel 中手动补充")
    return {"course": course_name, "chapter": chapter_name}


# ---------------------------------------------------------------------------
# 页面解析：题目提取
# ---------------------------------------------------------------------------
async def extract_stem(block) -> str:
    """提取题干：优先 .qtContent（作业页）与 .Zy_TItle_t / .Zy_TItle（测验页）"""
    for sel in [".qtContent", ".Zy_TItle_t", ".Zy_TItle"]:
        try:
            el = block.locator(sel).first
            if await el.count() > 0:
                stem = clean_text(await el.inner_text())
                if stem:
                    # 去掉题号前缀与题型标签（如 “1. (单选题) xxx”）
                    stem = strip_type_tag(strip_question_no(stem))
                    return stem
        except Exception:
            continue
    return ""


async def extract_type(block, block_text: str, stem: str) -> str:
    """提取题型：题干标记 -> 题型标签元素 -> input 类型推断 -> 选项特征推断"""
    # 1) 题干文本中的题型标签（注意：题干可能已被剥掉标签，需同时检查整块文本前段）
    t = extract_type_from_title(stem)
    if not t:
        t = extract_type_from_title(block_text[:120])
    if t:
        return t
    # 2) 题型标签元素（作业页 .colorShallow 内如 “(单选题)”）
    for sel in [".colorShallow", ".type-tag", ".q-type"]:
        try:
            el = block.locator(sel).first
            if await el.count() > 0:
                tag = clean_text(await el.inner_text())
                t = extract_type_from_title(tag)
                if t:
                    return t
        except Exception:
            continue
    # 3) input 类型推断
    try:
        if await block.locator("input[type=checkbox]").count() > 0:
            return "多选"
        if await block.locator("input[type=radio]").count() > 0:
            return "单选"
    except Exception:
        pass
    # 4) 选项特征：判断 / 对错
    opts = parse_options(block_text)
    if opts:
        joined = "".join(opts)
        if ("正确" in joined and "错误" in joined) or ("对" in joined and "错" in joined):
            return "判断"
    return "未知"


async def extract_options(block, block_text: str) -> Dict[str, str]:
    """提取选项，返回 {A: 内容, B: 内容, ...}"""
    options: Dict[str, str] = {}
    # 1) DOM 提取：优先作业页 .qtDetail li，其次测验页 .Zy_ulTop li
    li_candidates = [".qtDetail li", ".Zy_ulTop li", ".Zy_ulTop ul li", "ul li.fl"]
    for sel in li_candidates:
        try:
            li_list = block.locator(sel)
            n = await li_list.count()
            if n > 0:
                options = {}
                for idx in range(n):
                    li = li_list.nth(idx)
                    txt = clean_text(await li.inner_text())
                    m = re.match(r"^([A-Ha-h])\s*[.、:：)]?\s*(.*)$", txt, re.S)
                    if m:
                        letter = m.group(1).upper()
                        content = clean_text(m.group(2))
                        if content:
                            options[letter] = content
                if len(options) >= 2:
                    return options
        except Exception:
            continue
    # 2) 文本正则兜底
    if len(options) < 2:
        parsed = parse_options(block_text)
        for idx, content in enumerate(parsed):
            options[chr(ord("A") + idx)] = content
    return options


async def extract_answer(block, block_text: str, qtype: str, options: Dict[str, str]) -> str:
    """提取参考答案：class 优先，正则兜底"""
    # 1) 常见答案 class（作业页 .rightAnswerContent，测验页 .marking_da 等）
    answer_selectors = [
        ".rightAnswerContent",
        ".marking_da",
        ".answer, .answers",
        ".da, .daan",
        ".correct_answer, .Correct",
        ".zq, .correct",
        ".key, .answerKey",
    ]
    for sel in answer_selectors:
        try:
            el = block.locator(sel).first
            if await el.count() > 0:
                txt = clean_text(await el.inner_text())
                if txt:
                    norm = normalize_answer(txt)
                    if norm:
                        return norm
        except Exception:
            continue

    # 2) 正则：从整块文本中找 “正确答案：B” / “参考答案：AB” / “答案：正确”
    patterns = [
        r"(?:正确|参考)?答案\s*[:：]\s*([A-Ha-h][A-Ha-h,、，;；和\s]*)",
        r"(?:正确|参考)?答案\s*[:：]\s*(正确|错误|对|错|√|×)",
    ]
    for pat in patterns:
        m = re.search(pat, block_text, re.IGNORECASE)
        if m:
            norm = normalize_answer(m.group(1))
            if norm:
                return norm
    return ""


async def extract_analysis(block, block_text: str) -> str:
    """提取解析（讲解）：class 优先，正则兜底"""
    analysis_selectors = [
        ".qtAnalysis",
        ".marking_exam",
        ".analysis, .parse, .explain, .jieshi",
        ".jx, .fjw, .analysis_text",
    ]
    for sel in analysis_selectors:
        try:
            el = block.locator(sel).first
            if await el.count() > 0:
                txt = clean_text(await el.inner_text())
                if txt:
                    # 去掉“答案解析：”等前缀
                    txt = re.sub(r"^(?:答案解析|解析|讲解)\s*[:：]?\s*", "", txt)
                    return txt[:500]
        except Exception:
            continue
    m = re.search(r"(?:解析|答案解析|讲解)\s*[:：]?\s*(.+)", block_text, re.S)
    if m:
        return clean_text(m.group(1))[:500]
    return ""


# ---------------------------------------------------------------------------
# 学习通字体加密（font-cxsecret）解密
# ---------------------------------------------------------------------------
# 全局缓存：{字体哈希: {加密码点: 真实汉字}}，同一字体只匹配一次
_CX_FONT_CACHE: Dict[str, Dict[int, str]] = {}


def decode_cx_text(text: str, font_map: Dict[int, str]) -> str:
    """把文本中的“加密码点”替换为真实汉字，并反转义 HTML 实体（&lt; -> <）。"""
    if not text:
        return text
    # 1) 先反转义 HTML 实体：学习通题目中 “&lt;” 是双重转义，浏览器显示字面，
    #    题库里还原为 < > & 更易读
    text = html_unescape(text)
    # 2) 再替换字体加密码点
    if font_map:
        text = "".join(font_map.get(ord(c), c) for c in text)
    return text


def _render_cx_glyph(face, cp: int, size: int = 96, gsize: int = 78):
    """用 freetype 渲染单个码点为灰度位图（等比例缩放 + 居中），供字形匹配"""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    try:
        face.load_char(cp, 0x40 | 0x8000)  # FT_LOAD_RENDER | FT_LOAD_TARGET_NORMAL
        g = face.glyph
        bmp = g.bitmap
        if bmp.width == 0 or bmp.rows == 0:
            return None
        buf = np.array(bmp.buffer, dtype=np.uint8).reshape(bmp.rows, bmp.width)
        scale = gsize / max(bmp.width, bmp.rows)
        nw, nh = max(1, int(round(bmp.width * scale))), max(1, int(round(bmp.rows * scale)))
        pil = Image.fromarray(buf).resize((nw, nh), Image.LANCZOS)
        arr = np.asarray(pil, dtype=np.float32)
        canvas = np.zeros((size, size), dtype=np.float32)
        y0, x0 = (size - nh) // 2, (size - nw) // 2
        canvas[y0:y0 + nh, x0:x0 + nw] = arr
        mx = canvas.max()
        if mx > 0:
            canvas /= mx
        return canvas
    except Exception:
        return None


def _auto_match_glyphs(secret_ttf_path: Path, unknown_codes: List[int]) -> Dict[int, str]:
    """
    用系统黑体（微软雅黑 msyh.ttc）对未知码点做字形渲染比对，识别真实汉字。
    返回 {加密码点: 汉字}。依赖 freetype-py / numpy / Pillow，缺失时返回空表。
    """
    import os
    try:
        import freetype
        import numpy as np
        from PIL import Image  # noqa: F401  确保 PIL 可用
    except ImportError:
        logger.warning("未安装 freetype-py/numpy/Pillow，无法自动识别新加密字，"
                       "请执行：pip install freetype-py numpy pillow")
        return {}

    # 候选字库：系统黑体（Windows 微软雅黑）。若当前系统没有这些字体
    # （如 macOS/Linux），自动识别会失败并回退到内置 CX_FONT_MAP 映射表。
    msyh = r"C:\Windows\Fonts\msyh.ttc"
    if not os.path.exists(msyh):
        # 备选：其他黑体字体
        for alt in (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\simhei.ttf",
                    r"C:\Windows\Fonts\Deng.ttf"):
            if os.path.exists(alt):
                msyh = alt
                break
        else:
            logger.warning("未找到系统黑体字体（msyh.ttc），无法自动识别新加密字")
            return {}

    size = 96
    try:
        # 候选字库：GB2312 一级汉字（约 3800 个常用字）
        candidates = set()
        for b in range(0xB0, 0xD8):
            for g in range(0xA1, 0xFE):
                try:
                    candidates.add(bytes([b, g]).decode("gb2312"))
                except Exception:
                    pass
        cand_cps = sorted(ord(c) for c in candidates if c)

        lib_face = freetype.Face(msyh)
        lib_face.set_pixel_sizes(size, size)
        lib = {}
        for cp in cand_cps:
            img = _render_cx_glyph(lib_face, cp, size)
            if img is not None:
                lib[cp] = (img, float(img.sum()))

        secret_face = freetype.Face(str(secret_ttf_path))
        secret_face.set_pixel_sizes(size, size)

        result = {}
        for cp in unknown_codes:
            q = _render_cx_glyph(secret_face, cp, size)
            if q is None:
                continue
            qsum = float(q.sum())
            best_cp, best_score = None, 1e18
            for cand, (img, s) in lib.items():
                if abs(s - qsum) > qsum * 0.20:
                    continue
                score = float(np.abs(img - q).sum())
                if score < best_score:
                    best_score, best_cp = score, cand
            if best_cp:
                result[cp] = chr(best_cp)
        return result
    except Exception as exc:
        logger.warning(f"自动识别加密字失败：{exc}")
        return {}


async def build_cx_font_map(frame) -> Dict[int, str]:
    """
    从页面 CSS 中提取 font-cxsecret 字体，建立“加密码点 -> 真实汉字”映射。
    策略：内置表优先；字体中有未知码点时用系统黑体自动匹配；
    同一字体哈希的结果会缓存，避免重复计算。
    """
    try:
        css = await frame.evaluate("""
            Array.from(document.styleSheets).flatMap(s => {
                try { return Array.from(s.cssRules || []); } catch(e) { return []; }
            }).filter(r => r.cssText.includes('font-cxsecret'))
            .map(r => r.cssText).join('\\n')
        """)
        m = re.search(r"base64,([A-Za-z0-9+/=]+)", css or "")
        if not m:
            return dict(CX_FONT_MAP)
        import hashlib
        import io
        data = base64.b64decode(m.group(1))
        fhash = hashlib.sha256(data).hexdigest()[:16]
        if fhash in _CX_FONT_CACHE:
            return _CX_FONT_CACHE[fhash]

        from fontTools.ttLib import TTFont
        font = TTFont(io.BytesIO(data))
        codes = sorted(font.getBestCmap().keys())
        font_map = {cp: CX_FONT_MAP[cp] for cp in codes if cp in CX_FONT_MAP}
        unknown = [cp for cp in codes if cp not in CX_FONT_MAP]
        if unknown:
            logger.info(f"字体中有 {len(unknown)} 个未收录码点，正在用系统黑体自动识别 ...")
            ttf_tmp = OUTPUT_DIR / "_cxsecret_tmp.ttf"
            ttf_tmp.write_bytes(data)
            auto = _auto_match_glyphs(ttf_tmp, unknown)
            ttf_tmp.unlink(missing_ok=True)
            font_map.update(auto)
            if auto:
                logger.info(f"自动识别新增 {len(auto)} 个字")
        _CX_FONT_CACHE[fhash] = font_map
        return font_map
    except Exception as exc:
        logger.warning(f"提取加密字体失败（使用内置映射表）：{exc}")
        return dict(CX_FONT_MAP)


async def parse_questions(frame, container_sel: str, meta: Dict[str, str], url: str,
                          font_map: Optional[Dict[int, str]] = None) -> List[Dict]:
    """
    解析指定容器中的所有题目。
    返回题目字典列表，字段：
      course / chapter / qtype / stem / options(dict A~F) / answer / analysis
    font_map: 字体加密解码映射（无加密时传空字典）
    """
    questions: List[Dict] = []
    blocks = frame.locator(container_sel)
    total = await blocks.count()
    logger.info(f"使用容器 {container_sel}，开始解析 {total} 个题目 ...")
    font_map = font_map or {}

    def dec(s: str) -> str:
        """统一解码函数：文本经过加密字替换"""
        return decode_cx_text(s, font_map)

    for i in range(total):
        block = blocks.nth(i)
        try:
            # 取整块文本用于正则分析（选项、答案、解析都在其中）
            block_text = await block.inner_text()

            # 题干
            stem = await extract_stem(block)
            if not stem:
                stem = clean_text(strip_type_tag(block_text))
                stem = strip_question_no(stem)[:200]

            # 题型（注意：题干乱码时先解码再识别题型标签）
            qtype = await extract_type(block, dec(block_text)[:200], dec(stem))

            # 选项
            options = await extract_options(block, block_text)

            # 参考答案
            answer = await extract_answer(block, block_text, qtype, options)

            # 解析
            analysis = await extract_analysis(block, block_text)

            # 所有文本字段统一解码（还原字体加密的乱码）
            stem = dec(stem)
            options = {k: dec(v) for k, v in options.items()}
            answer = dec(answer)
            analysis = dec(analysis)

            questions.append(
                {
                    "course": meta["course"],
                    "chapter": meta["chapter"],
                    "qtype": qtype or "未知",
                    "stem": stem,
                    "options": options,
                    "answer": answer,
                    "analysis": analysis,
                }
            )
        except Exception as exc:
            logger.warning(f"第 {i + 1} 题解析失败: {exc}")

        # 每题之间小停顿，模拟人工阅读节奏
        await wait_random(0.3, 0.8)

    logger.info(f"成功解析 {len(questions)} / {total} 题")
    return questions


# ---------------------------------------------------------------------------
# Excel 导出
# ---------------------------------------------------------------------------
EXCEL_HEADERS = ["课程名称", "章节名称", "题型", "题干",
                 "选项A", "选项B", "选项C", "选项D", "选项E", "选项F",
                 "参考答案", "解析"]


def safe_filename(name: str) -> str:
    """清理文件名中的非法字符（Windows 不允许 \\ / : * ? \" < > | 等），并限制长度"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "", str(name))
    name = name.strip(" .")
    return name[:60]


def build_output_basename(questions: List[Dict]) -> str:
    """
    生成输出文件的“基础名”（不含扩展名），格式：日期_作业名称。
    命名优先级：章节名称 -> 课程名称 -> “习题”兜底。
    若同名文件（xlsx/txt/docx 任一）已存在（同一天重复采集），追加时分秒后缀。
    三种格式共用同一基础名，方便配套管理。
    """
    date_str = datetime.now().strftime("%Y%m%d")
    base = "习题"
    if questions:
        q0 = questions[0]
        base = (safe_filename(q0.get("chapter") or "")
                or safe_filename(q0.get("course") or "")
                or "习题")
    name = f"{date_str}_{base}"
    exists = any((OUTPUT_DIR / f"{name}{ext}").exists()
                 for ext in (".xlsx", ".txt", ".docx"))
    if exists:
        name = f"{date_str}_{base}_{datetime.now().strftime('%H%M%S')}"
    return name


def format_questions_text(questions: List[Dict]) -> str:
    """
    把题目列表格式化为稳定的结构化文本（TXT 与 Word 共用，刷题网页按此格式解析）。
    格式示例：
        课程名称：xxx
        章节名称：xxx
        采集时间：xxx
        题目数量：N
        ================================================

        【1】【单选】
        题干文本
        A. 选项内容
        B. 选项内容
        【参考答案】A
        【解析】解析内容
    """
    lines = []
    if questions:
        lines.append(f"课程名称：{questions[0].get('course', '')}")
        lines.append(f"章节名称：{questions[0].get('chapter', '')}")
    lines.append(f"采集时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"题目数量：{len(questions)}")
    lines.append("=" * 50)
    for idx, q in enumerate(questions, start=1):
        lines.append("")
        lines.append(f"【{idx}】【{q.get('qtype', '未知')}】")
        lines.append(q.get("stem", ""))
        opts = q.get("options", {})
        for letter in "ABCDEFGH":
            content = opts.get(letter)
            if content:
                lines.append(f"{letter}. {content}")
        if q.get("answer"):
            lines.append(f"【参考答案】{q['answer']}")
        if q.get("analysis"):
            lines.append(f"【解析】{q['analysis']}")
    return "\n".join(lines)


def export_txt(questions: List[Dict], basename: Optional[str] = None) -> Path:
    """把题目列表写入 output/日期_作业名称.txt（UTF-8 带 BOM，记事本打开不乱码）"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{basename or build_output_basename(questions)}.txt"
    try:
        # utf-8-sig：带 BOM，Windows 记事本/Excel 双击打开均不乱码
        out_path.write_text(format_questions_text(questions), encoding="utf-8-sig")
    except PermissionError:
        backup = OUTPUT_DIR / f"{out_path.stem}_{datetime.now().strftime('%H%M%S')}.txt"
        logger.warning(f"TXT 文件被占用，已改存为：{backup.name}")
        backup.write_text(format_questions_text(questions), encoding="utf-8-sig")
        out_path = backup
    return out_path


def export_word(questions: List[Dict], basename: Optional[str] = None) -> Path:
    """把题目列表写入 output/日期_作业名称.docx（Word 文档，加粗排版）"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from docx import Document
        from docx.shared import Pt
        from docx.oxml.ns import qn
    except ImportError:
        logger.error("未安装 python-docx，无法导出 Word。请执行：pip install python-docx")
        return Path()

    out_path = OUTPUT_DIR / f"{basename or build_output_basename(questions)}.docx"
    try:
        doc = Document()
        # 全局中文字体（宋体），避免 Word 打开中文乱码
        style = doc.styles["Normal"]
        style.font.name = "宋体"
        style.font.size = Pt(11)
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

        # 文档标题
        if questions:
            title = f"{questions[0].get('course', '')} - {questions[0].get('chapter', '')}"
        else:
            title = "学习通习题题库"
        doc.add_heading(title, level=0)
        doc.add_paragraph(f"采集时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        doc.add_paragraph(f"题目数量：{len(questions)}")

        # 逐题写入（文本格式与 TXT 完全一致，网页可统一解析）
        for idx, q in enumerate(questions, start=1):
            p = doc.add_paragraph()
            run = p.add_run(f"【{idx}】【{q.get('qtype', '未知')}】{q.get('stem', '')}")
            run.bold = True
            opts = q.get("options", {})
            for letter in "ABCDEFGH":
                content = opts.get(letter)
                if content:
                    doc.add_paragraph(f"{letter}. {content}")
            if q.get("answer"):
                ap = doc.add_paragraph()
                r = ap.add_run(f"【参考答案】{q['answer']}")
                r.bold = True
            if q.get("analysis"):
                doc.add_paragraph(f"【解析】{q['analysis']}")

        doc.save(out_path)
    except PermissionError:
        backup = OUTPUT_DIR / f"{out_path.stem}_{datetime.now().strftime('%H%M%S')}.docx"
        logger.warning(f"Word 文件被占用，已改存为：{backup.name}")
        out_path = backup
        doc.save(out_path)
    return out_path


def export_excel(questions: List[Dict], basename: Optional[str] = None) -> Path:
    """把题目列表写入 output/日期_作业名称.xlsx，返回文件路径（每次采集生成独立文件）"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "题库"

    # 表头
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill("solid", fgColor="4472C4")
    for col, header in enumerate(EXCEL_HEADERS, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # 数据行
    for r, q in enumerate(questions, start=2):
        opts = q.get("options", {})
        row = [
            q.get("course", ""),
            q.get("chapter", ""),
            q.get("qtype", ""),
            q.get("stem", ""),
            opts.get("A", ""),
            opts.get("B", ""),
            opts.get("C", ""),
            opts.get("D", ""),
            opts.get("E", ""),
            opts.get("F", ""),
            q.get("answer", ""),
            q.get("analysis", ""),
        ]
        for c, value in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=value)
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    # 列宽与冻结首行
    col_widths = [24, 24, 10, 60, 30, 30, 30, 30, 18, 18, 12, 50]
    for idx, width in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = "A2"

    out_path = OUTPUT_DIR / f"{basename or build_output_basename(questions)}.xlsx"
    try:
        wb.save(out_path)
    except PermissionError:
        # 文件恰好被占用（极少见，文件名含日期基本不会冲突）：追加时分秒重试
        backup = OUTPUT_DIR / f"{out_path.stem}_{datetime.now().strftime('%H%M%S')}.xlsx"
        logger.warning(f"文件被其他程序占用，已改存为：{backup.name}")
        wb.save(backup)
        out_path = backup
    return out_path


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
async def crawl_url(url: str) -> int:
    """
    采集单个 URL 页面中的习题，写入 Excel。
    返回采集到的题目数量。
    """
    async with async_playwright() as p:
        logger.info(f"正在连接本机 Edge 调试端口 {CDP_URL} ...")
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as exc:
            logger.error(
                f"连接 Edge 失败：{exc}\n"
                f"请确认已用远程调试模式启动 Edge（详见 README.md），"
                f"或双击 start_edge_debug.bat 一键启动。"
            )
            return 0

        # 复用已有浏览器上下文（含学习通登录 Cookie）
        if not browser.contexts:
            logger.error("调试端口上没有可用的浏览器上下文，请确认 Edge 已登录学习通")
            await browser.close()
            return 0
        context = browser.contexts[0]
        logger.info(f"已复用 Edge 登录会话（contexts={len(browser.contexts)}）")

        # 新建一个标签页打开目标 URL（不干扰用户已打开的页面）
        page = await context.new_page()
        try:
            logger.info(f"正在打开页面：{url}")
            await page.goto(url, timeout=60_000, wait_until="domcontentloaded")
        except Exception as exc:
            logger.error(f"打开页面失败：{exc}")
            await page.close()
            await browser.close()
            return 0

        # 等待页面与 iframe 内容渲染
        await wait_random(WAIT_BASE_MIN, WAIT_BASE_MAX)

        # 温和滚动，把当前页面懒加载的题目加载出来（不是翻页，仅本页内容）
        for _ in range(MAX_SCROLL_TIMES):
            await page.mouse.wheel(0, 1200)
            await wait_random(WAIT_SCROLL_MIN, WAIT_SCROLL_MAX)
            # 检查题目容器是否出现，出现即可提前停止滚动
            f, sel, cnt = await find_question_container(page)
            if f is not None and cnt > 0:
                break

        # 定位包含题目的容器
        frame, container_sel, total = await find_question_container(page)
        if frame is None or total == 0:
            logger.error("未找到题目。可能原因：")
            logger.error("  - 该页面不是章节测验/作业页面，或题目尚未加载完成")
            logger.error("  - 学习通改版导致 DOM 结构变化，请把页面 URL 反馈给开发者")
            title = await page.title()
            logger.error(f"页面标题：{title}")
            logger.error(f"页面 URL：{page.url}")
            await page.close()
            await browser.close()
            return 0

        # 提取课程/章节信息并解析题目
        meta = await extract_meta(page, frame, url)
        # 检测页面字体加密并建立解码映射（正常页面自动跳过）
        font_map = await build_cx_font_map(frame)
        if font_map:
            logger.info(f"检测到字体加密，已建立 {len(font_map)} 条解码映射")
            meta = {k: decode_cx_text(v, font_map) for k, v in meta.items()}
        logger.info(f"课程：{meta['course']} | 章节：{meta['chapter']}")
        questions = await parse_questions(frame, container_sel, meta, url, font_map)

        await page.close()
        await browser.close()

        if not questions:
            logger.error("解析到 0 题，未生成题库文件。")
            return 0

        # 同时导出 Excel / TXT / Word 三种格式（同一基础名，日期_作业名称）
        base = build_output_basename(questions)
        excel_path = export_excel(questions, base)
        txt_path = export_txt(questions, base)
        word_path = export_word(questions, base)
        logger.info("=" * 60)
        logger.info(f"采集完成：共 {len(questions)} 题，已导出 3 种格式：")
        logger.info(f"  Excel：{excel_path}")
        logger.info(f"  TXT  ：{txt_path}")
        logger.info(f"  Word ：{word_path}")
        logger.info("=" * 60)
        return len(questions)


async def main():
    # 解析 URL：优先命令行参数，否则交互输入
    url = ""
    if len(sys.argv) > 1:
        url = sys.argv[1].strip()
    else:
        try:
            url = input("请粘贴要采集的学习通习题页面 URL（回车开始）：").strip()
        except EOFError:
            url = ""

    if not url:
        logger.error("未输入 URL，程序退出。")
        return

    # 校验 URL 基本合法性
    if not url.startswith(("http://", "https://")):
        logger.warning("URL 格式异常，仍将尝试访问。")
    if "chaoxing.com" not in url:
        logger.warning("该 URL 不是学习通（chaoxing.com）域名，解析可能失败。")

    count = await crawl_url(url)
    if count == 0:
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("用户中断，程序退出。")
        sys.exit(130)
    except Exception as exc:
        logger.exception(f"程序发生未预期异常：{exc}")
        sys.exit(1)
