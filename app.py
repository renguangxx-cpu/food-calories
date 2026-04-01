#!/usr/bin/env python3
"""
食物热量计算器 Web 应用
运行: python3 app.py
访问: http://localhost:5000
"""

import base64
import io
import os
from pathlib import Path

from google import genai
from google.genai import types
from flask import Flask, jsonify, render_template_string, request
from PIL import Image

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20MB 上限（HEIC 原图较大）

CALORIE_PROMPT = """请仔细分析这张食物图片，识别其中的食物并估算热量。

请按以下格式回答：

## 🍽️ 食物识别
列出图片中识别到的所有食物和饮料。

## 📊 热量估算
| 食物 | 估计分量 | 热量 (kcal) |
|------|---------|------------|
| ...  | ...     | ...        |

## 🔥 总热量
**合计：约 XXX - XXX kcal**

## 💪 营养摘要
- 蛋白质 / 碳水化合物 / 脂肪的大致比例
- 简短健康建议

注意：如果图片中没有食物，请告知。热量估算仅供参考。"""

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>食物热量计算器</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
    background: #f5f5f7;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 32px 16px 60px;
  }
  h1 { font-size: 26px; font-weight: 700; color: #1d1d1f; margin-bottom: 6px; text-align: center; }
  .subtitle { color: #6e6e73; font-size: 14px; margin-bottom: 24px; text-align: center; }
  .card {
    background: #fff;
    border-radius: 18px;
    box-shadow: 0 2px 20px rgba(0,0,0,0.08);
    padding: 24px;
    width: 100%;
    max-width: 560px;
  }
  .upload-area {
    display: flex; flex-direction: column; align-items: center;
    border: 2px dashed #d1d1d6; border-radius: 14px; padding: 32px 20px;
    text-align: center; cursor: pointer; transition: all 0.2s; background: #fafafa;
    -webkit-tap-highlight-color: transparent; user-select: none; -webkit-user-select: none;
  }
  .upload-area:active { border-color: #007aff; background: #f0f7ff; }
  .upload-icon { font-size: 40px; margin-bottom: 10px; }
  .upload-text { color: #1d1d1f; font-size: 15px; font-weight: 500; margin-bottom: 4px; }
  .upload-hint { color: #8e8e93; font-size: 12px; }
  #preview-wrap { display: none; margin-top: 16px; text-align: center; }
  #preview-img { max-width: 100%; max-height: 240px; border-radius: 12px; object-fit: contain; box-shadow: 0 2px 12px rgba(0,0,0,0.12); }
  .preview-name { color: #6e6e73; font-size: 12px; margin-top: 6px; }
  .btn {
    display: block; width: 100%; padding: 13px; margin-top: 14px;
    border: none; border-radius: 12px; font-size: 15px; font-weight: 600;
    cursor: pointer; transition: all 0.2s;
  }
  .btn-primary { background: #007aff; color: #fff; }
  .btn-primary:hover:not(:disabled) { background: #0066d6; }
  .btn-primary:disabled { background: #b4d0f7; cursor: not-allowed; }
  .btn-secondary { background: #f2f2f7; color: #1d1d1f; }
  .btn-secondary:hover { background: #e5e5ea; }
  .btn-green { background: #34c759; color: #fff; }
  .btn-green:hover { background: #28a745; }
  #status { display: none; text-align: center; padding: 16px 0 4px; }
  .spinner {
    display: inline-block; width: 28px; height: 28px;
    border: 3px solid #e5e5ea; border-top-color: #007aff;
    border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 8px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .status-text { color: #6e6e73; font-size: 13px; }
  #error-box {
    display: none; background: #fff2f2; border: 1px solid #ffd5d5;
    border-radius: 12px; padding: 12px 16px; color: #c0392b; font-size: 13px; margin-top: 12px;
  }

  /* 结果卡片 */
  .result-card {
    background: #fff; border-radius: 18px;
    box-shadow: 0 2px 20px rgba(0,0,0,0.08);
    width: 100%; max-width: 560px; margin-top: 16px; overflow: hidden;
  }
  .result-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 20px; border-bottom: 1px solid #f2f2f7; cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }
  .result-header-left { display: flex; align-items: center; gap: 12px; }
  .result-thumb { width: 44px; height: 44px; border-radius: 8px; object-fit: cover; background: #f2f2f7; flex-shrink: 0; }
  .result-meta { display: flex; flex-direction: column; gap: 2px; }
  .result-time { font-size: 12px; color: #8e8e93; }
  .result-calories { font-size: 15px; font-weight: 700; color: #1d1d1f; }
  .result-chevron { color: #c7c7cc; font-size: 18px; transition: transform 0.2s; }
  .result-chevron.open { transform: rotate(90deg); }
  .result-body { display: none; padding: 0 20px 16px; }
  .result-body.open { display: block; }
  .result-content { color: #1d1d1f; font-size: 14px; line-height: 1.7; padding-top: 12px; }
  .result-content h2 { font-size: 14px; margin: 14px 0 6px; color: #1d1d1f; }
  .result-content table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 13px; }
  .result-content th { background: #f2f2f7; padding: 7px 10px; text-align: left; font-weight: 600; border-bottom: 1px solid #e5e5ea; }
  .result-content td { padding: 7px 10px; border-bottom: 1px solid #f2f2f7; }
  .result-content tr:last-child td { border-bottom: none; }
  .result-content strong { font-weight: 700; }
  .result-content li { margin: 3px 0; padding-left: 4px; }
  .result-content ul { padding-left: 18px; }
  .result-content p { margin: 4px 0; }
  .result-actions { display: flex; gap: 8px; margin-top: 12px; }
  .btn-sm {
    flex: 1; padding: 9px; border: none; border-radius: 10px;
    font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s;
  }
  .btn-sm-copy { background: #f2f2f7; color: #1d1d1f; }
  .btn-sm-copy:hover { background: #e5e5ea; }
  .btn-sm-del { background: #fff2f2; color: #c0392b; }
  .btn-sm-del:hover { background: #ffd5d5; }
  .copied-tip { color: #34c759; font-size: 12px; margin-top: 6px; text-align: center; display: none; }

  /* 历史汇总区 */
  #history-section { width: 100%; max-width: 560px; margin-top: 20px; }
  .history-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
  .history-title { font-size: 16px; font-weight: 700; color: #1d1d1f; }
  .history-total { font-size: 13px; color: #6e6e73; }
  #coach-btn-wrap { margin-top: 12px; }
</style>
</head>
<body>

<h1>\U0001f37d\ufe0f 食物热量计算器</h1>
<p class="subtitle">上传食物照片，AI 自动识别并估算热量</p>

<div class="card">
  <input type="file" id="file-input" accept="image/*" style="display:none">
  <label for="file-input" class="upload-area">
    <span class="upload-icon">\U0001f4f7</span>
    <span class="upload-text">点击选择食物图片</span>
    <span class="upload-hint">支持 JPG、PNG、HEIC、WEBP，最大 20MB</span>
  </label>
  <div id="preview-wrap">
    <img id="preview-img" src="" alt="预览">
    <div class="preview-name" id="preview-name"></div>
  </div>
  <div id="error-box"></div>
  <div id="status">
    <div class="spinner"></div>
    <div class="status-text">AI 正在识别食物并计算热量…</div>
  </div>
  <button class="btn btn-primary" id="analyze-btn" disabled>分析热量</button>
  <button class="btn btn-secondary" id="reset-btn" style="display:none">重新选择</button>
</div>

<div id="history-section" style="display:none">
  <div class="history-header">
    <span class="history-title">今日记录</span>
    <span class="history-total" id="history-total"></span>
  </div>
  <div id="records-list"></div>
  <div id="coach-btn-wrap">
    <button class="btn btn-green" id="coach-btn">\U0001f4cb 一键复制发给教练</button>
    <div class="copied-tip" id="coach-tip">已复制到剪贴板 \u2713</div>
  </div>
</div>

<script>
  var fileInput    = document.getElementById('file-input');
  var previewWrap  = document.getElementById('preview-wrap');
  var previewImg   = document.getElementById('preview-img');
  var previewName  = document.getElementById('preview-name');
  var analyzeBtn   = document.getElementById('analyze-btn');
  var resetBtn     = document.getElementById('reset-btn');
  var statusDiv    = document.getElementById('status');
  var errorBox     = document.getElementById('error-box');
  var recordsList  = document.getElementById('records-list');
  var histSection  = document.getElementById('history-section');
  var histTotal    = document.getElementById('history-total');
  var coachBtn     = document.getElementById('coach-btn');
  var coachTip     = document.getElementById('coach-tip');

  var selectedFile = null;
  var previewDataUrl = '';
  var records = [];  // [{time, fileName, thumb, rawText, calories}]

  fileInput.addEventListener('change', function() {
    var f = fileInput.files && fileInput.files[0];
    if (f) handleFile(f);
  });

  function handleFile(file) {
    var t = file.type || '';
    if (t && t.indexOf('image/') !== 0 && t !== 'application/octet-stream') {
      showError('请选择图片文件（JPG、PNG、HEIC、WEBP 等）');
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      showError('图片超过 20MB，请压缩后再试');
      return;
    }
    selectedFile = file;
    previewDataUrl = '';
    hideError();
    previewName.textContent = file.name;
    previewImg.src = '';
    previewWrap.style.display = 'block';
    analyzeBtn.disabled = false;
    resetBtn.style.display = 'block';
    var reader = new FileReader();
    reader.onload = function(e) { previewDataUrl = e.target.result; previewImg.src = previewDataUrl; };
    reader.onerror = function() {};
    reader.readAsDataURL(file);
  }

  analyzeBtn.addEventListener('click', function() {
    if (!selectedFile) return;
    analyzeBtn.disabled = true;
    statusDiv.style.display = 'block';
    hideError();
    var formData = new FormData();
    formData.append('image', selectedFile);
    var capturedThumb = previewDataUrl;
    var capturedName  = selectedFile.name;
    fetch('/analyze', { method: 'POST', body: formData })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        statusDiv.style.display = 'none';
        analyzeBtn.disabled = false;
        if (data.error) { showError(data.error); return; }
        var now = new Date();
        var timeStr = now.getHours() + ':' + String(now.getMinutes()).padStart(2,'0');
        var dateStr = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
        var cal = extractCalories(data.result);
        var rec = { date: dateStr, time: timeStr, fileName: capturedName, thumb: capturedThumb, rawText: data.result, calories: cal };
        records.unshift(rec);
        renderRecords();
        // 滚动到第一条记录
        histSection.style.display = 'block';
        setTimeout(function() { histSection.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 100);
      })
      .catch(function() {
        statusDiv.style.display = 'none';
        analyzeBtn.disabled = false;
        showError('网络错误，请检查连接后重试');
      });
  });

  resetBtn.addEventListener('click', function() {
    selectedFile = null; previewDataUrl = '';
    fileInput.value = '';
    previewWrap.style.display = 'none';
    analyzeBtn.disabled = true;
    resetBtn.style.display = 'none';
    hideError();
  });

  function renderRecords() {
    recordsList.innerHTML = '';
    var totalLow = 0, totalHigh = 0;
    records.forEach(function(rec, idx) {
      totalLow  += rec.calories[0];
      totalHigh += rec.calories[1];
      var div = document.createElement('div');
      div.className = 'result-card';
      div.innerHTML =
        '<div class="result-header" onclick="toggleRecord(' + idx + ',this)">' +
          '<div class="result-header-left">' +
            '<img class="result-thumb" src="' + (rec.thumb || '') + '" onerror="this.style.display=\'none\'">' +
            '<div class="result-meta">' +
              '<span class="result-time">' + rec.date + ' ' + rec.time + (records.length > 1 ? '  \u7b2c' + (records.length - idx) + '\u9910' : '') + '</span>' +
              '<span class="result-calories">' + (rec.calories[0] ? rec.calories[0] + ' - ' + rec.calories[1] + ' kcal' : '热量未识别') + '</span>' +
            '</div>' +
          '</div>' +
          '<span class="result-chevron" id="chev-' + idx + '">\u203a</span>' +
        '</div>' +
        '<div class="result-body" id="body-' + idx + '">' +
          '<div class="result-content">' + markdownToHtml(rec.rawText) + '</div>' +
          '<div class="result-actions">' +
            '<button class="btn-sm btn-sm-copy" onclick="copyRecord(' + idx + ',this)">复制此条</button>' +
            '<button class="btn-sm btn-sm-del"  onclick="deleteRecord(' + idx + ')">删除</button>' +
          '</div>' +
          '<div class="copied-tip" id="tip-' + idx + '">已复制 \u2713</div>' +
        '</div>';
      recordsList.appendChild(div);
      // 最新一条默认展开
      if (idx === 0) toggleRecord(0, div.querySelector('.result-header'));
    });
    var lo = totalLow, hi = totalHigh;
    histTotal.textContent = records.length + ' 餐 | 合计约 ' + lo + ' - ' + hi + ' kcal';
  }

  function toggleRecord(idx, headerEl) {
    var body = document.getElementById('body-' + idx);
    var chev = document.getElementById('chev-' + idx);
    var isOpen = body.classList.contains('open');
    body.classList.toggle('open', !isOpen);
    chev.classList.toggle('open', !isOpen);
  }

  function deleteRecord(idx) {
    records.splice(idx, 1);
    if (records.length === 0) { histSection.style.display = 'none'; return; }
    renderRecords();
  }

  function copyRecord(idx, btn) {
    var text = formatForCoach([records[idx]]);
    copyToClipboard(text, function() {
      var tip = document.getElementById('tip-' + idx);
      tip.style.display = 'block';
      setTimeout(function() { tip.style.display = 'none'; }, 2000);
    });
  }

  coachBtn.addEventListener('click', function() {
    var text = formatForCoach(records.slice().reverse());
    copyToClipboard(text, function() {
      coachTip.style.display = 'block';
      setTimeout(function() { coachTip.style.display = 'none'; }, 2500);
    });
  });

  function formatForCoach(recs) {
    var lines = ['\U0001f4ca \u996e\u98df\u70ed\u91cf\u8bb0\u5f55'];
    if (recs.length > 0) lines.push('\u65e5\u671f\uff1a' + recs[0].date);
    lines.push('');
    recs.forEach(function(rec, i) {
      lines.push('\u3010\u7b2c' + (i+1) + '\u9910\u3011' + rec.time);
      // 提取食物列表行
      var foodLines = rec.rawText.split('\\n').filter(function(l) {
        return l.match(/^\|/) && !l.match(/[-:]{3}/) && !l.match(/\u98df\u7269.*\u70ed\u91cf/);
      });
      foodLines.forEach(function(l) {
        var cells = l.replace(/^\||\|$/g,'').split('|').map(function(c){return c.trim();});
        if (cells[0] && cells[0] !== '...' && cells.length >= 3)
          lines.push('  ' + cells[0] + '  ' + cells[1] + '  ' + cells[2]);
      });
      if (rec.calories[0]) lines.push('\u70ed\u91cf\uff1a\u7ea6 ' + rec.calories[0] + ' - ' + rec.calories[1] + ' kcal');
      lines.push('');
    });
    var totalLow = 0, totalHigh = 0;
    recs.forEach(function(r){ totalLow += r.calories[0]; totalHigh += r.calories[1]; });
    if (recs.length > 1) lines.push('\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014');
    lines.push('\u4eca\u65e5\u5408\u8ba1\uff1a\u7ea6 ' + totalLow + ' - ' + totalHigh + ' kcal');
    return lines.join('\\n');
  }

  function extractCalories(text) {
    // 匹配"约 800 - 1000"或"约800~1000"等格式
    var m = text.match(/\u5408\u8ba1[^\d]*(\d+)\s*[-~\uff5e]\s*(\d+)/);
    if (m) return [parseInt(m[1]), parseInt(m[2])];
    m = text.match(/(\d{3,4})\s*[-~\uff5e]\s*(\d{3,4})\s*kcal/i);
    if (m) return [parseInt(m[1]), parseInt(m[2])];
    m = text.match(/(\d{3,4})\s*kcal/i);
    if (m) return [parseInt(m[1]), parseInt(m[1])];
    return [0, 0];
  }

  function copyToClipboard(text, cb) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(cb).catch(function() { fallbackCopy(text, cb); });
    } else { fallbackCopy(text, cb); }
  }

  function fallbackCopy(text, cb) {
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.focus(); ta.select();
    try { document.execCommand('copy'); cb(); } catch(e) {}
    document.body.removeChild(ta);
  }

  function showError(msg) { errorBox.textContent = '\u26a0\ufe0f ' + msg; errorBox.style.display = 'block'; }
  function hideError() { errorBox.style.display = 'none'; }

  function markdownToHtml(md) {
    var lines = md.split('\\n');
    var html = '', inTable = false, tableHtml = '';
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (/^\|/.test(line)) {
        var cells = line.replace(/^\||\|$/g,'').split('|').map(function(c){return c.trim();});
        if (cells.every(function(c){return /^[-: ]+$/.test(c);})) continue;
        if (!inTable) {
          inTable = true; tableHtml = '<table><thead><tr>';
          cells.forEach(function(c){ tableHtml += '<th>' + inline(c) + '</th>'; });
          tableHtml += '</tr></thead><tbody>';
        } else {
          tableHtml += '<tr>';
          cells.forEach(function(c){ tableHtml += '<td>' + inline(c) + '</td>'; });
          tableHtml += '</tr>';
        }
        continue;
      } else if (inTable) { html += tableHtml + '</tbody></table>'; inTable = false; tableHtml = ''; }
      if (/^## /.test(line))  { html += '<h2>' + inline(line.slice(3)) + '</h2>'; continue; }
      if (/^### /.test(line)) { html += '<h3>' + inline(line.slice(4)) + '</h3>'; continue; }
      if (/^[-*] /.test(line)){ html += '<li>' + inline(line.slice(2)) + '</li>'; continue; }
      if (line.trim() === '')  { html += '<br>'; continue; }
      html += '<p>' + inline(line) + '</p>';
    }
    if (inTable) html += tableHtml + '</tbody></table>';
    return html;
  }

  function inline(t) {
    return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
            .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
            .replace(/\*(.+?)\*/g,'<em>$1</em>');
  }
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


def convert_to_jpeg(file_bytes: bytes) -> bytes:
    """用 Pillow 打开任意格式图片，统一转为 JPEG 返回。"""
    img = Image.open(io.BytesIO(file_bytes))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@app.route("/analyze", methods=["POST"])
def analyze():
    if "image" not in request.files:
        return jsonify({"error": "未收到图片文件"}), 400

    file = request.files["image"]
    if not file.filename and not file.content_type:
        return jsonify({"error": "文件无效"}), 400

    raw_bytes = file.read()
    if not raw_bytes:
        return jsonify({"error": "文件内容为空"}), 400

    # 用 Pillow 统一转换：支持 HEIC/HEIF/JPG/PNG/WEBP/GIF 等所有格式
    try:
        jpeg_bytes = convert_to_jpeg(raw_bytes)
    except Exception as e:
        return jsonify({"error": f"无法识别图片格式，请换一张照片（{e}）"}), 400

    image_data = base64.standard_b64encode(jpeg_bytes).decode("utf-8")
    media_type = "image/jpeg"

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "服务器未配置 API Key，请联系管理员"}), 500

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"),
                types.Part.from_text(text=CALORIE_PROMPT),
            ],
        )
        return jsonify({"result": response.text})

    except Exception as e:
        err = str(e)
        if "API_KEY_INVALID" in err or "API key" in err:
            return jsonify({"error": "API Key 无效"}), 500
        if "quota" in err.lower() or "rate" in err.lower():
            return jsonify({"error": "请求过于频繁，请稍后再试"}), 429
        return jsonify({"error": f"分析失败：{err}"}), 500


if __name__ == "__main__":
    if not os.environ.get("GEMINI_API_KEY"):
        print("⚠️  警告：未设置 GEMINI_API_KEY 环境变量")
        print("   运行前请执行: export GEMINI_API_KEY='your-api-key'")
        print()
    print("🍽️  食物热量计算器启动中...")
    port = int(os.environ.get("PORT", 8080))
    print(f"   打开 Safari 访问: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
