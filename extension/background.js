/* background.js
   后台 Service Worker：接收 popup 的导出请求
   1) 按需下载题目图片到“学习通题库/{basename}/{basename}_图片/”
   2) 按用户勾选生成 xlsx / txt / docx（同一 basename，独立文件夹）
   文件保存在浏览器默认“下载/学习通题库/”目录，命名与 crawler/main.py 一致。
   另：课程名自动发现（扫描已打开标签页 + 记忆 courseId->课程名）。
*/
"use strict";

importScripts("xlsx.full.min.js", "jszip.min.js");

// ---------- 通用工具 ----------
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

function safeFilename(name) {
  return String(name || "").replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 80) || "习题";
}

function pad2(n) { return (n < 10 ? "0" : "") + n; }

function buildBasename(meta) {
  // 命名：作业名(章节优先，课程兜底)_YYYYMMDD_HHMMSS
  var now = new Date();
  var datePart = "" + now.getFullYear() + pad2(now.getMonth() + 1) + pad2(now.getDate());
  var timePart = pad2(now.getHours()) + pad2(now.getMinutes()) + pad2(now.getSeconds());
  var base = safeFilename(meta && (meta.chapter || meta.course)) || "习题";
  return base + "_" + datePart + "_" + timePart;
}

function bufToB64(buf) {
  var bytes = new Uint8Array(buf), bin = "", CH = 0x8000;
  for (var i = 0; i < bytes.length; i += CH) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
  }
  return btoa(bin);
}

function downloadDataURL(dataUrl, filename) {
  return chrome.downloads.download({ url: dataUrl, filename: filename, saveAs: false });
}

