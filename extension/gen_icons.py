# -*- coding: utf-8 -*-
"""生成浏览器扩展图标（蓝底白字“题”），输出 extension/icons/icon16/48/128.png"""
from PIL import Image, ImageDraw, ImageFont

ICON_DIR = r"E:\chaoxing-exercise-crawler\extension\icons"


def make_icon(size: int):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size * 0.22
    # 蓝色圆角方块（渐变省略，纯色即可）
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(r), fill=(37, 99, 235, 255))
    # 白色“题”字
    font_size = int(size * 0.62)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", font_size)
    except Exception:
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), "题", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]), "题",
           font=font, fill=(255, 255, 255, 255))
    img.save(f"{ICON_DIR}/icon{size}.png")


for s in (16, 48, 128):
    make_icon(s)
    print("生成 icon", s)
