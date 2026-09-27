# -*- coding: utf-8 -*-
"""
爬虫 Excel 导出功能自测
=================================
调用 crawler/main.py 的 export_excel，把一组模拟题目写入
output/question_bank.xlsx，再读回文件校验表头、行数与内容。
运行：python tests/test_export.py
"""
import re
import sys
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crawler"))
import main as crawler  # noqa: E402

SAMPLE_QUESTIONS = [
    {
        "course": "大学英语", "chapter": "Unit1测验", "qtype": "单选",
        "stem": "（单选题）1+1等于（）",
        "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
        "answer": "B", "analysis": "1+1=2，故选B。",
    },
    {
        "course": "大学英语", "chapter": "Unit1测验", "qtype": "多选",
        "stem": "（多选题）下列属于水果的有（）",
        "options": {"A": "苹果", "B": "香蕉", "C": "土豆", "D": "西红柿"},
        "answer": "AB", "analysis": "苹果和香蕉是水果。",
    },
    {
        "course": "大学英语", "chapter": "Unit1测验", "qtype": "判断",
        "stem": "（判断题）地球是圆的。",
        "options": {"A": "正确", "B": "错误"},
        "answer": "A", "analysis": "地球是一个近似球体。",
    },
]


def main():
    passed, failed = 0, 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            failed += 1
            print(f"  [FAIL] {name}  {detail}")

    out = crawler.export_excel(SAMPLE_QUESTIONS)
    print(f"导出文件：{out}")
    check("文件存在", out.exists(), str(out))
    # 新命名规则：日期_作业名称.xlsx（章节名 Unit1测验）
    check("文件名=日期_作业名称", re.fullmatch(r"\d{8}_Unit1测验\.xlsx", out.name) is not None, out.name)
    check("文件位于 output 目录", out.parent.name == "output", str(out.parent))

    wb = load_workbook(out)
    ws = wb.active
    check("工作表名=题库", ws.title == "题库", ws.title)
    check("表头12列", ws.max_column == 12, str(ws.max_column))
    check("数据4行（含表头）", ws.max_row == 4, str(ws.max_row))

    headers = [ws.cell(row=1, column=c).value for c in range(1, 13)]
    check("表头顺序正确",
          headers == crawler.EXCEL_HEADERS, str(headers))
    check("题1题干", ws.cell(row=2, column=4).value == "（单选题）1+1等于（）",
          str(ws.cell(row=2, column=4).value))
    check("题1答案B", ws.cell(row=2, column=11).value == "B",
          str(ws.cell(row=2, column=11).value))
    check("题2多选答案AB", ws.cell(row=3, column=11).value == "AB",
          str(ws.cell(row=3, column=11).value))
    check("题3判断选项B=错误", ws.cell(row=4, column=6).value == "错误",
          str(ws.cell(row=4, column=6).value))
    check("课程名称列", ws.cell(row=2, column=1).value == "大学英语",
          str(ws.cell(row=2, column=1).value))

    print("=" * 50)
    print(f"测试结果：通过 {passed} 项，失败 {failed} 项")
    # 清理本次测试生成的题库文件，避免污染 output 目录
    try:
        out.unlink()
        print(f"已清理测试文件：{out.name}")
    except Exception:
        pass
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
