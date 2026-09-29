# -*- coding: utf-8 -*-
"""验证 background.js 新版课程名扫描函数（模拟注入，全部 chaoxing 标签）"""
import asyncio
from playwright.async_api import async_playwright

SCAN_FUNC = """(cid) => {
  // 1) 精确匹配 A：课程卡片带 courseid 属性
  var cards = document.querySelectorAll("[courseid='" + cid + "']");
  for (var c = 0; c < cards.length; c++) {
    var nm = cards[c].querySelector(".course-name, .courseName, [class*='course-name'], [class*='courseName']");
    if (nm) {
      var t = (nm.innerText || nm.title || "").trim().split("\\n")[0].trim();
      if (t && t.length >= 2 && t.length <= 60) return [t];
    }
    var a = cards[c].querySelector("a");
    if (a) {
      var t2 = (a.innerText || "").trim().split("\\n")[0].trim();
      if (t2 && t2.length >= 2 && t2.length <= 60) return [t2];
    }
  }
  // 2) 精确匹配 B：链接
  var as = document.querySelectorAll(
    "a[href*='courseId=' + cid + ''], a[href*='courseid=' + cid + '']");
  for (var i = 0; i < as.length; i++) {
    var node = as[i];
    for (var k = 0; k < 5 && node; k++, node = node.parentElement) {
      var t = (node.innerText || "").trim().split("\\n")[0].trim();
      if (t && t.length >= 2 && t.length <= 60 &&
          !/未知|暂无|返回|作业|测验|课程资料|课程信息|讨论|笔记|全部课程|我的课程|进行中|已结束/.test(t)) {
        return [t];
      }
    }
  }
  return [];
}"""


async def main():
    targets = [("264808661", "期望: Python语言程序设计"),
               ("219501351", "期望: windows 网络编程技术"),
               ("266057104", "期望: Java Web程序设计与开发(第5期)")]
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        pages = []
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if "chaoxing.com" in pg.url:
                    pages.append(pg)
        for cid, expect in targets:
            found = False
            for pg in pages:
                for fr in pg.frames:
                    try:
                        r = await fr.evaluate(SCAN_FUNC, cid)
                        if r:
                            print("courseId=%s -> %s  [%s]" % (cid, r[0], expect))
                            found = True
                            break
                    except Exception:
                        pass
                if found:
                    break
            if not found:
                print("courseId=%s -> 未命中 [%s]" % (cid, expect))
        await browser.close()


asyncio.run(main())
