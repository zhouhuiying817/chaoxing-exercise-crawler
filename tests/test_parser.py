# -*- coding: utf-8 -*-
"""
爬虫解析逻辑自测脚本
=================================
用本机 Edge（无头模式）打开模拟的学习通页面（tests/simulate_chaoxing_page.html），
直接调用 crawler/main.py 的解析函数，验证：
  - 能否在 iframe 中定位题目块
  - 能否提取课程/章节名称
  - 能否正确解析题型、题干、选项、参考答案、解析

运行：python tests/test_parser.py
"""
import asyncio
import sys
from pathlib import Path

# 把 crawler 目录加入导入路径，复用 main.py 中的解析函数
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crawler"))

import main as crawler  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

SIM_PAGE = (Path(__file__).resolve().parent / "simulate_chaoxing_page.html").as_uri()


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

    async with async_playwright() as p:
        print("启动本机 Edge（无头模式）...")
        browser = await p.chromium.launch(channel="msedge", headless=True)
        page = await browser.new_page()
        await page.goto(SIM_PAGE, wait_until="domcontentloaded")
        await page.wait_for_timeout(800)  # 等待 iframe 内容写入

        # 1) 定位题目容器（新版 API 返回 frame, 容器选择器, 数量）
        frame, sel, total = await crawler.find_question_container(page)
        check("在 iframe 中定位到题目块", frame is not None and total == 4, f"sel={sel} total={total}")

        # 2) 提取课程/章节名称
        meta = await crawler.extract_meta(page, frame, SIM_PAGE)
        print(f"  meta = {meta}")
        check("提取课程名称", meta["course"] == "大学英语", meta["course"])
        check("提取章节名称", "Unit1" in meta["chapter"], meta["chapter"])

        # 3) 解析全部题目
        questions = await crawler.parse_questions(frame, sel, meta, SIM_PAGE)
        check("解析出 4 题", len(questions) == 4, f"len={len(questions)}")

        if len(questions) == 4:
            q1, q2, q3, q4 = questions

            # 题1：单选
            check("题1 题型=单选", q1["qtype"] == "单选", q1["qtype"])
            check("题1 题干", "1+1" in q1["stem"], q1["stem"])
            check("题1 选项A=1", q1["options"].get("A") == "1", str(q1["options"]))
            check("题1 选项B=2", q1["options"].get("B") == "2", str(q1["options"]))
            check("题1 答案=B", q1["answer"] == "B", q1["answer"])
            check("题1 解析", "1+1=2" in q1["analysis"], q1["analysis"])

            # 题2：多选
            check("题2 题型=多选", q2["qtype"] == "多选", q2["qtype"])
            check("题2 答案=AB", q2["answer"] == "AB", q2["answer"])
            check("题2 选项D=西红柿", q2["options"].get("D") == "西红柿", str(q2["options"]))

            # 题3：判断
            check("题3 题型=判断", q3["qtype"] == "判断", q3["qtype"])
            check("题3 答案=A", q3["answer"] == "A", q3["answer"])
            check("题3 选项A=正确", q3["options"].get("A") == "正确", str(q3["options"]))

            # 题4：无题型标记 + checkbox -> 推断为多选
            check("题4 题型=多选（由checkbox推断）", q4["qtype"] == "多选", q4["qtype"])
            check("题4 答案=ABCD", q4["answer"] == "ABCD", q4["answer"])
            check("题4 选项E=地动仪", q4["options"].get("E") == "地动仪", str(q4["options"]))
            check("题4 课程字段继承", q4["course"] == "大学英语", q4["course"])
            check("题4 章节字段继承", "Unit1" in q4["chapter"], q4["chapter"])

        await browser.close()

    print("=" * 50)
    print(f"测试结果：通过 {passed} 项，失败 {failed} 项")
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(run())
    sys.exit(0 if ok else 1)