// ---------- 图片下载（去重、批间延时、返回文件名映射与字节缓存） ----------
async function downloadImages(questions, basePath) {
  // 收集全部图片 URL（保持每题内顺序，全局去重）
  var urlList = [], urlSeen = {}, urlName = {};
  questions.forEach(function (q) {
    (q.images || []).forEach(function (u) {
      if (!u || urlSeen[u]) return;
      urlSeen[u] = true;
      urlList.push(u);
    });
  });

  var buffers = {};   // 最终文件名 -> ArrayBuffer（供 Word 内嵌）
  var failed = new Set();
  // 导出进度（写入 storage.session，popup 通过 onChanged 实时显示；导出结束清除）
  try {
    chrome.storage.session.set({ cxExportProgress: { done: 0, totalImg: urlList.length, totalQ: questions.length } });
  } catch (e) {}
  for (var i = 0; i < urlList.length; i++) {
    var url = urlList[i];
    try {
      var resp = await fetch(url, { credentials: "include" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      var buf = await resp.arrayBuffer();
      var ext = (url.match(/\.(png|jpe?g|gif|webp|svg)(\?|$)/i) || [])[1] || "png";
      if (ext.toLowerCase() === "jpg") ext = "jpeg";
      if (!/^(png|jpeg|gif|webp|svg)$/i.test(ext)) ext = "png";
      var base = (url.split("/").pop() || "").replace(/\?.*$/, "");
      var name = (base && /\.(png|jpe?g|gif|webp|svg)$/i.test(base)) ? base : ("img" + (i + 1) + "." + ext);
      // 目标目录内重名则加序号
      var final = name, n = 2;
      while (buffers[final]) final = name.replace(/(\.[^.]+)$/, "_" + (n++) + "$1");
      buffers[final] = buf;
      urlName[url] = final;
      var b64 = bufToB64(buf);
      await downloadDataURL("data:image/" + ext + ";base64," + b64,
        basePath + "_图片/" + final);
      await sleep(300 + Math.random() * 400); // 批间延时，防请求过快
      // 进度更新
      try { chrome.storage.session.set({ cxExportProgress: { done: i + 1, totalImg: urlList.length, totalQ: questions.length } }); } catch (e) {}
    } catch (e) {
      failed.add(url);
    }
  }
  // 图片阶段结束（后续为文件生成阶段）
  try { chrome.storage.session.set({ cxExportProgress: { done: -1, totalImg: urlList.length, totalQ: questions.length } }); } catch (e) {}

  // 把每题 images 中的 URL 映射为最终文件名；替换占位符为“可读标注”
  questions.forEach(function (q) {
    (q.images || []).forEach(function (u, idx) {
      var ph = "[[IMG:" + idx + "]]";
      var fname = urlName[u];
      var mark = fname ? "[图片: " + fname + "]" : (failed.has(u) ? "[图片: 下载失败]" : "");
      q.stem = q.stem.split(ph).join(mark);
      q.analysis = q.analysis.split(ph).join(mark);
      Object.keys(q.options || {}).forEach(function (L) {
        q.options[L] = q.options[L].split(ph).join(mark);
      });
    });
  });
  return { images: Object.keys(buffers).length, buffers: buffers };
}

// ---------- TXT ----------
function formatQuestionsText(questions) {
  var lines = [];
  if (questions.length) {
    lines.push("课程名称：" + (questions[0].course || ""));
    lines.push("章节名称：" + (questions[0].chapter || ""));
  }
  var now = new Date();
  lines.push("采集时间：" + now.getFullYear() + "-" + pad2(now.getMonth() + 1) + "-" +
             pad2(now.getDate()) + " " + pad2(now.getHours()) + ":" + pad2(now.getMinutes()) + ":" + pad2(now.getSeconds()));
  lines.push("题目数量：" + questions.length);
  lines.push("=".repeat(50));
  questions.forEach(function (q, idx) {
    lines.push("");
    lines.push("【" + (idx + 1) + "】【" + (q.qtype || "未知") + "】");
    lines.push(q.stem || "");
    "ABCDEFGH".split("").forEach(function (L) {
      if (q.options && q.options[L]) lines.push(L + ". " + q.options[L]);
    });
    if (q.answer) lines.push("【参考答案】" + q.answer);
    if (q.analysis) lines.push("【解析】" + q.analysis);
  });
  return lines.join("\n");
}

function buildTxt(questions) {
  // utf-8 BOM，记事本打开不乱码
  var b64 = bufToB64(new TextEncoder().encode("\uFEFF" + formatQuestionsText(questions)).buffer);
  return "data:text/plain;charset=utf-8;base64," + b64;
}

// ---------- XLSX（SheetJS） ----------
function buildXlsx(questions) {
  var headers = ["课程名称", "章节名称", "题型", "题干",
                 "选项A", "选项B", "选项C", "选项D", "选项E", "选项F",
                 "参考答案", "解析"];
  var rows = questions.map(function (q) {
    return [q.course || "", q.chapter || "", q.qtype || "", q.stem || "",
            (q.options && q.options.A) || "", (q.options && q.options.B) || "",
            (q.options && q.options.C) || "", (q.options && q.options.D) || "",
            (q.options && q.options.E) || "", (q.options && q.options.F) || "",
            q.answer || "", q.analysis || ""];
  });
  var ws = XLSX.utils.aoa_to_sheet([headers].concat(rows));
  ws["!cols"] = [{ wch: 20 }, { wch: 18 }, { wch: 6 }, { wch: 45 }, { wch: 25 }, { wch: 25 },
                 { wch: 25 }, { wch: 25 }, { wch: 25 }, { wch: 25 }, { wch: 10 }, { wch: 40 }];
  var wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "题库");
  var b64 = XLSX.write(wb, { bookType: "xlsx", type: "base64" });
  return "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64," + b64;
}

// ---------- DOCX（JSZip + 手写 OOXML，图片内嵌） ----------
function xmlEsc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function readPngSize(buf) {
  // PNG 尺寸：IHDR 在偏移 16，宽/高各 4 字节大端
  if (!buf || buf.byteLength < 24) return null;
  var dv = new DataView(buf);
  if (dv.getUint32(0) !== 0x89504E47) return null;
  return { w: dv.getUint32(16), h: dv.getUint32(20) };
}
function para(text, bold) {
  var rpr = bold
    ? '<w:rPr><w:b/><w:rFonts w:ascii="微软雅黑" w:eastAsia="微软雅黑" w:hAnsi="微软雅黑"/></w:rPr>'
    : '<w:rPr><w:rFonts w:ascii="微软雅黑" w:eastAsia="微软雅黑" w:hAnsi="微软雅黑"/></w:rPr>';
  return '<w:p><w:r>' + rpr + '<w:t xml:space="preserve">' + xmlEsc(text) + '</w:t></w:r></w:p>';
}
function imgPara(rId, name, buf) {
  var size = readPngSize(buf);
  var cx = 1080000; // 宽 3cm（EMU）
  var cy = 900000;  // 高上限 2.5cm
  if (size && size.w > 0 && size.h > 0) {
    cy = Math.round(cx * size.h / size.w);
    if (cy > 1440000) cy = 1440000; // 高不超过 4cm
  }
  var xml =
    '<w:p><w:r><w:drawing>' +
    '<wp:inline distT="0" distB="0" distL="0" distR="0" ' +
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">' +
    '<wp:extent cx="' + cx + '" cy="' + cy + '"/>' +
    '<wp:docPr id="' + rId + '" name="' + name + '"/>' +
    '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">' +
    '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">' +
    '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">' +
    '<pic:nvPicPr><pic:cNvPr id="' + rId + '" name="' + name + '"/><pic:cNvPicPr/></pic:nvPicPr>' +
    '<pic:blipFill><a:blip r:embed="rIdImg' + rId + '"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>' +
    '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="' + cx + '" cy="' + cy + '"/></a:xfrm>' +
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>' +
    '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>';
  return xml;
}
function buildDocx(questions, imgBuffers) {
  var zip = new JSZip();
  var mediaNames = Object.keys(imgBuffers || {});
  var body = [];
  var imgId = 0;

  function pushText(text, bold) {
    // 文本中的 “[图片: 文件名]” 转为内嵌图片 run（文件名在 imgBuffers 中）
    var re = /\[图片:\s*([^\]]+)\]/g, last = 0, m;
    while ((m = re.exec(text)) !== null) {
      var before = text.slice(last, m.index);
      if (before) body.push(para(before, bold));
      var fname = m[1].trim();
      if (imgBuffers[fname]) {
        imgId++;
        body.push(imgPara(imgId, fname, imgBuffers[fname]));
      } else {
        body.push(para("[图片: " + fname + "]", bold)); // 没有缓存则保留标注
      }
      last = m.index + m[0].length;
    }
    var rest = text.slice(last);
    if (rest) body.push(para(rest, bold));
  }

  // 头部信息
  if (questions.length) {
    pushText("课程名称：" + (questions[0].course || ""), true);
    pushText("章节名称：" + (questions[0].chapter || ""), true);
  }
  var now = new Date();
  pushText("采集时间：" + now.getFullYear() + "-" + pad2(now.getMonth() + 1) + "-" +
           pad2(now.getDate()) + " " + pad2(now.getHours()) + ":" + pad2(now.getMinutes()) + ":" + pad2(now.getSeconds()), false);
  pushText("题目数量：" + questions.length, false);
  body.push(para("=".repeat(50), false));

  questions.forEach(function (q, idx) {
    body.push(para("", false));
    pushText("【" + (idx + 1) + "】【" + (q.qtype || "未知") + "】", true);
    pushText(q.stem || "", false);
    "ABCDEFGH".split("").forEach(function (L) {
      if (q.options && q.options[L]) pushText(L + ". " + q.options[L], false);
    });
    if (q.answer) pushText("【参考答案】" + q.answer, true);
    if (q.analysis) pushText("【解析】" + q.analysis, false);
  });

  // media 与关系
  mediaNames.forEach(function (name, i) {
    zip.file("word/media/" + name, imgBuffers[name]);
  });
  var imgRels = mediaNames.map(function (name, i) {
    return '<Relationship Id="rIdImg' + (i + 1) + '" ' +
      'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" ' +
      'Target="media/' + name + '"/>';
  }).join("");

  zip.file("[Content_Types].xml",
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
    '<Default Extension="xml" ContentType="application/xml"/>' +
    '<Default Extension="png" ContentType="image/png"/>' +
    '<Default Extension="jpeg" ContentType="image/jpeg"/>' +
    '<Default Extension="gif" ContentType="image/gif"/>' +
    '<Default Extension="webp" ContentType="image/webp"/>' +
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
    "</Types>");
  zip.file("_rels/.rels",
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
    "</Relationships>");
  zip.file("word/_rels/document.xml.rels",
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + imgRels + "</Relationships>");
  zip.file("word/document.xml",
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' +
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
    "<w:body>" + body.join("") +
    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>' +
    '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>');

  return zip.generateAsync({ type: "blob", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
}

function blobToDataURL(blob) {
  return new Promise(function (resolve, reject) {
    var fr = new FileReader();
    fr.onload = function () { resolve(fr.result); };
    fr.onerror = reject;
    fr.readAsDataURL(blob);
  });
}

// ---------- 课程名自动发现 ----------
// 作业/测验详情页本身通常不含课程名（课程名在课程主页/作业列表页/学习通空间主页）。
// 策略：1) 扫描已打开的 chaoxing 标签页，优先按 courseId 精确匹配课程卡片；
//       2) 记忆 courseId->课程名，下次直接复用；3) 都失败则回退通用选择器取候选。
async function findCourseNameFromTabs(currentTabId, courseId) {
  if (!courseId) return "";
  // 2) 先查记忆
  var mem = await chrome.storage.local.get("courseNames");
  if (mem.courseNames && mem.courseNames[courseId]) {
    return mem.courseNames[courseId];
  }
  // 1) 扫描其它 chaoxing 标签页
  var tabs = await chrome.tabs.query({ url: ["*://*.chaoxing.com/*"] });
  for (var i = 0; i < tabs.length; i++) {
    var t = tabs[i];
    if (t.id === currentTabId || !t.url || t.url.indexOf("chaoxing.com") < 0) continue;
    try {
      var results = await chrome.scripting.executeScript({
        target: { tabId: t.id, allFrames: true },
        args: [courseId],
        func: function (cid) {
          // 1) 精确匹配 A：课程卡片带 courseid 属性（学习通空间主页课程列表）
          var cards = document.querySelectorAll("[courseid='" + cid + "']");
          for (var c = 0; c < cards.length; c++) {
            var nm = cards[c].querySelector(".course-name, .courseName, [class*='course-name'], [class*='courseName']");
            if (nm) {
              var t = (nm.innerText || nm.title || "").trim().split("\n")[0].trim();
              if (t && t.length >= 2 && t.length <= 60) return [t];
            }
            // 卡片内任意链接文本
            var a = cards[c].querySelector("a");
            if (a) {
              var t2 = (a.innerText || "").trim().split("\n")[0].trim();
              if (t2 && t2.length >= 2 && t2.length <= 60) return [t2];
            }
          }
          // 2) 精确匹配 B：页面中含 courseId=cid 的链接，取其自身/祖先文本（课程卡片）
          var as = document.querySelectorAll(
            "a[href*='courseId=" + cid + "'], a[href*='courseid=" + cid + "']");
          for (var i = 0; i < as.length; i++) {
            var node = as[i];
            for (var k = 0; k < 5 && node; k++, node = node.parentElement) {
              var t = (node.innerText || "").trim().split("\n")[0].trim();
              if (t && t.length >= 2 && t.length <= 60 &&
                  !/未知|暂无|返回|作业|测验|课程资料|课程信息|讨论|笔记|全部课程|我的课程|进行中|已结束/.test(t)) {
                return [t];
              }
            }
          }
          // 3) 回退：通用课程名选择器
          var cands = [];
          var sels = [".courseName", ".course-name", ".courseTitle", ".course-title",
                      ".topTitle", ".nav-title", ".crumb", ".breadcrumb", ".headTitle",
                      ".course_name", ".courseNameTitle", "#courseName",
                      "[class*=courseName]", "[class*=courseName] span",
                      ".course_top .title", ".course-info .title", ".courseInfo"];
          for (var i = 0; i < sels.length; i++) {
            var els = document.querySelectorAll(sels[i]);
            for (var j = 0; j < els.length; j++) {
              var t = (els[j].innerText || "").trim().split("\n")[0].trim();
              if (t && t.length >= 2 && t.length <= 60 &&
                  !/未知|暂无|返回|作业|测验|课程资料|课程信息|讨论|笔记|全部课程|我的课程|进行中|已结束/.test(t)) cands.push(t);
            }
          }
          return cands.slice(0, 8);
        }
      });
      for (var k = 0; k < (results || []).length; k++) {
        var arr = results[k] && results[k].result;
        if (!arr || !arr.length) continue;
        var best = arr[0];
        // 有精确匹配(单元素数组)则直接用；否则多候选取最短（课程名通常较短）
        if (arr.length > 1) {
          arr.forEach(function (s) { if (s.length < best.length) best = s; });
        }
        var v = await chrome.storage.local.get("courseNames");
        var map = v.courseNames || {};
        map[courseId] = best;
        await chrome.storage.local.set({ courseNames: map });
        return best;
      }
    } catch (e) { /* 该标签不可注入则跳过 */ }
  }
  return "";
}

// ---------- 消息处理 ----------
chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  if (!msg || msg.type !== "export") return;
  handleExport(msg).then(sendResponse).catch(function (e) {
    sendResponse({ ok: false, error: e.message || String(e) });
  });
  return true; // 保持异步响应通道
});

