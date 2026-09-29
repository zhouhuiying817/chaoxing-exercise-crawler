# -*- coding: utf-8 -*-
"""提取 web-practice/index.html 的内联 <script>，用 node --check 校验语法"""
import re
import subprocess
import tempfile
import os

path = r"E:\chaoxing-exercise-crawler\web-practice\index.html"
html = open(path, encoding="utf-8").read()
# 取内联脚本（src 外链的跳过）
blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
print("内联 script 块数:", len(blocks))
ok = True
for i, code in enumerate(blocks):
    fd, tmp = tempfile.mkstemp(suffix=".js")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(code)
    r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
    if r.returncode != 0:
        ok = False
        print(f"块 {i} 语法错误:\n{r.stderr[:800]}")
    else:
        print(f"块 {i} OK（{len(code)} 字符）")
    os.remove(tmp)
print("内联 JS 全部通过" if ok else "存在语法错误")
