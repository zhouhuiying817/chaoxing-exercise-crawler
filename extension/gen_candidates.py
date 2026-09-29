# -*- coding: utf-8 -*-
"""生成 GB2312 一级汉字（3755 常用字）候选表，写入 extension/candidates.txt"""
chars = []
for b in range(0xB0, 0xD8):
    for g in range(0xA1, 0xFE):
        try:
            chars.append(bytes([b, g]).decode('gb2312'))
        except Exception:
            pass
extra = '（）()+-*/=<>%&|!?，。、；：\"\'·×÷≥≤≠≈'
cand = ''.join(chars) + extra
print('候选字数:', len(cand))
for c in cand:
    assert ord(c) < 0xFFFF, c
with open(r'E:\chaoxing-exercise-crawler\extension\candidates.txt', 'w', encoding='utf-8') as f:
    f.write(cand)
print('已写入 candidates.txt')
