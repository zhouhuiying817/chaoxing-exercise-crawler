# -*- coding: utf-8 -*-
"""
离线刷题网页自测：乱序刷题 + 导出错题
=====================================
1. 导入题库（4 题）后点「乱序」：按钮状态切换、题目顺序被打乱
2. 再次点「乱序」：顺序恢复为导入时的原始顺序
3. 答错一题进错题本后点「导出错题」：触发 TXT 文件下载（文件名以“错题_”开头）

运行：python tests/test_web4.py（需要本机 Edge）
"""
import asyncio
import sys
from pathlib import Path

from openpyxl import Workbook

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = Path(__file__).resolve().parent / "sample_bank4.xlsx"
INDEX_URI = (ROOT / "web-practice" / "index.html").as_uri()

HEADERS = ["课程名称", "章节名称", "题型", "题干",
           "选项A", "选项B", "选项C", "选项D", "选项E", "选项F",
           "参考答案", "解析"]


def make_sample_xlsx():
    wb = Workbook()
    ws = wb.active
    ws.title = "题库"
    ws.append(HEADERS)
    rows = [
        ["大学英语", "Unit1", "单选", "第1题 1+1等于（）", "1", "2", "3", "4", "", "", "B", "1+1=2"],
        ["大学英语", "Unit1", "单选", "第2题 2+2等于（）", "2", "4", "6", "8", "", "", "B", "2+2=4"],
        ["大学英语", "Unit1", "单选", "第3题 3+3等于（）", "3", "6", "9", "12", "", "", "B", "3+3=6"],
        ["大学英语", "Unit1", "单选", "第4题 4+4等于（）", "4", "8", "12", "16", "", "", "B", "4+4=8"],
    ]
    for r in rows:
        ws.append(r)
    wb.save(XLSX_PATH)


async def get_stems(page):
    """读取当前页面所有题干的文本列表（按渲染顺序）"""
    return await page.locator(".q-card .q-stem").all_text_contents()


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
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(INDEX_URI, wait_until="domcontentloaded")
        await page.wait_for_selector("#dropZone")

        # 1) 导入题库
        await page.set_input_files("#fileInput", str(XLSX_PATH))
        await page.wait_for_selector(".q-card")
        total = await page.text_content("#stTotal")
        check("导入题库显示 4 题", total.strip() == "4", total)
        order0 = await get_stems(page)
        check("初始顺序为 第1→第4 题", order0 == ["第1题 1+1等于（）", "第2题 2+2等于（）",
                                                 "第3题 3+3等于（）", "第4题 4+4等于（）"],
              str(order0))

        # 2) 乱序：按钮状态切换 + 顺序打乱（随机撞车时最多重试 8 次）
        btn_shuffle = page.locator("#btnShuffle")
        shuffled_seen = False
        for _ in range(8):
            await btn_shuffle.click()
            await page.wait_for_timeout(150)
            cls = await btn_shuffle.get_attribute("class")
            txt = await btn_shuffle.text_content()
            if "active" in cls and "乱序中" in txt:
                order1 = await get_stems(page)
                if order1 != order0:
                    shuffled_seen = True
                    break
            # 未打乱则恢复重来
            await btn_shuffle.click()
            await page.wait_for_timeout(150)
        check("点乱序后按钮进入激活态", "active" in (await btn_shuffle.get_attribute("class") or "")
              and "乱序中" in (await btn_shuffle.text_content() or ""))
        check("乱序后题目顺序发生改变", shuffled_seen, "多次重试仍与原始顺序相同（小概率随机撞车）")

        # 3) 再次点乱序：恢复原始顺序
        await btn_shuffle.click()
        await page.wait_for_timeout(150)
        order2 = await get_stems(page)
        check("再点乱序恢复原始顺序", order2 == order0, str(order2))
        check("恢复后按钮取消激活态", "active" not in (await btn_shuffle.get_attribute("class") or ""))

        # 4) 答错一题进入错题本（在乱序状态下答错再导出）
        await btn_shuffle.click()  # 开启乱序
        await page.wait_for_timeout(150)
        await page.locator(".q-card").first.locator(".opt").first.click()  # 点第一个选项（非B）
        await page.wait_for_timeout(200)
        wrong_count = await page.text_content("#wrongCount")
        check("答错后错题本为 1", wrong_count.strip() == "1", wrong_count)

        # 5) 导出错题：触发文件下载
        async with page.expect_download() as dl_info:
            await page.locator("#btnExportWrong").click()
        download = await dl_info.value
        fname = download.suggested_filename
        check("导出错题触发下载", fname.startswith("错题_") and fname.endswith(".txt"), fname)

        await browser.close()

    print("=" * 50)
    print(f"测试结果：通过 {passed} 项，失败 {failed} 项")
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(run())
    sys.exit(0 if ok else 1)
