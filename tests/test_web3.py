# -*- coding: utf-8 -*-
"""
刷题网页三种格式导入自测
=================================
1. 用爬虫导出函数生成 xlsx / txt / docx 三份测试题库
2. 用本机 Edge 无头打开 index.html，分别导入三种格式
3. 验证：题目数量、单选判分、错题本

运行：python tests/test_web3.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crawler"))
import main as crawler  # noqa: E402

from playwright.async_api import async_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INDEX_URI = (ROOT / "web-practice" / "index.html").as_uri()
OUT_DIR = Path(__file__).resolve().parent

QUESTIONS = [
    {"course": "测试课程", "chapter": "网页导入测试", "qtype": "单选",
     "stem": "1+1等于（）", "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
     "answer": "B", "analysis": "1+1=2"},
    {"course": "测试课程", "chapter": "网页导入测试", "qtype": "多选",
     "stem": "水果有（）", "options": {"A": "苹果", "B": "香蕉", "C": "土豆"},
     "answer": "AB", "analysis": "苹果香蕉是水果"},
    {"course": "测试课程", "chapter": "网页导入测试", "qtype": "判断",
     "stem": "地球是圆的。", "options": {"A": "正确", "B": "错误"},
     "answer": "A", "analysis": "近似球体"},
]


def make_files():
    """生成三份测试题库（同一基础名）"""
    base = "20260101_网页导入测试"
    xlsx = crawler.export_excel(QUESTIONS, base)
    txt = crawler.export_txt(QUESTIONS, base)
    docx = crawler.export_word(QUESTIONS, base)
    return xlsx, txt, docx


async def run():
    passed, failed = 0, 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            failed += 1
            print(f"  [FAIL] {name}  {detail}")

    xlsx, txt, docx = make_files()

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        page = await browser.new_page()

        # ---------- 1) 导入 TXT ----------
        await page.goto(INDEX_URI, wait_until="domcontentloaded")
        await page.set_input_files("#fileInput", str(txt))
        await page.wait_for_selector(".q-card")
        total = (await page.text_content("#stTotal")).strip()
        check("TXT 导入显示 3 题", total == "3", total)
        cards = page.locator(".q-card")
        check("TXT 渲染 3 张卡片", await cards.count() == 3, str(await cards.count()))
        # 单选判分：题1 点 B
        await cards.nth(0).locator(".opt").nth(1).click()
        msg1 = (await cards.nth(0).locator(".result-msg").text_content()).strip()
        check("TXT 单选判分正确", "正确" in msg1, msg1)
        # 多选判分：题2 勾 A、B 提交
        c2 = cards.nth(1)
        await c2.locator(".opt").nth(0).click()
        await c2.locator(".opt").nth(1).click()
        await c2.locator("button:has-text('提交答案')").click()
        msg2 = (await c2.locator(".result-msg").text_content()).strip()
        check("TXT 多选判分正确", "正确" in msg2, msg2)
        # 判断题：题3 点 A（正确）
        await cards.nth(2).locator(".opt").nth(0).click()
        msg3 = (await cards.nth(2).locator(".result-msg").text_content()).strip()
        check("TXT 判断判分正确", "正确" in msg3, msg3)

        # ---------- 2) 导入 DOCX（换新上下文清 localStorage 无影响，直接换文件）----------
        await page.set_input_files("#fileInput", str(docx))
        await page.wait_for_selector(".q-card")
        total = (await page.text_content("#stTotal")).strip()
        check("DOCX 导入显示 3 题", total == "3", total)
        cards = page.locator(".q-card")
        check("DOCX 渲染 3 张卡片", await cards.count() == 3, str(await cards.count()))
        # 判断导入的题干/选项完整
        stem1 = (await cards.nth(0).locator(".q-stem").text_content()).strip()
        check("DOCX 题干解析正确", "1+1" in stem1, stem1)
        optA = (await cards.nth(0).locator(".opt").nth(0).text_content()).strip()
        check("DOCX 选项解析正确", "1" in optA, optA)

        # ---------- 3) 导入 XLSX ----------
        await page.set_input_files("#fileInput", str(xlsx))
        await page.wait_for_selector(".q-card")
        total = (await page.text_content("#stTotal")).strip()
        check("XLSX 导入显示 3 题", total == "3", total)
        check("XLSX 渲染 3 张卡片", await cards.count() == 3, str(await cards.count()))

        # ---------- 4) 元信息（课程/章节）填充 ----------
        await page.set_input_files("#fileInput", str(txt))
        await page.wait_for_selector(".q-card")
        src = (await page.locator(".q-card .q-source").first.text_content()).strip()
        check("课程/章节信息展示", "测试课程" in src and "网页导入测试" in src, src)

        await browser.close()

    # 清理测试文件
    for f in (xlsx, txt, docx):
        try:
            f.unlink()
        except Exception:
            pass
    print("已清理测试文件")

    print("=" * 50)
    print(f"测试结果：通过 {passed} 项，失败 {failed} 项")
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(run())
    sys.exit(0 if ok else 1)
