/* popup.js
   弹窗逻辑：注入采集脚本 -> 汇总各 frame 结果 -> 交给 background 导出
*/
"use strict";

var tabId = null;

function $(id) { return document.getElementById(id); }

// 读取当前活动标签页
chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
  if (tabs && tabs[0]) {
    tabId = tabs[0].id;
    var url = tabs[0].url || "";
    var isCx = /chaoxing\.com|edu\.cn/.test(url);
    $("pageInfo").textContent = isCx
      ? "当前页面：学习通页面 ✓"
      : "当前页面：非学习通域名（请在学习通页面使用）";
    if (!isCx) $("pageInfo").style.color = "#b45309";
  }
});

// 恢复上次勾选的导出格式（本地偏好记忆）
chrome.storage.local.get("exportFormats", function (v) {
  var saved = v.exportFormats;
  if (Array.isArray(saved) && saved.length) {
    ["xlsx", "txt", "docx"].forEach(function (f) {
      $("fmt" + f[0].toUpperCase() + f.slice(1)).checked = saved.indexOf(f) >= 0;
    });
  }
});

// 图片/文件导出进度（background 写入 storage.session，弹窗实时更新）
chrome.storage.onChanged.addListener(function (changes, area) {
  if (area !== "session" || !changes.cxExportProgress) return;
  var p = changes.cxExportProgress.newValue;
  if (!p) return;
  if (p.done === -1 || p.totalImg === 0) {
    // 图片阶段结束（或无图片），进入文件生成阶段
    $("status").textContent = "解析完成：" + (p.totalQ || 0) + " 题\n正在生成文件…";
  } else if (p.done === 0) {
    $("status").textContent = "解析完成：" + (p.totalQ || 0) + " 题\n正在导出（图片 0/" + p.totalImg + "）…";
  } else if (p.done < p.totalImg) {
    $("status").textContent = "导出中：图片 " + p.done + "/" + p.totalImg + "…";
  } else {
    $("status").textContent = "导出中：图片下载完成，正在生成文件…";
  }
});

// 采集按钮
$("btnCollect").addEventListener("click", function () {
  if (!tabId) return;
  var formats = [];
  if ($("fmtXlsx").checked) formats.push("xlsx");
  if ($("fmtTxt").checked) formats.push("txt");
  if ($("fmtDocx").checked) formats.push("docx");
  if (!formats.length) {
    $("status").textContent = "请至少勾选一种导出格式";
    $("status").className = "err";
    return;
  }
  // 记忆本次勾选，下次打开弹窗沿用
  chrome.storage.local.set({ exportFormats: formats });

  var btn = $("btnCollect");
  btn.disabled = true;
  $("status").className = "";
  $("status").textContent = "正在采集（含自动展开答案、字体解密），请稍候…";
  $("result").textContent = "";

  chrome.scripting.executeScript({
    target: { tabId: tabId, allFrames: true },
    files: ["font-common.js", "collect.js"],
    world: "MAIN"
  }, function () {
    if (chrome.runtime.lastError) {
      $("status").textContent = "采集失败：" + chrome.runtime.lastError.message;
      $("status").className = "err";
      btn.disabled = false;
      return;
    }
    // 注入脚本只“定义”了采集函数，这里必须在页面上下文（MAIN world）真正调用它，
    // 否则 result 为 undefined，会被误判为“未找到题目”。
    chrome.scripting.executeScript({
      target: { tabId: tabId, allFrames: true },
      func: function () {
        if (typeof window.__CX_COLLECT !== "function") {
          return { ok: false, error: "采集脚本未加载（请重新加载扩展后重试）" };
        }
        return window.__CX_COLLECT();
      },
      world: "MAIN"
    }, function (results) {
      if (chrome.runtime.lastError) {
        $("status").textContent = "采集执行失败：" + chrome.runtime.lastError.message;
        $("status").className = "err";
        btn.disabled = false;
        return;
      }
      // 汇总各 frame 结果：取题目数最多的 frame，课程名缺省时用其他 frame 补充
      var best = null, errMsg = "";
      (results || []).forEach(function (r) {
        var res = r && r.result;
        if (!res) return;
        if (!res.ok) { if (!errMsg) errMsg = res.error || "未解析到题目"; return; }
        if (!best || res.questions.length > best.questions.length) best = res;
      });
      if (!best) {
        // 优先显示采集脚本给出的具体原因（如容器未命中、0 题等）
        $("status").textContent = errMsg || "未找到题目，请确认当前是章节测验/作业页面";
        $("status").className = "err";
        btn.disabled = false;
        return;
      }
      // 补全课程名（主 frame 通常有课程名）
      (results || []).forEach(function (r) {
        var res = r && r.result;
        if (res && res.ok && res.meta && res.meta.course &&
            res.meta.course.indexOf("未知") !== 0 && best.meta.course.indexOf("未知") === 0) {
          best.meta.course = res.meta.course;
        }
      });

      // 课程名输入框：自动识别（含扫描其它标签页/记忆），用户可手动修改
      var courseInput = $("courseInput");
      if (best.meta.course && best.meta.course.indexOf("未知") !== 0) {
        courseInput.value = best.meta.course;
      } else {
        courseInput.value = "";
        courseInput.placeholder = "自动识别中…";
        var m = (best.frameUrl || "").match(/courseId=(\d+)|courseid=(\d+)/i);
        var cid = m ? (m[1] || m[2]) : "";
        if (cid) {
          chrome.runtime.sendMessage(
            { type: "findCourseName", tabId: tabId, courseId: cid },
            function (resp) {
              if (resp && resp.ok && resp.name) {
                courseInput.value = resp.name;
                courseInput.placeholder = "";
              } else {
                courseInput.placeholder = "未自动识别到，可手动填写";
              }
            });
        } else {
          courseInput.placeholder = "未自动识别到，可手动填写";
        }
      }

      var total = best.questions.length;
      $("status").textContent = "解析完成：" + total + " 题\n正在导出（勾选：" + formats.join(" / ") + "）…";

      // 无答案提示（章节测验已批阅回顾页只有“我的答案”）
      if (best.note) {
        var noteBox = $("result");
        noteBox.textContent = "⚠ " + best.note;
        noteBox.className = "warn";
      }

      // 交给 background 下载图片并生成文件（课程名以输入框为准）
      var finalMeta = best.meta;
      var manualCourse = courseInput.value.trim();
      if (manualCourse) finalMeta.course = manualCourse;
      finalMeta.frameUrl = best.frameUrl;

      chrome.runtime.sendMessage({
        type: "export",
        meta: finalMeta,
        questions: best.questions,
        formats: formats,
        tabId: tabId
      }, function (resp) {
        btn.disabled = false;
        if (!resp) {
          $("status").textContent = "后台处理无响应，请重新尝试";
          $("status").className = "err";
          return;
        }
        if (!resp.ok) {
          $("status").textContent = "导出失败：" + (resp.error || "未知错误");
          $("status").className = "err";
          return;
        }
        var files = resp.files || [];
        $("status").textContent = "✅ 完成！共 " + total + " 题";
        $("status").className = "ok";
        $("result").textContent =
          "已导出 " + files.length + " 个文件：\n" + files.join("\n") +
          (resp.images > 0 ? "\n图片 " + resp.images + " 张（见 ..._图片 文件夹）" : "");
        $("result").className = "ok";
      });
    });
  });
});
