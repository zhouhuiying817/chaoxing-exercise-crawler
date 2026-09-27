# -*- coding: utf-8 -*-
"""一次性生成 samples/ 脱敏示例题库（不进入 Git 追踪？——不，samples 要入库）
生成：示例_第一章 Python 入门.xlsx/.txt/.docx + _图片/formula01.png、formula02.png
题目为虚构示例，无任何真实用户数据，可直接用于体验刷题网页。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crawler"))
import main as crawler  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
BASE = "示例_第一章 Python 入门"
IMG_DIR = SAMPLES / f"{BASE}_图片"
IMG_DIR.mkdir(parents=True, exist_ok=True)


def make_formula(path: Path, text: str):
    """用系统黑体渲染一行数学表达式为 PNG（模拟学习通公式截图）"""
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 60)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10), "white"))
    bbox = probe.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0] + 48, bbox[3] - bbox[1] + 48
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    d.text((24 - bbox[0], 24 - bbox[1]), text, font=font, fill="black")
    img.save(path)


make_formula(IMG_DIR / "formula01.png", "y = 2x\u00b2 + 1")      # 题干附图
make_formula(IMG_DIR / "formula02.png", "y = 2\u00d79 + 1 = 19")  # 解析附图

# 题目数据（图片占位符 [[IMG:文件名]] 为 download_media 之后的形式）
questions = [
    {
        "course": "Python 程序设计基础（示例）", "chapter": "第一章 Python 入门",
        "qtype": "单选", "stem": "表达式 2**3 的值为（）",
        "options": {"A": "6", "B": "8", "C": "9", "D": "4"},
        "answer": "B", "analysis": "2**3 表示 2 的 3 次方，结果为 8。",
    },
    {
        "course": "Python 程序设计基础（示例）", "chapter": "第一章 Python 入门",
        "qtype": "单选",
        "stem": "已知二次函数 y=2x\u00b2+1[[IMG:formula01.png]]，当 x=3 时 y 的值为（）",
        "options": {"A": "17", "B": "19", "C": "21", "D": "23"},
        "answer": "B",
        "analysis": "将 x=3 代入计算[[IMG:formula02.png]]：y=2\u00d79+1=19。",
    },
    {
        "course": "Python 程序设计基础（示例）", "chapter": "第一章 Python 入门",
        "qtype": "多选", "stem": "下列哪些是 Python 合法的变量名（）",
        "options": {"A": "my_var", "B": "1var", "C": "_name", "D": "def"},
        "answer": "AC",
        "analysis": "变量名不能以数字开头（排除 B）；def 是关键字，不能用作变量名（排除 D）。",
    },
    {
        "course": "Python 程序设计基础（示例）", "chapter": "第一章 Python 入门",
        "qtype": "判断", "stem": "Python 中列表（list）是可变类型。（）",
        "options": {"A": "正确", "B": "错误"},
        "answer": "正确", "analysis": "列表支持增删改元素，属于可变对象。",
    },
    {
        "course": "Python 程序设计基础（示例）", "chapter": "第一章 Python 入门",
        "qtype": "判断", "stem": "Python 中字符串（str）是不可变类型。（）",
        "options": {"A": "正确", "B": "错误"},
        "answer": "正确",
        "analysis": "字符串一旦创建不可修改，任何修改都会生成新对象。",
    },
    {
        "course": "Python 程序设计基础（示例）", "chapter": "第一章 Python 入门",
        "qtype": "单选", "stem": "len(\"学习通\") 的返回值是（）",
        "options": {"A": "2", "B": "3", "C": "4", "D": "5"},
        "answer": "B", "analysis": "len() 统计字符个数，“学习通”包含 3 个汉字。",
    },
]

# 把导出目录指向 samples/（模块内 OUTPUT_DIR 是全局变量，直接替换即可）
crawler.OUTPUT_DIR = SAMPLES
excel = crawler.export_excel(questions, BASE)
txt = crawler.export_txt(questions, BASE)
word = crawler.export_word(questions, BASE)
print("生成完成：")
print(" ", excel)
print(" ", txt)
print(" ", word)
print(" ", IMG_DIR)
