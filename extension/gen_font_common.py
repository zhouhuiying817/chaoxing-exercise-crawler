# -*- coding: utf-8 -*-
"""生成 extension/font-common.js：嵌入 CX_FONT_MAP 与候选汉字表，输出前端字体解密公共模块"""
import re
import json

CAND = open(r"E:\chaoxing-exercise-crawler\extension\candidates.txt", encoding="utf-8").read()

# 与 crawler/main.py 的 CX_FONT_MAP 保持一致（35 字，视觉核对过）
CX_FONT_MAP = {
    0x6236: "关", 0x6299: "的", 0x629D: "达", 0x629E: "值", 0x62A3: "为",
    0x62A6: "学", 0x62A7: "数", 0x62A8: "法", 0x62A9: "是", 0x62AA: "合",
    0x62AE: "不", 0x62B0: "下", 0x62B2: "出", 0x62B3: "句", 0x62B6: "结",
    0x62B7: "语", 0x62B8: "果", 0x62BA: "中", 0x62BB: "行", 0x62BE: "则",
    0x62BF: "符", 0x62C0: "字", 0x62C1: "串", 0x62C3: "若", 0x62C4: "价",
    0x62C7: "等", 0x62CA: "计", 0x6473: "表", 0x66F3: "输", 0x6CAC: "列",
    0x7197: "正", 0x7832: "以", 0x79E5: "算", 0x83D7: "执", 0x9B26: "式",
}
TYPE_KEYWORDS = {
    "单选题": "单选", "多选题": "多选", "判断题": "判断", "填空题": "填空",
    "简答题": "简答", "名词解释题": "名词解释", "论述题": "论述", "计算题": "计算",
    "综合题": "综合", "问答题": "问答", "程序设计题": "编程", "翻译题": "翻译",
}

map_lines = ",\n    ".join("0x%04X: \"%s\"" % (cp, ch) for cp, ch in CX_FONT_MAP.items())
kw_lines = ", ".join('"%s": "%s"' % (k, v) for k, v in TYPE_KEYWORDS.items())

