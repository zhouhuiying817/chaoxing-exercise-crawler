# -*- coding: utf-8 -*-
"""真实页面验证：把扩展的 font-common.js + collect.js 注入 work/view 页面并调用 __CX_COLLECT()"""
import asyncio
import json
from playwright.async_api import async_playwright

EXT = r"E:\chaoxing-exercise-crawler\extension"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        target = None
        for ctx in browser.contexts:
            for page in ctx.pages:
                if "mooc2/work/view" in page.url:
                    target = page
                    break
        if target is None:
            print("未找到 work/view 页面")
            await browser.close()
            return
        print("目标页面:", target.url[:120])
        frame = target.main_frame

        # 注入两个脚本文件（与扩展一致，注入页面 MAIN world）
        js = open(EXT + r"\font-common.js", encoding="utf-8").read() + "\n;\n" + \
             open(EXT + r"\collect.js", encoding="utf-8").read()
        await frame.evaluate(js)

        # 调用采集函数（验证 popup 修复后的等效行为）
        res = await frame.evaluate("window.__CX_COLLECT()")
        summary = {
            "ok": res.get("ok"),
            "error": res.get("error", ""),
            "expandCount": res.get("expandCount"),
            "probe": res.get("probe"),
            "meta": res.get("meta"),
            "题数": len(res.get("questions", [])),
        }
        print("\n==== 采集结果摘要 ====")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        for i, q in enumerate(res.get("questions", [])[:3]):
            print(f"\n--- 第{i+1}题 ---")
            print(json.dumps({k: q.get(k) for k in ("qtype", "stem", "options", "answer", "analysis")},
                             ensure_ascii=False, indent=2)[:1200])
        await browser.close()


asyncio.run(main())
