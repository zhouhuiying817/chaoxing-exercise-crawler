# -*- coding: utf-8 -*-
"""
三种格式导出功能自测：Excel / TXT / Word
验证：文件生成、命名一致（同一基础名）、内容读回正确
运行：python tests/test_export3.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crawler"))
import main as crawler  # noqa: E402

SAMPLE = [
    {"course": "大学英语", "chapter": "Unit1测验", "qtype": "单选",
     "stem": "1+1等于（）", "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
     "answer": "B", "analysis": "1+1=2，故选B。"},
    {"course": "大学英语", "chapter": "Unit1测验", "qtype": "多选",
     "stem": "下列属于水果的有（）", "options": {"A": "苹果", "B": "香蕉", "C": "土豆", "D": "西红柿"},
     "answer": "AB", "analysis": "苹果和香蕉是水果。"},
    {"course": "大学英语", "chapter": "Unit1测验", "qtype": "判断",
     "stem": "地球是圆的。", "options": {"A": "正确", "B": "错误"},
     "answer": "A", "analysis": "地球近似球体。"},
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

    # 1) 三种格式导出（共享同一基础名）
    base = crawler.build_output_basename(SAMPLE)
    xlsx = crawler.export_excel(SAMPLE, base)
    txt = crawler.export_txt(SAMPLE, base)
    docx = crawler.export_word(SAMPLE, base)

    check("Excel 生成", xlsx.exists() and xlsx.suffix == ".xlsx", str(xlsx))
    check("TXT 生成", txt.exists() and txt.suffix == ".txt", str(txt))
    check("Word 生成", docx.exists() and docx.suffix == ".docx", str(docx))

    # 2) 三种格式使用同一基础名
    base = set()
    for p in (xlsx, txt, docx):
        base.add(p.stem)
    check("三种格式同一基础名", len(base) == 1, str(base))
    check("基础名=作业名称_日期_时间", re.fullmatch(r"Unit1测验_\d{8}_\d{6}", xlsx.stem) is not None,
          xlsx.stem)
    # 三种格式文件位于同一子文件夹中
    check("三种格式在同一文件夹", xlsx.parent == txt.parent == docx.parent, str(xlsx.parent))

    # 3) TXT 内容读回验证
    text = txt.read_text(encoding="utf-8-sig")
    check("TXT 含课程名称", "课程名称：大学英语" in text)
    check("TXT 含题目数量", "题目数量：3" in text)
    check("TXT 含题型标记", "【1】【单选】" in text and "【2】【多选】" in text)
    check("TXT 含答案解析", "【参考答案】AB" in text and "【解析】苹果和香蕉是水果。" in text)

    # 4) Word 内容读回验证（python-docx 读回）
    from docx import Document
    doc = Document(str(docx))
    all_text = "\n".join(p.text for p in doc.paragraphs)
    check("Word 含标题", "大学英语 - Unit1测验" in all_text, all_text[:50])
    check("Word 含题目", "【1】【单选】1+1等于（）" in all_text)
    check("Word 含答案", "【参考答案】B" in all_text)
    check("Word 含解析", "【解析】1+1=2" in all_text)

    # 5) 清理测试文件（删除子文件夹，含可能存在的图片目录）
    folder = xlsx.parent
    for p in (xlsx, txt, docx):
        try:
            p.unlink()
        except Exception:
            pass
    try:
        img_dir = folder / f"{folder.name}_图片"
        if img_dir.exists():
            for f in img_dir.glob("*"):
                f.unlink(missing_ok=True)
            img_dir.rmdir()
        folder.rmdir()  # 目录空后删除
    except Exception:
        pass
    print(f"已清理测试文件")

    print("=" * 50)
    print(f"测试结果：通过 {passed} 项，失败 {failed} 项")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