// popup 请求：为当前页自动找课程名
chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  if (!msg || msg.type !== "findCourseName") return;
  findCourseNameFromTabs(msg.tabId, msg.courseId)
    .then(function (name) { sendResponse({ ok: true, name: name }); })
    .catch(function (e) { sendResponse({ ok: false, error: e.message || String(e) }); });
  return true;
});

async function handleExport(msg) {
  var questions = (msg.questions || []).map(function (q) {
    // 深拷贝，避免污染页面数据
    return JSON.parse(JSON.stringify(q));
  });
  if (!questions.length) return { ok: false, error: "没有可导出的题目" };

  // 课程名兜底：未知时从 URL 提取 courseId，查记忆/扫描标签页自动补全
  var meta = msg.meta || {};
  if (!meta.course || meta.course.indexOf("未知") === 0) {
    var m = (meta.frameUrl || "").match(/courseId=(\d+)|courseid=(\d+)/i);
    var cid = m ? (m[1] || m[2]) : "";
    if (cid) {
      var found = await findCourseNameFromTabs(msg.tabId, cid);
      if (found) {
        meta.course = found;
        questions.forEach(function (q) { q.course = found; });
      }
    }
  }

  var basename = buildBasename(meta);
  var dir = "学习通题库/" + basename;

  // 1) 下载图片（含占位符替换）
  var imgResult = await downloadImages(questions, dir);

  // 2) 按勾选格式生成文件
  var files = [];
  var formats = msg.formats || ["xlsx", "txt", "docx"];
  if (formats.indexOf("xlsx") >= 0) {
    var xb = buildXlsx(questions);
    var xn = basename + ".xlsx";
    await downloadDataURL(xb, dir + "/" + xn);
    files.push(xn);
  }
  if (formats.indexOf("txt") >= 0) {
    var tb = buildTxt(questions);
    var tn = basename + ".txt";
    await downloadDataURL(tb, dir + "/" + tn);
    files.push(tn);
  }
  if (formats.indexOf("docx") >= 0) {
    var blob = await buildDocx(questions, imgResult.buffers);
    var dn = basename + ".docx";
    await downloadDataURL(await blobToDataURL(blob), dir + "/" + dn);
    files.push(dn);
  }
  // 清除导出进度（避免下次弹窗误读旧状态）
  try { chrome.storage.session.remove("cxExportProgress"); } catch (e) {}
  return { ok: true, files: files, images: imgResult.images, basename: basename, dir: dir };
}