js = """/* font-common.js
   学习通字体加密（font-cxsecret）前端解密 + 文本工具
   注入 MAIN world（collect.js 使用），挂在 window.__CXCOMMON。
   解密策略（与 crawler/main.py 一致）：
     1) 内置映射表 CX_FONT_MAP（人工核对过的 %(map_n)d 字）
     2) 运行时从页面 CSS 提取加密字体，枚举其覆盖的码点
     3) 未收录码点用 canvas 渲染字形，与系统黑体候选字逐像素比对取最相似
*/
(function () {
  "use strict";

  var CX_FONT_MAP = {
    %(map_lines)s
  };
  var TYPE_KEYWORDS = { %(kw_lines)s };
  var CANDIDATES = %(cand_json)s;

  // ---------- 文本工具 ----------
  function cleanText(s) {
    if (!s) return "";
    return String(s).replace(/\\s+/g, " ").trim();
  }
  function htmlUnescape(s) {
    var d = document.createElement("textarea");
    d.innerHTML = String(s == null ? "" : s);
    return d.value;
  }
  function extractTypeFromTitle(t) {
    if (!t) return null;
    var m = String(t).match(/[（(【]\\s*(单选题|多选题|判断题|填空题|简答题|名词解释题|论述题|计算题|综合题|问答题|程序设计题|翻译题)\\s*[)）】]/);
    return m ? (TYPE_KEYWORDS[m[1]] || null) : null;
  }
  function stripQuestionNo(stem) {
    var s = String(stem == null ? "" : stem);
    s = s.replace(/^\\s*\\d+\\s*[.、．:：]\\s*/, "");
    s = s.replace(/^\\s*\\d+\\s+(?=\\S)/, "");
    return s;
  }
  function stripTypeTag(stem) {
    return String(stem == null ? "" : stem)
      .replace(/^\\s*[（(【]\\s*(?:单选题|多选题|判断题|填空题|简答题|名词解释题|论述题|计算题|综合题|问答题|程序设计题|翻译题)\\s*[)）】]\\s*/, "");
  }
  var TRUE_WORDS = ["正确", "对", "√", "是", "true", "t", "yes"];
  var FALSE_WORDS = ["错误", "错", "×", "x", "否", "false", "f", "no"];
  function normalizeAnswer(raw) {
    if (!raw) return "";
    var text = cleanText(raw);
    text = text.replace(/^(?:正确|参考)?答案\\s*[:：]?\\s*/i, "");
    var letters = text.match(/[A-Ha-h]/g);
    if (letters && text.length <= 12) {
      var set = {};
      letters.forEach(function (L) { set[L.toUpperCase()] = 1; });
      return Object.keys(set).sort().join("");
    }
    for (var i = 0; i < TRUE_WORDS.length; i++)
      if (text.toLowerCase().indexOf(TRUE_WORDS[i].toLowerCase()) === 0) return TRUE_WORDS[i];
    for (var j = 0; j < FALSE_WORDS.length; j++)
      if (text.toLowerCase().indexOf(FALSE_WORDS[j].toLowerCase()) === 0) return FALSE_WORDS[j];
    return text;
  }
  function parseOptionsText(blockText) {
    var opts = [];
    var re = /(?:^|[\\n\\r])\\s*([A-Ha-h])\\s*[.、:：)]\\s*(.+?)(?=(?:[\\n\\r]\\s*[A-Ha-h]\\s*[.、:：)])|$)/g;
    var m;
    while ((m = re.exec(String(blockText || ""))) !== null) {
      var c = cleanText(m[2]);
      if (c) opts.push(c);
    }
    if (!opts.length) {
      String(blockText || "").split(/[\\n\\r]+/).forEach(function (line) {
        var lm = cleanText(line).match(/^([A-Ha-h])\\s*[.、:：)]\\s*(.+)$/);
        if (lm) { var cc = cleanText(lm[2]); if (cc) opts.push(cc); }
      });
    }
    return opts;
  }
  function decodeCxText(text, font_map) {
    if (!text) return text;
    var t = htmlUnescape(text);
    if (!font_map) return t;
    var out = "";
    for (var i = 0; i < t.length; i++) {
      var cp = t.charCodeAt(i);
      out += font_map[cp] || t[i];
    }
    return out;
  }

  // ---------- 字体解码 ----------
  var SIZE = 32;
  function renderGlyph(ch, family) {
    var canvas = document.createElement("canvas");
    canvas.width = SIZE; canvas.height = SIZE;
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = "#000"; ctx.fillRect(0, 0, SIZE, SIZE);
    ctx.font = SIZE + "px " + family;
    ctx.textBaseline = "middle"; ctx.textAlign = "center";
    ctx.fillStyle = "#fff";
    ctx.fillText(ch, SIZE / 2, SIZE / 2 + SIZE * 0.05);
    var data = ctx.getImageData(0, 0, SIZE, SIZE).data;
    var img = new Float32Array(SIZE * SIZE);
    var sum = 0;
    for (var i = 0, p = 0; i < img.length; i++, p += 4) {
      var v = data[p];
      img[i] = v; sum += v;
    }
    return { img: img, sum: sum };
  }
  var _probeCanvas = null, _probeCtx = null;
  function hasGlyph(ch, family) {
    // 小尺寸检测“是否有字形”（仅判 ink，速度快）；复用同一 canvas 避免反复创建
    if (!_probeCanvas) {
      _probeCanvas = document.createElement("canvas");
      _probeCanvas.width = 20; _probeCanvas.height = 20;
      _probeCtx = _probeCanvas.getContext("2d");
    }
    var s = 20, ctx = _probeCtx;
    ctx.fillStyle = "#000"; ctx.fillRect(0, 0, s, s);
    ctx.font = s + "px " + family;
    ctx.textBaseline = "middle"; ctx.textAlign = "center";
    ctx.fillStyle = "#fff";
    ctx.fillText(ch, s / 2, s / 2 + s * 0.05);
    var data = ctx.getImageData(0, 0, s, s).data;
    var sum = 0;
    for (var i = 3; i < data.length; i += 4) sum += data[i];  // alpha
    return sum > 20;
  }

  async function prepareFontDecoder() {
    // 1) 从页面 CSS 提取 font-cxsecret 字体源
    var fontCss = "";
    try {
      fontCss = Array.prototype.concat.apply([], Array.from(document.styleSheets).map(function (s) {
        try { return Array.from(s.cssRules || []); } catch (e) { return []; }
      })).filter(function (r) { return (r.cssText || "").indexOf("font-cxsecret") >= 0; })
        .map(function (r) { return r.cssText; }).join("\\n");
    } catch (e) {}
    var family = "cxsecret";
    var src = "";
    var m1 = fontCss.match(/src:\\s*url\\(([^)]+)\\)/);
    if (m1) src = m1[1];
    else {
      var m2 = fontCss.match(/base64,([A-Za-z0-9+/=]+)/);
      if (m2) src = "data:font/ttf;base64," + m2[1];
    }
    if (!src) return { decode: function (t) { return t ? htmlUnescape(t) : t; }, family: null, encryptedCount: 0 };
    try {
      var face = new FontFace(family, "url(" + src + ")");
      await face.load();
      document.fonts.add(face);
    } catch (e) { return { decode: function (t) { return t ? htmlUnescape(t) : t; }, family: null, encryptedCount: 0 }; }

    // 2) 枚举加密字体覆盖的码点（有字形即收录）
    var fq = '"' + family + '"';
    var encrypted = new Set();
    var ranges = [[0x4E00, 0x9FFF], [0xE000, 0xF8FF]];
    for (var r = 0; r < ranges.length; r++) {
      for (var cp = ranges[r][0]; cp <= ranges[r][1]; cp++) {
        if (hasGlyph(String.fromCharCode(cp), fq)) encrypted.add(cp);
      }
    }
    // 3) 预渲染候选字（系统黑体微软雅黑；macOS/Linux 回退到无衬线字体）
    var sysFamily = '"Microsoft YaHei", "PingFang SC", sans-serif';
    var lib = {};
    for (var i = 0; i < CANDIDATES.length; i++) lib[CANDIDATES[i]] = renderGlyph(CANDIDATES[i], sysFamily);
    // 4) 未知码点字形比对
    function matchChar(cp) {
      var q = renderGlyph(String.fromCharCode(cp), fq);
      var best = null, bestScore = Infinity;
      for (var k in lib) {
        var s = lib[k];
        if (Math.abs(s.sum - q.sum) > q.sum * 0.20) continue;
        var sc = 0, im1 = s.img, im2 = q.img;
        for (var i2 = 0; i2 < im1.length; i2++) sc += Math.abs(im1[i2] - im2[i2]);
        if (sc < bestScore) { bestScore = sc; best = k; }
      }
      return best;
    }
    function decode(text) {
      if (!text) return text;
      var t = htmlUnescape(text);
      var out = "";
      for (var i = 0; i < t.length; i++) {
        var cp = t.charCodeAt(i);
        if (CX_FONT_MAP[cp]) out += CX_FONT_MAP[cp];
        else if (encrypted.has(cp)) out += matchChar(cp) || t[i];
        else out += t[i];
      }
      return out;
    }
    return { decode: decode, family: family, encryptedCount: encrypted.size };
  }

  window.__CXCOMMON = {
    CX_FONT_MAP: CX_FONT_MAP,
    cleanText: cleanText,
    htmlUnescape: htmlUnescape,
    extractTypeFromTitle: extractTypeFromTitle,
    stripQuestionNo: stripQuestionNo,
    stripTypeTag: stripTypeTag,
    normalizeAnswer: normalizeAnswer,
    parseOptionsText: parseOptionsText,
    decodeCxText: decodeCxText,
    prepareFontDecoder: prepareFontDecoder
  };
})();
""" % {
    "map_n": len(CX_FONT_MAP),
    "map_lines": map_lines,
    "kw_lines": kw_lines,
    "cand_json": json.dumps(CAND, ensure_ascii=False),
}

out = r"E:\chaoxing-exercise-crawler\extension\font-common.js"
with open(out, "w", encoding="utf-8") as f:
    f.write(js)
print("已生成", out, "字节:", len(js.encode("utf-8")))
