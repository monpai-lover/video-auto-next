# Video Auto Next Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个本地 Python 程序，复用浏览器登录态，修复视频误跳到最后一秒的问题，并在真实播放结束后自动切换下一节。

**Architecture:** 采用 Python + Playwright。将纯逻辑判定与浏览器交互拆开：`logic.py` 负责误跳尾判定、文本匹配、下一节选择；`main.py` 负责浏览器启动、页面检测、修复播放进度和自动跳转。优先通过 DOM 与 HTML5 video 修复，必要时再回退到进度条拖动或点击下一节。

**Tech Stack:** Python 3、unittest、Playwright

---

### Task 1: 项目骨架与纯逻辑测试

**Files:**
- Create: `video-auto-next/logic.py`
- Create: `video-auto-next/tests/test_logic.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from logic import is_false_end_jump, normalize_text, choose_next_item_label

class LogicTests(unittest.TestCase):
    def test_false_end_jump_detected_when_video_near_end_too_early(self):
        self.assertTrue(is_false_end_jump(duration=1200, current_time=1199, watch_elapsed=3))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/goatdie/video-auto-next && python3 -m unittest tests/test_logic.py -v`
Expected: FAIL with `ModuleNotFoundError` or missing function error

- [ ] **Step 3: Write minimal implementation**

```python
def is_false_end_jump(duration: float, current_time: float, watch_elapsed: float) -> bool:
    return duration > 0 and current_time >= duration - 2 and watch_elapsed <= 8
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/goatdie/video-auto-next && python3 -m unittest tests/test_logic.py -v`
Expected: PASS

### Task 2: 文本匹配与下一节选择逻辑

**Files:**
- Modify: `video-auto-next/logic.py`
- Modify: `video-auto-next/tests/test_logic.py`

- [ ] **Step 1: Write the failing test**

```python
    def test_choose_next_item_prefers_start_watch_status(self):
        rows = [
            {"title": "1-xxx", "status": "已完成"},
            {"title": "2-xxx", "status": "开始观看"},
        ]
        self.assertEqual(choose_next_item_label(rows), "2-xxx")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/goatdie/video-auto-next && python3 -m unittest tests/test_logic.py -v`
Expected: FAIL with missing function or wrong return value

- [ ] **Step 3: Write minimal implementation**

```python
def choose_next_item_label(rows):
    for row in rows:
        status = normalize_text(row.get("status", ""))
        if any(token in status for token in ("开始观看", "继续学习", "下一节", "未学习")):
            return row.get("title")
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/goatdie/video-auto-next && python3 -m unittest tests/test_logic.py -v`
Expected: PASS

### Task 3: 浏览器控制最小实现

**Files:**
- Create: `video-auto-next/main.py`
- Create: `video-auto-next/README.md`

- [ ] **Step 1: Write the failing test**

```python
# 本任务不做浏览器集成自动化测试，改为在 README 中写出手动验证步骤，
# 并保持纯逻辑已有测试覆盖关键判定。
```

- [ ] **Step 2: Write minimal implementation**

```python
# main.py 提供 CLI：
# python3 main.py --url <课程页> --profile-dir ./browser-profile --safe-seek 2
# 核心流程：
# 1. 启动持久化浏览器
# 2. 打开页面并等待用户确认已登录
# 3. 轮询 video/current row/button
# 4. 检测误跳尾后 seek 到 safe-seek 秒
# 5. 正常播放完成后点击下一节
```

- [ ] **Step 3: Run verification**

Run: `cd /Users/goatdie/video-auto-next && python3 -m py_compile logic.py main.py && python3 -m unittest tests/test_logic.py -v`
Expected: PASS

### Task 4: 使用说明与人工验证步骤

**Files:**
- Modify: `video-auto-next/README.md`

- [ ] **Step 1: Document install and run commands**

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
cd /Users/goatdie/video-auto-next
python3 main.py --url 'https://example.com/course'
```

- [ ] **Step 2: Document manual verification**

```text
1. 进入课程页并确保已登录。
2. 观察脚本是否在误跳到最后一秒时自动拉回到 2 秒。
3. 观察真实播完后是否切换到下一节。
4. 若页面按钮文案不同，按 README 中的方法补充选择器关键词。
```
