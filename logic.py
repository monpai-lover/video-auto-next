from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Mapping, Optional

NEXT_STATUS_TOKENS = ('开始观看', '继续学习', '下一节', '未学习')
CURRENT_STATUS_TOKENS = ('正在播放',)
COLLECTION_SKIP_TOKENS = ('已完成',)
NAVIGATION_ERROR_TOKENS = (
    'execution context was destroyed',
    'most likely because of a navigation',
    'cannot find context with specified id',
)
VIDEO_TAB_LABELS = ('视频', '视频课程')


def normalize_text(value: str) -> str:
    return ''.join(value.split())


def is_false_end_jump(duration: float, current_time: float, watch_elapsed: float, *, safe_margin: float = 2.0, early_window: float = 8.0) -> bool:
    if duration <= 0:
        return False
    return current_time >= duration - safe_margin and watch_elapsed <= early_window


def is_current_item(status: str) -> bool:
    normalized = normalize_text(status)
    return any(token in normalized for token in CURRENT_STATUS_TOKENS)


def is_next_item(status: str) -> bool:
    normalized = normalize_text(status)
    return any(token in normalized for token in NEXT_STATUS_TOKENS)


def choose_next_item_after_current(rows: Iterable[Mapping[str, str]]) -> Optional[str]:
    found_current = False
    for row in rows:
        status = row.get('status', '')
        if is_current_item(status):
            found_current = True
            continue
        if found_current and is_next_item(status):
            return row.get('title')
    return None


def choose_next_item_label(rows: Iterable[Mapping[str, str]]) -> Optional[str]:
    preferred = choose_next_item_after_current(rows)
    if preferred:
        return preferred
    for row in rows:
        if is_next_item(row.get('status', '')):
            return row.get('title')
    return None


def get_repair_strategy_order(*, has_videojs: bool) -> list[str]:
    if has_videojs:
        return ['videojs', 'native', 'progress']
    return ['native', 'progress']


def get_collection_visit_order(rows: Iterable[Mapping[str, str]]) -> list[str]:
    links = [row['href'] for row in rows if row.get('href')]
    links.reverse()
    return links


def filter_playable_collections(rows: Iterable[Mapping[str, str]]) -> list[str]:
    playable = []
    for row in rows:
        href = row.get('href')
        status = normalize_text(row.get('status', ''))
        if not href:
            continue
        if any(token in status for token in COLLECTION_SKIP_TOKENS):
            continue
        playable.append(href)
    return playable


def get_autoplay_strategy_order() -> list[str]:
    return ['click-current', 'videojs-play', 'big-play-button']


def is_navigation_context_error(message: str) -> bool:
    normalized = (message or '').lower()
    return any(token in normalized for token in NAVIGATION_ERROR_TOKENS)


def get_collection_script_template(parent_selector: str, title_selector: str, link_selector: str, status_selector: str) -> str:
    return f"""
    () => [...document.querySelectorAll('{parent_selector}')].map((node, index) => ({{
      index,
      title: node.querySelector('{title_selector}')?.innerText?.trim() ?? '',
      href: node.querySelector('{link_selector}')?.getAttribute('href') ?? '',
      status: node.querySelector('{status_selector}')?.innerText?.trim() ?? ''
    }})).filter(row => row.href)
    """


def get_auth_state_path(profile_dir: str) -> str:
    return str(Path(profile_dir) / 'auth_state.json')


def get_video_tab_labels() -> tuple[str, ...]:
    return VIDEO_TAB_LABELS


def build_storage_restore_script(storage_entries: list[dict]) -> str:
    payload = json.dumps(storage_entries, ensure_ascii=False)
    return f"""
    (() => {{
      const entries = {payload};
      const current = window.location.origin;
      for (const entry of entries) {{
        if (entry.origin !== current) continue;
        for (const item of (entry.localStorage || [])) {{
          window.localStorage.setItem(item.name, item.value);
        }}
        for (const item of (entry.sessionStorage || [])) {{
          window.sessionStorage.setItem(item.name, item.value);
        }}
      }}
    }})();
    """


def format_seconds_as_clock(total_seconds: int) -> str:
    hours, remainder = divmod(max(0, total_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f'{hours:02d}:{minutes:02d}:{seconds:02d}'
    return f'{minutes:02d}:{seconds:02d}'


def extract_study_time_display(text: str) -> Optional[str]:
    compact = re.sub(r'\s+', '', text or '')
    if not compact:
        return None

    clock_match = re.search(
        r'(?:学习累计时长|累计学习时长|累计时长|学习时长|累计学时|已学时长|已学时长|总学时)[：:]?(\d{1,2}:\d{2}(?::\d{2})?)',
        compact,
    )
    if clock_match:
        return clock_match.group(1)

    chinese_match = re.search(
        r'(?:学习累计时长|累计学习时长|累计时长|学习时长|累计学时|已学时长|总学时)[：:]?'
        r'(?:(\d+)小时)?(?:(\d+)分)?(?:(\d+)秒)?',
        compact,
    )
    if chinese_match and any(part is not None for part in chinese_match.groups()):
        hours = int(chinese_match.group(1) or 0)
        minutes = int(chinese_match.group(2) or 0)
        seconds = int(chinese_match.group(3) or 0)
        return format_seconds_as_clock(hours * 3600 + minutes * 60 + seconds)

    decimal_hours_match = re.search(
        r'(?:当前累计学时|累计学时|总学时|学习时长信息.*?当前累计学时).*?(?:单位[:：]?小时)?.*?(\d+(?:\.\d+)?)',
        compact,
    )
    if decimal_hours_match:
        return f'{decimal_hours_match.group(1)}小时'

    return None


def build_study_time_overlay_text(value: Optional[str]) -> str:
    return f'累计学习时长：{value or "读取中..."}'
