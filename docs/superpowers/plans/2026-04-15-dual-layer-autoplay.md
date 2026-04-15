# Dual-Layer Autoplay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建父页面集合调度 + 详情页集合内视频自动播放的双层自动化流程，并修复进入集合后不自动播放的问题。

**Architecture:** 在现有站点专用脚本上增加“父页面集合抓取与倒序调度器”，先从集合列表页提取所有 `#/trainDetail` 链接并倒序访问，再复用现有详情页播放器逻辑播放集合内未完成视频。详情页播放前增加自动开播修复，优先点击当前可播放项、Video.js API 播放和大播放按钮兜底。

**Tech Stack:** Python 3、unittest、Playwright

---

### Task 1: 双层调度纯逻辑测试

**Files:**
- Modify: `video-auto-next/logic.py`
- Modify: `video-auto-next/tests/test_logic.py`

- [ ] **Step 1: Write the failing test**

```python
def test_reverse_collection_order_returns_last_to_first():
    rows = [
        {'title': 'A', 'href': '#/trainDetail?id=1', 'status': '未开始'},
        {'title': 'B', 'href': '#/trainDetail?id=2', 'status': '未开始'},
    ]
    self.assertEqual(get_collection_visit_order(rows), ['#/trainDetail?id=2', '#/trainDetail?id=1'])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/goatdie/video-auto-next && python3 -m unittest tests/test_logic.py -v`
Expected: FAIL with missing function import

- [ ] **Step 3: Write minimal implementation**

```python
def get_collection_visit_order(rows):
    links = [row['href'] for row in rows if row.get('href')]
    links.reverse()
    return links
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/goatdie/video-auto-next && python3 -m unittest tests/test_logic.py -v`
Expected: PASS

### Task 2: 父页面集合抓取与倒序直达

**Files:**
- Modify: `video-auto-next/main.py`
- Modify: `video-auto-next/README.md`

- [ ] **Step 1: Write the failing test**

```python
def test_pick_unfinished_collection_rows_filters_finished_items():
    rows = [
        {'title': 'A', 'href': '#/trainDetail?id=1', 'status': '未开始'},
        {'title': 'B', 'href': '#/trainDetail?id=2', 'status': '已完成'},
    ]
    self.assertEqual(filter_playable_collections(rows), ['#/trainDetail?id=1'])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/goatdie/video-auto-next && python3 -m unittest tests/test_logic.py -v`
Expected: FAIL with missing function import

- [ ] **Step 3: Write minimal implementation**

```python
def filter_playable_collections(rows):
    return [row['href'] for row in rows if '已完成' not in normalize_text(row.get('status', '')) and row.get('href')]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/goatdie/video-auto-next && python3 -m unittest tests/test_logic.py -v`
Expected: PASS

### Task 3: 集合详情页自动开播修复

**Files:**
- Modify: `video-auto-next/main.py`
- Modify: `video-auto-next/tests/test_logic.py`

- [ ] **Step 1: Write the failing test**

```python
def test_autoplay_strategy_order_prefers_click_then_videojs_then_big_button():
    self.assertEqual(get_autoplay_strategy_order(), ['click-current', 'videojs-play', 'big-play-button'])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/goatdie/video-auto-next && python3 -m unittest tests/test_logic.py -v`
Expected: FAIL with missing function import

- [ ] **Step 3: Write minimal implementation**

```python
def get_autoplay_strategy_order():
    return ['click-current', 'videojs-play', 'big-play-button']
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/goatdie/video-auto-next && python3 -m unittest tests/test_logic.py -v`
Expected: PASS

### Task 4: 编译、测试、README 更新

**Files:**
- Modify: `video-auto-next/README.md`

- [ ] **Step 1: Run verification**

Run: `cd /Users/goatdie/video-auto-next && python3 -m py_compile logic.py main.py && python3 -m unittest tests/test_logic.py -v`
Expected: PASS
