# -*- coding: utf-8 -*-
"""
离线刷题网页自测脚本
=================================
1. 用 openpyxl 生成一份与爬虫输出同结构的测试题库 tests/sample_bank.xlsx
2. 用本机 Edge（无头模式）打开 web-practice/index.html
3. 注入题库文件，验证：导入数量、单选/多选/判断判分、错题本写入

运行：python tests/test_web.py
"""
import asyncio
import sys
from pathlib import Path

from openpyxl import Workbook

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = Path(__file__).resolve().parent / "sample_bank.xlsx"
INDEX_URI = (ROOT / "web-practice" / "index.html").as_uri()

HEADERS = ["课程名称", "章节名称", "题型", "题干",
           "选项A", "选项B", "选项C", "选项D", "选项E", "选项F",
           "参考答案", "解析"]


def make_sample_xlsx():
    """生成与爬虫输出完全同结构的测试题库"""
    wb = Workbook()
    ws = wb.active
    ws.title = "题库"
    ws.append(HEADERS)
    rows = [
        ["大学英语", "Unit1", "单选", "1+1等于（）", "1", "2", "3", "4", "", "", "B", "1+1=2，故选B"],
        ["大学英语", "Unit1", "多选", "下列属于水果的有（）", "苹果", "香蕉", "土豆", "西红柿", "", "", "AB", "苹果和香蕉是水果"],
        ["大学英语", "Unit1", "判断", "地球是圆的。", "正确", "错误", "", "", "", "", "A", "地球近似球体"],
        ["大学英语", "Unit2", "判断", "太阳从西边升起。", "正确", "错误", "", "", "", "", "B", "太阳从东边升起"],
    ]
    for r in rows:
        ws.append(r)
    wb.save(XLSX_PATH)
    print(f"已生成测试题库：{XLSX_PATH}（{len(rows)} 题）")


async def run():
    passed = 0
    failed = 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            failed += 1
            print(f"  [FAIL] {name}  {detail}")

    make_sample_xlsx()

    async with async_playwright() as p:
        print("启动本机 Edge（无头模式）...")
        browser = await p.chromium.launch(channel="msedge", headless=True)
        # 使用全新上下文，保证 localStorage 干净
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(INDEX_URI, wait_until="domcontentloaded")
        await page.wait_for_selector("#dropZone")

        # 1) 注入题库文件
        await page.set_input_files("#fileInput", str(XLSX_PATH))
        await page.wait_for_selector(".q-card")
        total = await page.text_content("#stTotal")
        check("导入题库显示 4 题", total.strip() == "4", total)
        cards = page.locator(".q-card")
        check("页面渲染 4 张题目卡片", await cards.count() == 4, str(await cards.count()))

        # 2) 单选判对：题1（1+1=？）点选项B（第2个）
        c1 = cards.nth(0)
        await c1.locator(".opt").nth(1).click()
        msg1 = (await c1.locator(".result-msg").text_content()).strip()
        check("单选点B判正确", "正确" in msg1, msg1)
        # 选项B高亮为正确色
        check("正确答案高亮", "correct" in (await c1.locator(".opt").nth(1).get_attribute("class")))

        # 3) 多选判对：题2 勾选A、B后提交
        c2 = cards.nth(1)
        await c2.locator(".opt").nth(0).click()  # A
        await c2.locator(".opt").nth(1).click()  # B
        await c2.locator("button:has-text('提交答案')").click()
        msg2 = (await c2.locator(".result-msg").text_content()).strip()
        check("多选AB提交判正确", "正确" in msg2, msg2)

        # 4) 判断判对：题3 点“正确”
        c3 = cards.nth(2)
        await c3.locator(".opt").nth(0).click()
        msg3 = (await c3.locator(".result-msg").text_content()).strip()
        check("判断点正确判对", "正确" in msg3, msg3)

        # 5) 判断判错：题4 点“正确”（应为“错误”），进入错题本
        c4 = cards.nth(3)
        await c4.locator(".opt").nth(0).click()
        msg4 = (await c4.locator(".result-msg").text_content()).strip()
        check("判断答错显示正确答案", "回答错误" in msg4 and "B" in msg4, msg4)
        wrong_count = await page.text_content("#wrongCount")
        check("错题本数量为 1", wrong_count.strip() == "1", wrong_count)

        # 6) 统计：已答4、正确3
        done = await page.text_content("#stDone")
        rate = await page.text_content("#stRate")
        check("已答 4 题", done.strip() == "4", done)
        check("正确率 75%", rate.strip() == "75%", rate)

        # 7) 题型筛选：点击“多选”只显示1题
        await page.locator("#toolbar .btn[data-filter='多选']").click()
        await page.wait_for_timeout(200)
        c_after = await page.locator(".q-card").count()
        check("筛选多选后显示 1 题", c_after == 1, str(c_after))

        # 8) 错题本视图：显示刚才答错的判断题
        await page.locator("#toolbar .btn[data-filter='wrong']").click()
        await page.wait_for_timeout(200)
        wrong_view = await page.locator(".q-card").count()
        check("错题本视图显示 1 题", wrong_view == 1, str(wrong_view))
        wrong_stem = await page.locator(".q-card .q-stem").first.text_content()
        check("错题本内容是答错的题", "太阳" in wrong_stem, wrong_stem)

        # 9) 错题本中答对后自动移出：回到全部，把该题答对
        await page.locator("#toolbar .btn[data-filter='all']").click()
        await page.wait_for_timeout(200)
        cards = page.locator(".q-card")
        c4b = cards.nth(3)
        await c4b.locator(".opt").nth(1).click()  # 点“错误” -> 正确
        await page.wait_for_timeout(200)
        wrong_count2 = await page.text_content("#wrongCount")
        check("答对后错题本清空", wrong_count2.strip() == "0", wrong_count2)

        await browser.close()

    print("=" * 50)
    print(f"测试结果：通过 {passed} 项，失败 {failed} 项")
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(run())
    sys.exit(0 if ok else 1)
