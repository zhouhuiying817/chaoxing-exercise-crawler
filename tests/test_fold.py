# -*- coding: utf-8 -*-
"""测试：折叠答案展开功能（expand_hidden_answers）
场景：题目块内“查看答案”按钮默认折叠答案/解析，
     点击后内容显示，解析结果才能提取到答案与解析。
验证：
  1) 不展开时，折叠题解析结果中答案/解析为空；
  2) 调用 expand_hidden_answers 后点击了按钮；
  3) 再次解析，折叠题能提取到答案与解析；
  4) 含“提交/保存”等词的按钮不会被误点（页面无副作用）；
  5) 正常显示答案的题目不受影响。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crawler"))
import main as crawler  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

PAGE_URI = (Path(__file__).resolve().parent / "simulate_fold_page.html").as_uri()
PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name}  {detail}")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        page = await browser.new_page()
        await page.goto(PAGE_URI, wait_until="domcontentloaded")
        await crawler.wait_random(0.5, 0.8)

        # 定位题目容器
        frame, sel, cnt = await crawler.find_question_container(page)
        check("找到题目容器", frame is not None and cnt == 3, f"sel={sel} cnt={cnt}")

        meta = {"course": "Python程序设计", "chapter": "第一章测验"}

        # 1) 不展开直接解析：折叠题（题1）答案/解析应为空
        qs = await crawler.parse_questions(frame, sel, meta, PAGE_URI, {})
        check("解析出 3 题", len(qs) == 3, f"got {len(qs)}")
        check("未展开时题1答案为空", qs and qs[0]["answer"] == "", qs[0]["answer"] if qs else "-")
        check("未展开时题1解析为空", qs and qs[0]["analysis"] == "", qs[0]["analysis"] if qs else "-")

        # 2) 展开
        clicked = await crawler.expand_hidden_answers(frame, sel)
        check("展开函数点击了 1 个按钮", clicked == 1, f"clicked={clicked}")

        # 3) 再次解析：题1 能提取到答案与解析
        qs2 = await crawler.parse_questions(frame, sel, meta, PAGE_URI, {})
        check("展开后题1答案=B", qs2 and qs2[0]["answer"] == "B",
              qs2[0]["answer"] if qs2 else "-")
        check("展开后题1解析非空", qs2 and "2的3次方" in qs2[0]["analysis"],
              qs2[0]["analysis"] if qs2 else "-")

        # 4) “提交作业”按钮未被误点（页面无副作用标记）
        submitted = await page.evaluate("window.__submitted === true")
        check("“提交作业”未被误点", submitted is False)
        # 题2/题3 答案仍正常
        check("题2答案=A（正常显示不受影响）", qs2 and qs2[1]["answer"] == "A",
              qs2[1]["answer"] if qs2 else "-")
        check("题3答案=ABCD", qs2 and qs2[2]["answer"] == "ABCD",
              qs2[2]["answer"] if qs2 else "-")

        await browser.close()

    print("=" * 50)
    print(f"测试结果：通过 {PASS} 项，失败 {FAIL} 项")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
