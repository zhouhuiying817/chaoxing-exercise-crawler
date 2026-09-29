/* collect.js
   采集核心：在页面上下文（MAIN world）运行，解析当前页面的题目。
   - 依赖 font-common.js（window.__CXCOMMON）
   - 通过 chrome.scripting.executeScript 注入（allFrames: true，每个 frame 独立运行）
   - 只处理当前页面，不翻页、不遍历、不自动答题
   返回：{ ok, frameUrl, meta:{course,chapter}, questions:[...], expandCount, error }
   题目字段与 crawler/main.py 一致：course/chapter/qtype/stem/options/answer/analysis/images
   images 为整题图片 URL 列表，stem/options/analysis 中的 [[IMG:n]] 指向其下标。
*/
(function () {
  "use strict";

  // ---------- 工具 ----------
  function sleep(ms) {
    return new Promise(function (r) { setTimeout(r, ms); });
  }
  function clean(s) {
    return window.__CXCOMMON.cleanText(s);
  }

  // ---------- 页面预处理：少量滚动加载懒加载内容（不翻页） ----------
  async function lazyLoadScroll() {
    var heights = [];
    for (var i = 0; i < 3; i++) {
      heights.push(document.body.scrollHeight);
      window.scrollTo(0, document.body.scrollHeight);
      await sleep(400 + Math.random() * 400);
      if (i > 0 && document.body.scrollHeight === heights[heights.length - 2]) break; // 高度不再变化即停止
    }
    window.scrollTo(0, 0);
  }

  // ---------- 题目容器定位 ----------
  var CONTAINER_PRIORITY = [".questionLi", ".TiMu", ".question", ".questLi"];
  function isRealQuestion(el) {
    var sels = [".qtContent", ".Zy_TItle", ".Zy_TItle_t", ".qtDetail", ".mark_name"];
    for (var i = 0; i < sels.length; i++) {
      if (el.querySelector(sels[i])) return true;
    }
    return false;
  }
  function findContainer() {
    var bestSel = null, bestN = 0;
    var probe = {};
    for (var i = 0; i < CONTAINER_PRIORITY.length; i++) {
      var sel = CONTAINER_PRIORITY[i];
      var nodes = document.querySelectorAll(sel);
      if (!nodes.length) { probe[sel] = { count: 0 }; continue; }
      var realFirst = isRealQuestion(nodes[0]);   // 过滤头部信息卡等“假题目块”
      probe[sel] = { count: nodes.length, realFirst: realFirst };
      if (!realFirst) continue;
      if (nodes.length > bestN) { bestSel = sel; bestN = nodes.length; }
    }
    return { sel: bestSel, count: bestN, probe: probe };
  }

  // ---------- 折叠答案展开（只点“查看答案/解析”类按钮） ----------
  function expandHiddenAnswers(root, dec) {
    var include = ["查看答案", "查看解析", "答案解析", "展开答案", "查看答案与解析", "showanswer", "viewanswer"];
    var exclude = ["提交", "保存", "完成", "收起", "关闭", "返回", "交卷", "上一", "下一", "翻页"];
    var nodes = root.querySelectorAll(
      "button, span[onclick], div[onclick], a[onclick], a[href^='javascript:'], " +
      "[class*='answer'], [class*='Answer']"
    );
    var n = 0;
    nodes.forEach(function (node) {
      var raw = (node.innerText || "").trim().toLowerCase();
      if (!raw) return;
      // 按钮文字可能被字体加密（乱码码点），先解码再判断关键词
      var txt = dec ? dec(raw).toLowerCase() : raw;
      if (!include.some(function (k) { return txt.indexOf(k) >= 0; })) return;
      if (exclude.some(function (k) { return txt.indexOf(k) >= 0; })) return;
      var r = node.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return;   // 跳过不可见元素
      node.click();
      n++;
    });
    return n;
  }

  // ---------- 元素文本 + 图片收集 ----------
  function elementTextWithImages(el) {
    var urls = [], parts = [];
    function walk(node) {
      if (node.nodeType === 3) { parts.push(node.textContent); return; }
      if (node.nodeType !== 1) return;
      if (node.tagName === "IMG") {
        // 学习通图片常懒加载：真实地址在 data-original
        var u = node.getAttribute("data-original") || node.getAttribute("src") || "";
        urls.push(u);
        parts.push("[[IMG:" + (urls.length - 1) + "]]");
      } else {
        Array.prototype.forEach.call(node.childNodes, walk);
      }
    }
    walk(el);
    return { text: parts.join(""), urls: urls };
  }

  // ---------- 课程/章节名称 ----------
  function extractMeta() {
    var course = "", chapter = "";
    var i, el, t;
    for (i = 0; i < [".mark_title", ".colorfont", ".cur", ".qt_title"].length; i++) {
      el = document.querySelector([".mark_title", ".colorfont", ".cur", ".qt_title"][i]);
      if (el) {
        t = clean(el.innerText);
        if (t && t.length < 80) { chapter = t; break; }
      }
    }
    if (!chapter) {
      var m = (document.body.innerText || "").match(/^\s*([^\n]{1,50})\s*\n\s*题量\s*[:：]/m);
      if (m) {
        var cand = clean(m[1]);
        if (cand && ["待完成", "已完成", "章节测验", "测验", "考试"].indexOf(cand) < 0) chapter = cand;
      }
    }
    var courseSels = [".courseName", ".course-name", ".courseTitle", ".course-title",
                      "#courseName", ".topTitle", ".nav-title", ".crumb", ".breadcrumb"];
    for (i = 0; i < courseSels.length; i++) {
      el = document.querySelector(courseSels[i]);
      if (el) {
        t = clean(el.innerText);
        if (t && t.length < 80) {
          var parts = t.split(/[/>›»|｜丨]/).map(function (s) { return s.trim(); }).filter(Boolean);
          if (parts.length >= 2) {
            course = parts[0];
            if (!chapter) chapter = parts[parts.length - 1];
          } else if (!course) {
            course = parts[0];
          }
          break;
        }
      }
    }
    if (!course) course = "未知课程";
    if (!chapter) chapter = "未知章节";
    return { course: course, chapter: chapter };
  }

  // ---------- 选项提取 ----------
  function extractOptions(block, blockText) {
    var options = {}, optImgs = {};
    var liCands = [".qtDetail li", ".Zy_ulTop li", ".Zy_ulTop ul li", "ul li.fl"];
    for (var i = 0; i < liCands.length; i++) {
      var lis = block.querySelectorAll(liCands[i]);
      if (!lis.length) continue;
      var tmp = {}, imgs = {};
      Array.prototype.forEach.call(lis, function (li) {
        var r = elementTextWithImages(li);
        var m = clean(r.text).match(/^([A-Ha-h])\s*[.、:：)]?\s*(.*)$/);
        if (m) {
          var L = m[1].toUpperCase(), c = clean(m[2]);
          // 页面数据偶尔把字母前缀写两遍（如“C. C. 超文本…”），去掉与选项字母重复的前缀
          c = c.replace(new RegExp("^" + L + "\\s*[.、:：)]\\s*"), "");
          if (c) { tmp[L] = c; imgs[L] = r.urls; }
        }
      });
      if (Object.keys(tmp).length >= 2) { options = tmp; optImgs = imgs; break; }
    }
    if (Object.keys(options).length < 2) {
      var parsed = window.__CXCOMMON.parseOptionsText(blockText);
      parsed.forEach(function (c, idx) {
        options[String.fromCharCode(65 + idx)] = c;
        optImgs[String.fromCharCode(65 + idx)] = [];
      });
    }
    return { options: options, optImgs: optImgs };
  }

  // ---------- 参考答案提取 ----------
  function extractAnswer(block, blockText, dec) {
    var sels = [".rightAnswerContent", ".marking_da", ".answer, .answers",
                ".da, .daan", ".correct_answer, .Correct", ".zq, .correct", ".key, .answerKey"];
    var i, el, t, n;
    for (i = 0; i < sels.length; i++) {
      el = block.querySelector(sels[i]);
      if (el) {
        t = clean(el.innerText);
        // 元素文本可能被字体加密，先解码再归一化
        if (dec) t = dec(t);
        if (!t) continue;
        // 纯“我的答案”元素跳过（不是正确答案）
        if (t.indexOf("我的答案") >= 0 && t.indexOf("正确答案") < 0 && t.indexOf("参考答案") < 0) continue;
        // 优先提取“正确答案/参考答案：”之后的内容；无标记则用整段
        var hasMark = /(?:正确答案|参考答案)\s*[:：]/.test(t);
        var body = hasMark
          ? t.replace(/^.*?(?:正确答案|参考答案)\s*[:：]\s*/, "")
          : t;
        body = body.replace(/我的答案[^\n]*/g, "").trim(); // 剔除可能混入的“我的答案”行
        if (!body) continue;
        // 字母答案（A / AB）或判断词 -> 归一化；否则按文本答案返回（填空/简答等）
        if (/^[A-Ha-h][A-Ha-h,、，;；和\s]*$/.test(body) ||
            /^(正确|错误|对|错|√|×)$/.test(body)) {
          n = window.__CXCOMMON.normalizeAnswer(body);
          if (n) return n;
        }
        if (body) return body.slice(0, 200);
      }
    }
    // 正则兜底（blockText 已由调用方解码）：先剔除“我的答案”行，避免误取 A
    var textOnlyCorrect = blockText.replace(/我的答案[^\n]*/g, "");
    var m1 = textOnlyCorrect.match(/(?:正确|参考)?答案\s*[:：]\s*([A-Ha-h][A-Ha-h,、，;；和\s]*)/i);
    if (m1) { n = window.__CXCOMMON.normalizeAnswer(m1[1]); if (n) return n; }
    var m2 = textOnlyCorrect.match(/(?:正确|参考)?答案\s*[:：]\s*(正确|错误|对|错|√|×)/i);
    if (m2) return window.__CXCOMMON.normalizeAnswer(m2[1]);
    // 填空/简答等无选项题型：答案后跟任意文本（限 200 字，排除单个字母与对错词）
    var m3 = textOnlyCorrect.match(/(?:正确|参考)?答案\s*[:：]\s*([^\n]{1,200})/i);
    if (m3) {
      var v = clean(m3[1]);
      if (v && !/^(A|B|C|D|E|F|G|H)$/i.test(v) && !/^(正确|错误|对|错|√|×)$/.test(v)) {
        return v.slice(0, 200);
      }
    }
    return "";
  }

  // ---------- 解析提取 ----------
  function extractAnalysis(block, blockText, dec) {
    var sels = [".qtAnalysis", ".marking_exam", ".analysis, .parse, .explain, .jieshi",
                ".jx, .fjw, .analysis_text"];
    var i, el, r, t;
    for (i = 0; i < sels.length; i++) {
      el = block.querySelector(sels[i]);
      if (el) {
        r = elementTextWithImages(el);
        t = clean(r.text);
        if (dec) t = dec(t);   // 解析文本可能被字体加密
        if (t) return { text: t.replace(/^(?:答案解析|解析|讲解)\s*[:：]?\s*/, "").slice(0, 500), urls: r.urls };
      }
    }
    // 正则兜底（blockText 已解码）
    var m = blockText.match(/(?:解析|答案解析|讲解)\s*[:：]?\s*(.+)/s);
    if (m) return { text: clean(m[1]).slice(0, 500), urls: [] };
    return { text: "", urls: [] };
  }

  // ---------- 主流程 ----------
  async function collect() {
    // 0) 页面已就绪：少量滚动加载懒加载内容
    await lazyLoadScroll();

    // 1) 字体解密器（提前准备：折叠按钮文字、答案/解析都可能是加密码点）
    var decoder = await window.__CXCOMMON.prepareFontDecoder();
    var dec = decoder.decode;

    // 2) 展开折叠答案（按钮文字解码后判断，点击后等待渲染）
    var expandCount = 0;
    var containerSel = findContainer().sel;
    if (containerSel) {
      Array.prototype.forEach.call(document.querySelectorAll(containerSel), function (b) {
        expandCount += expandHiddenAnswers(b, dec);
      });
      if (expandCount) await sleep(700 + Math.random() * 500);
    }

    // 3) 重新定位容器（展开后 DOM 可能变化）
    var fc = findContainer();
    if (!fc.sel) {
      return {
        ok: false, frameUrl: location.href, meta: extractMeta(),
        questions: [], expandCount: expandCount,
        probe: fc.probe,
        error: "未找到题目容器：" + JSON.stringify(fc.probe) +
               "（当前页面可能不是章节测验/作业页面，或学习通改版导致结构变化）"
      };
    }

    // 4) 解析每题
    var meta = extractMeta();
    var questions = [];
    Array.prototype.forEach.call(document.querySelectorAll(fc.sel), function (block, idx) {
      try {
        var blockText = block.innerText || "";
        // 整块文本先解码，后续所有正则/关键词判断都基于解码文本
        var blockTextDec = dec(blockText);
        var qImgs = [];
        function rebase(text, urls) {
          var off = qImgs.length;
          (urls || []).forEach(function (u) { qImgs.push(u); });
          return text.replace(/\[\[IMG:(\d+)\]\]/g, function (mm, n) {
            return "[[IMG:" + (off + parseInt(n, 10)) + "]]";
          });
        }

        // 题干（带图片）
        var stem = "", stemImgs = [];
        var stemSels = [".qtContent", ".Zy_TItle_t", ".Zy_TItle"];
        for (var si = 0; si < stemSels.length; si++) {
          var se = block.querySelector(stemSels[si]);
          if (se) {
            var sr = elementTextWithImages(se);
            if (clean(sr.text)) { stem = sr.text; stemImgs = sr.urls; break; }
          }
        }
        if (!clean(stem)) stem = clean(blockTextDec);
        stem = window.__CXCOMMON.stripTypeTag(window.__CXCOMMON.stripQuestionNo(clean(stem)));
        stem = rebase(stem, stemImgs);

        // 题型（题干/整块文本均已解码）
        var qtype = window.__CXCOMMON.extractTypeFromTitle(dec(stem)) ||
                    window.__CXCOMMON.extractTypeFromTitle(blockTextDec.slice(0, 120)) || "";
        if (!qtype) {
          var tagSels = [".colorShallow", ".type-tag", ".q-type"];
          for (var ti = 0; ti < tagSels.length; ti++) {
            var tel = block.querySelector(tagSels[ti]);
            if (tel) { var tt = window.__CXCOMMON.extractTypeFromTitle(dec(clean(tel.innerText))); if (tt) { qtype = tt; break; } }
          }
        }
        if (!qtype) {
          if (block.querySelector("input[type=checkbox]")) qtype = "多选";
          else if (block.querySelector("input[type=radio]")) qtype = "单选";
        }
        if (!qtype) {
          var popts = window.__CXCOMMON.parseOptionsText(blockTextDec);
          if (popts.length) {
            var joined = popts.join("");
            if ((joined.indexOf("正确") >= 0 && joined.indexOf("错误") >= 0) ||
                (joined.indexOf("对") >= 0 && joined.indexOf("错") >= 0)) qtype = "判断";
          }
        }
        // 无选项题型：标题/题干含关键词 -> 填空/简答（覆盖填空题、简答题、名词解释、问答、论述、计算等）
        if (!qtype) {
          var kw = blockTextDec.slice(0, 120);
          if (/填空题|填空\s*[:：]/.test(kw)) qtype = "填空";
          else if (/简答题|简答\s*[:：]|问答题|问答\s*[:：]|论述题|论述\s*[:：]|案例分析|编程题/.test(kw)) qtype = "简答";
          else if (/名词解释/.test(kw)) qtype = "名词解释";
          else if (/计算题|综合题/.test(kw)) qtype = "计算";
        }
        qtype = qtype || "未知";

        // 选项（带图片；兜底正则用解码文本）
        var eo = extractOptions(block, blockTextDec);
        Object.keys(eo.options).forEach(function (L) {
          eo.options[L] = rebase(eo.options[L], eo.optImgs[L] || []);
        });

        // 无选项且题干含下划线/括号空位 -> 填空
        if (qtype === "未知") {
          if (Object.keys(eo.options).length === 0 &&
              /_{2,}|（\s*）|\(\s*\)|【\s*】/.test(dec(stem))) qtype = "填空";
        }

        // 参考答案（基于解码文本 + 元素文本解码）
        var answer = extractAnswer(block, blockTextDec, dec);

        // 解析（带图片）
        var ar = extractAnalysis(block, blockTextDec, dec);
        var analysis = rebase(ar.text, ar.urls);

        // 统一字体解码
        var q = {
          course: meta.course,
          chapter: meta.chapter,
          qtype: qtype,
          stem: dec(stem),
          options: {},
          answer: dec(answer),
          analysis: dec(analysis),
          images: qImgs
        };
        Object.keys(eo.options).forEach(function (L) { q.options[L] = dec(eo.options[L]); });
        questions.push(q);
      } catch (e) {
        // 单题失败不中断整页解析
      }
    });

    // 无答案提示：已批阅回顾页只有“我的答案”，平台不下发正确答案/解析
    var hasAnswer = questions.some(function (q) { return q.answer; });
    var note = "";
    if (questions.length && !hasAnswer) {
      note = "本页题目均未解析到“参考答案/解析”：若为已批阅回顾页，平台只提供“我的答案”，不含正确答案。可尝试从课程目录-任务点-章节测验入口（未作答页）采集。";
    }

    return {
      ok: questions.length > 0,
      frameUrl: location.href,
      meta: meta,
      questions: questions,
      expandCount: expandCount,
      probe: fc.probe,
      note: note,
      error: questions.length ? "" : "解析到 0 题（可能页面未加载完成，可稍等后重试）"
    };
  }

  window.__CX_COLLECT = collect;
})();
