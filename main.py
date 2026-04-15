from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from logic import (
    build_storage_restore_script,
    choose_next_item_after_current,
    choose_next_item_label,
    filter_playable_collections,
    get_autoplay_strategy_order,
    get_auth_state_path,
    get_collection_script_template,
    get_collection_visit_order,
    get_video_tab_labels,
    get_repair_strategy_order,
    is_false_end_jump,
    is_navigation_context_error,
    normalize_text,
)

VIDEO_SELECTOR = '.video-player .vjs-tech'
PLAYER_ROOT_SELECTOR = '.video-player .video-js'
BIG_PLAY_SELECTOR = '.vjs-big-play-button'
PROGRESS_SELECTOR = '.vjs-progress-holder.vjs-slider'
ITEM_SELECTOR = '.video_list .video_list_item'
ITEM_TITLE_SELECTOR = '.play_title > span'
ITEM_STATUS_SELECTOR = '.play_status span'
PARENT_COLLECTION_SELECTOR = '.onlineTrain_li'
PARENT_LINK_SELECTOR = '.btn a[href*="#/trainDetail"]'
PARENT_TITLE_SELECTOR = '.right .main .title'
PARENT_STATUS_SELECTOR = '.btn div'
VIDEO_TAB_CONTENT_SELECTOR = '.video_list, .video_box .video_list'
NEXT_TEXT_TOKENS = ('开始观看', '下一节', '下一集', '继续学习', '继续观看')
CLOSE_TEXT_TOKENS = ('关闭', '知道了', '我知道了', '稍后', '取消', '确定', '确认')
WATCHED_DURATION_TOLERANCE_SECONDS = 5.0
ONLINE_TRAIN_PARENT_URL = 'https://peixun.tyjr.sh.gov.cn/azqPhoneService/#/onlineTrainList'


@dataclass
class PlayerSnapshot:
    exists: bool
    current_time: float = 0.0
    duration: float = 0.0
    paused: bool = True
    ended: bool = False
    src: str = ''
    title: str = ''
    current_display: str = ''
    duration_display: str = ''
    player_class: str = ''
    has_videojs: bool = False

    @property
    def key(self) -> str:
        return self.src or self.title or 'unknown'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='自动修复误跳尾并切换下一节/下一集合的视频站脚本（退役军人课程站增强版）')
    parser.add_argument('--url', required=True, help='父页面或课程详情页 URL')
    parser.add_argument('--profile-dir', default='browser-profile', help='浏览器用户数据目录，用于复用登录态')
    parser.add_argument('--safe-seek', type=float, default=2.0, help='误跳尾时拉回到的秒数，默认 2 秒')
    parser.add_argument('--poll-interval', type=float, default=2.0, help='轮询间隔秒数')
    parser.add_argument('--login-wait', action='store_true', help='打开页面后等待你手动登录，再按回车继续')
    parser.add_argument('--headless', action='store_true', help='无头模式运行，不建议首次调试时使用')
    return parser.parse_args()


def read_auth_state(profile_dir: str) -> dict:
    path = Path(get_auth_state_path(profile_dir))
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        print(f"[warn] 读取登录态失败: {exc}")
        return {}


def install_storage_restore(context, auth_state: dict) -> None:
    storage_entries = auth_state.get('origins') or []
    if not storage_entries:
        return
    context.add_init_script(build_storage_restore_script(storage_entries))


def apply_auth_state(context, profile_dir: str) -> bool:
    auth_state = read_auth_state(profile_dir)
    if not auth_state:
        return False
    cookies = auth_state.get('cookies') or []
    if cookies:
        try:
            context.add_cookies(cookies)
        except Exception as exc:
            print(f"[warn] 恢复 cookies 失败: {exc}")
    install_storage_restore(context, auth_state)
    print(f"[info] 已加载登录态: {get_auth_state_path(profile_dir)}")
    return True


def capture_storage(page) -> dict:
    return safe_page_evaluate(
        page,
        """
        () => ({
          origin: window.location.origin,
          localStorage: Object.keys(window.localStorage).map((name) => ({ name, value: window.localStorage.getItem(name) ?? '' })),
          sessionStorage: Object.keys(window.sessionStorage).map((name) => ({ name, value: window.sessionStorage.getItem(name) ?? '' })),
        })
        """,
        default={},
        label='capture_storage',
    )


def save_auth_state(context, page, profile_dir: str) -> None:
    path = Path(get_auth_state_path(profile_dir))
    path.parent.mkdir(parents=True, exist_ok=True)
    auth_state = {
        'cookies': context.cookies(),
        'origins': [],
    }
    storage = capture_storage(page)
    if storage.get('origin'):
        auth_state['origins'].append(storage)
    path.write_text(json.dumps(auth_state, ensure_ascii=False, indent=2))
    print(f"[info] 已保存登录态: {path}")


def wait_for_manual_ready(login_wait: bool, *, prompt=input) -> None:
    if not login_wait:
        return
    prompt('如需手动登录或检查页面，请先处理完成，然后按回车继续...')


def wait_before_close(headless: bool, *, prompt=input) -> None:
    if headless:
        return
    prompt('任务已结束，页面将保持打开。确认后按回车关闭浏览器...')


def load_playwright():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise SystemExit(
            '缺少 playwright 依赖。先运行:\n'
            '  python3 -m pip install playwright\n'
            '  python3 -m playwright install chromium'
        ) from exc
    return sync_playwright, PlaywrightTimeoutError


def safe_page_evaluate(page, expression: str, arg=None, *, default=None, label: str = 'evaluate'):
    try:
        if arg is None:
            return page.evaluate(expression)
        return page.evaluate(expression, arg)
    except Exception as exc:
        if is_navigation_context_error(str(exc)):
            print(f"[warn] {label} 遇到页面导航，跳过本次 evaluate")
            return default
        raise


def has_response_code_failure(message: str) -> bool:
    return 'err_http_response_code_failure' in (message or '').lower()


def get_base_url(target_url: str) -> str:
    parts = urlsplit(target_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or '/', parts.query, ''))


def resolve_parent_url(target_url: str) -> str:
    normalized = (target_url or '').strip()
    if '#/trainDetail' in normalized or normalized.endswith('#/onlineTrain') or normalized.endswith('#/onlineTrainList'):
        return ONLINE_TRAIN_PARENT_URL
    return normalized


def goto_allowing_response_failure(page, target_url: str, *, timeout: int = 60_000) -> bool:
    try:
        page.goto(target_url, wait_until='domcontentloaded', timeout=timeout)
        return False
    except Exception as exc:
        if not has_response_code_failure(str(exc)):
            raise
        print(f'[warn] 页面返回非 2xx，继续等待页面可用: {target_url}')
        page.wait_for_load_state('domcontentloaded', timeout=timeout)
        return True


def open_url(page, target_url: str, *, timeout: int = 60_000) -> None:
    had_response_failure = goto_allowing_response_failure(page, target_url, timeout=timeout)
    if not had_response_failure or '#' not in target_url:
        return

    base_url = get_base_url(target_url)
    print(f'[warn] 直接打开失败，改为先加载基础页再切换 hash: {target_url}')
    goto_allowing_response_failure(page, base_url, timeout=timeout)
    safe_page_evaluate(
        page,
        '(url) => { window.location.href = url; }',
        target_url,
        label='open_url_hash_fallback',
    )


def dismiss_popups(page) -> None:
    for token in CLOSE_TEXT_TOKENS:
        locator = page.get_by_text(token, exact=False)
        count = min(locator.count(), 3)
        for index in range(count):
            try:
                target = locator.nth(index)
                if target.is_visible(timeout=150):
                    target.click(timeout=300)
                    return
            except Exception:
                continue


def is_parent_page(page) -> bool:
    try:
        return page.locator(PARENT_COLLECTION_SELECTOR).count() > 0 and page.locator(ITEM_SELECTOR).count() == 0
    except Exception:
        return False


def is_detail_page(page) -> bool:
    try:
        return page.locator(ITEM_SELECTOR).count() > 0 or page.locator(VIDEO_SELECTOR).count() > 0
    except Exception:
        return False


def collect_collections(page) -> list[dict[str, str]]:
    script = get_collection_script_template(
        PARENT_COLLECTION_SELECTOR,
        PARENT_TITLE_SELECTOR,
        PARENT_LINK_SELECTOR,
        PARENT_STATUS_SELECTOR,
    )
    rows = safe_page_evaluate(
        page,
        script,
        default=[],
        label='collect_collections',
    )
    print(f'[info] 抓取到 {len(rows)} 个视频集合')
    return rows


def make_absolute_url(current_url: str, href: str) -> str:
    if href.startswith('#'):
        return current_url.split('#', 1)[0] + href
    return urljoin(current_url, href)


def get_collection_targets(page) -> list[dict[str, str]]:
    rows = collect_collections(page)
    playable_links = filter_playable_collections(rows)
    visit_order = get_collection_visit_order([row for row in rows if row.get('href') in playable_links])
    targets = []
    row_by_href = {row['href']: row for row in rows}
    for href in visit_order:
        row = row_by_href[href]
        targets.append({
            'title': row.get('title', ''),
            'href': href,
            'url': make_absolute_url(page.url, href),
            'status': row.get('status', ''),
        })
    print(f'[info] 过滤后待播放集合数: {len(targets)}')
    return targets


def scroll_parent_collection_list(page) -> None:
    safe_page_evaluate(
        page,
        """
        () => {
          const list = document.querySelector('.van-list');
          const track = document.querySelector('.van-pull-refresh__track');
          if (list) list.scrollTop = list.scrollHeight;
          if (track) track.scrollTop = track.scrollHeight;
          window.scrollTo(0, document.body.scrollHeight);
        }
        """,
        default=None,
        label='scroll_parent_collection_list',
    )


def wait_for_collection_targets(page, *, timeout_seconds: float = 15.0, poll_interval: float = 0.5) -> list[dict[str, str]]:
    deadline = time.monotonic() + timeout_seconds
    best_targets: list[dict[str, str]] = []
    stable_rounds = 0
    while True:
        targets = get_collection_targets(page)
        if len(targets) > len(best_targets):
            best_targets = targets
            stable_rounds = 0
        elif targets and len(targets) == len(best_targets):
            stable_rounds += 1

        if best_targets and stable_rounds >= 2:
            return best_targets
        if time.monotonic() >= deadline:
            return best_targets
        scroll_parent_collection_list(page)
        time.sleep(poll_interval)


def collect_rows(page) -> list[dict[str, str]]:
    script = f"""
    () => [...document.querySelectorAll('{ITEM_SELECTOR}')].map((node, index) => ({{
      index,
      title: node.querySelector('{ITEM_TITLE_SELECTOR}')?.innerText?.trim() ?? '',
      status: node.querySelector('{ITEM_STATUS_SELECTOR}')?.innerText?.trim() ?? '',
      raw: node.innerText?.trim() ?? ''
    }})).filter(row => row.title)
    """
    return safe_page_evaluate(page, script, default=[], label='collect_rows')


def click_row_by_title(page, title: str) -> bool:
    rows = page.locator(ITEM_SELECTOR)
    for index in range(rows.count()):
        try:
            row = rows.nth(index)
            row_title = normalize_text(row.locator(ITEM_TITLE_SELECTOR).inner_text(timeout=300))
            if row_title == normalize_text(title):
                row.click(timeout=500)
                print(f'[action] 点击视频项: {title}')
                return True
        except Exception:
            continue
    return False


def click_text_token(page, token: str) -> bool:
    locator = page.get_by_text(token, exact=False)
    count = min(locator.count(), 5)
    for index in range(count):
        try:
            target = locator.nth(index)
            if target.is_visible(timeout=200):
                target.click(timeout=500)
                print(f'[action] 点击按钮: {token}')
                return True
        except Exception:
            continue
    return False


def click_next_video(page, require_current: bool = False) -> str | None:
    rows = collect_rows(page)
    next_label = choose_next_item_after_current(rows)
    if not next_label and not require_current:
        next_label = choose_next_item_label(rows)
    if next_label and click_row_by_title(page, next_label):
        return next_label
    if require_current:
        return None
    for token in NEXT_TEXT_TOKENS:
        if click_text_token(page, token):
            return token
    return None


def click_current_or_next_playable(page, preferred_title: str | None = None) -> str | None:
    if preferred_title and click_row_by_title(page, preferred_title):
        return preferred_title
    rows = collect_rows(page)
    current_label = None
    for row in rows:
        if '正在播放' in normalize_text(row.get('status', '')):
            current_label = row.get('title')
            break
    if current_label and click_row_by_title(page, current_label):
        return current_label
    next_label = choose_next_item_after_current(rows) or choose_next_item_label(rows)
    if next_label and click_row_by_title(page, next_label):
        return next_label
    return None


def parse_duration_text_to_seconds(value: str) -> float | None:
    text = (value or '').strip()
    if not text:
        return None
    parts = text.split(':')
    if not all(part.isdigit() for part in parts):
        return None
    try:
        if len(parts) == 2:
            minutes, seconds = map(int, parts)
            return float(minutes * 60 + seconds)
        if len(parts) == 3:
            hours, minutes, seconds = map(int, parts)
            return float(hours * 3600 + minutes * 60 + seconds)
    except ValueError:
        return None
    return None


def extract_watched_duration_seconds(row: dict[str, str]) -> float | None:
    raw = row.get('raw', '') or ''
    match = re.search(r'所看时长[:：]\s*(\d{1,2}:\d{2}(?::\d{2})?)', raw)
    if not match:
        return None
    return parse_duration_text_to_seconds(match.group(1))


def should_skip_by_watched_duration(snapshot: PlayerSnapshot, rows: list[dict[str, str]], *, tolerance_seconds: float = WATCHED_DURATION_TOLERANCE_SECONDS) -> bool:
    if not snapshot.exists or snapshot.duration <= 0 or not snapshot.title:
        return False
    target_title = normalize_text(snapshot.title)
    for row in rows:
        if normalize_text(row.get('title', '')) != target_title:
            continue
        watched_seconds = extract_watched_duration_seconds(row)
        if watched_seconds is None:
            return False
        return snapshot.duration - watched_seconds <= tolerance_seconds
    return False


def ensure_video_tab(page) -> bool:
    try:
        if page.locator(ITEM_SELECTOR).count() > 0 or page.locator(VIDEO_TAB_CONTENT_SELECTOR).count() > 0:
            return True
    except Exception:
        pass

    active_label = ''
    try:
        active_tab = page.locator('.van-tab--active').first
        if active_tab.count() > 0:
            active_label = normalize_text(active_tab.inner_text(timeout=300))
    except Exception:
        active_label = ''

    if active_label in get_video_tab_labels():
        try:
            return page.locator(ITEM_SELECTOR).count() > 0 or page.locator(VIDEO_TAB_CONTENT_SELECTOR).count() > 0
        except Exception:
            return False

    for label in get_video_tab_labels():
        try:
            tab = page.get_by_text(label, exact=True)
            if tab.count() > 0:
                tab.first.click(timeout=800)
                page.wait_for_timeout(800)
                if page.locator(ITEM_SELECTOR).count() > 0 or page.locator(VIDEO_TAB_CONTENT_SELECTOR).count() > 0:
                    print(f'[fix] 已自动切换到“{label}”标签页')
                    return True
        except Exception:
            continue
    return False


def snapshot_player(page) -> PlayerSnapshot:
    data = safe_page_evaluate(
        page,
        f"""
        () => {{
          const video = document.querySelector('{VIDEO_SELECTOR}');
          const currentItem = [...document.querySelectorAll('{ITEM_SELECTOR}')].find(
            node => (node.querySelector('{ITEM_STATUS_SELECTOR}')?.innerText || '').includes('正在播放')
          );
          const titleNode = currentItem?.querySelector('{ITEM_TITLE_SELECTOR}');
          const currentDisplay = document.querySelector('.vjs-current-time-display')?.innerText || '';
          const durationDisplay = document.querySelector('.vjs-duration-display')?.innerText || '';
          const playerRoot = document.querySelector('{PLAYER_ROOT_SELECTOR}');
          const hasVideoJs = !!(window.videojs || playerRoot?.player || playerRoot?.__vue__);
          return {{
            exists: !!video,
            currentTime: video?.currentTime ?? 0,
            duration: video?.duration ?? 0,
            paused: video ? video.paused : true,
            ended: video ? video.ended : false,
            src: video?.currentSrc ?? video?.src ?? '',
            title: titleNode?.innerText?.trim() ?? '',
            currentDisplay,
            durationDisplay,
            playerClass: playerRoot?.className ?? '',
            hasVideoJs
          }};
        }}
        """,
        default={},
        label='snapshot_player',
    )
    return PlayerSnapshot(
        exists=bool(data.get('exists')),
        current_time=float(data.get('currentTime') or 0.0),
        duration=float(data.get('duration') or 0.0),
        paused=bool(data.get('paused')),
        ended=bool(data.get('ended')),
        src=data.get('src') or '',
        title=normalize_text(data.get('title') or ''),
        current_display=normalize_text(data.get('currentDisplay') or ''),
        duration_display=normalize_text(data.get('durationDisplay') or ''),
        player_class=data.get('playerClass') or '',
        has_videojs=bool(data.get('hasVideoJs')),
    )

def ensure_playing(page) -> None:
    safe_page_evaluate(
        page,
        f"""
        () => {{
          const video = document.querySelector('{VIDEO_SELECTOR}');
          if (video && video.paused) {{
            video.muted = false;
            video.play().catch(() => {{}});
          }}
        }}
        """,
        default=None,
        label='ensure_playing',
    )

def autoplay_with_videojs(page) -> bool:
    result = safe_page_evaluate(
        page,
        f"""
        () => {{
          const root = document.querySelector('{PLAYER_ROOT_SELECTOR}');
          let player = null;
          if (root?.player) player = root.player;
          else if (window.videojs && root?.id) player = window.videojs(root.id);
          else if (window.videojs) {{
            const players = window.videojs.getPlayers ? window.videojs.getPlayers() : window.videojs.players;
            if (players) player = Object.values(players)[0] || null;
          }}
          if (!player) return false;
          try {{
            if (typeof player.play === 'function') player.play();
            return true;
          }} catch (err) {{
            return false;
          }}
        }}
        """,
        default=False,
        label='autoplay_with_videojs',
    )
    return bool(result)

def ensure_video_started(page, preferred_title: str | None = None) -> bool:
    for strategy in get_autoplay_strategy_order():
        if strategy == 'click-current':
            clicked = click_current_or_next_playable(page, preferred_title=preferred_title)
            if not clicked:
                continue
            time.sleep(1)
            snapshot = snapshot_player(page)
            if snapshot.exists and (not snapshot.paused or snapshot.current_time > 0):
                print('[fix] 已通过点击当前/下一可播放项启动视频')
                return True
        elif strategy == 'videojs-play' and autoplay_with_videojs(page):
            time.sleep(1)
            snapshot = snapshot_player(page)
            if snapshot.exists and (not snapshot.paused or snapshot.current_time > 0):
                print('[fix] 已通过 Video.js play() 启动视频')
                return True
        elif strategy == 'big-play-button':
            try:
                if page.locator(BIG_PLAY_SELECTOR).count() > 0:
                    page.locator(BIG_PLAY_SELECTOR).first.click(timeout=500)
                    time.sleep(1)
                    snapshot = snapshot_player(page)
                    if snapshot.exists and (not snapshot.paused or snapshot.current_time > 0):
                        print('[fix] 已通过大播放按钮启动视频')
                        return True
            except Exception:
                pass
    ensure_playing(page)
    snapshot = snapshot_player(page)
    return snapshot.exists and (not snapshot.paused or snapshot.current_time > 0)


def repair_with_videojs(page, safe_seek: float) -> bool:
    result = safe_page_evaluate(page,
        f"""
        (safeSeek) => {{
          const root = document.querySelector('{PLAYER_ROOT_SELECTOR}');
          const video = document.querySelector('{VIDEO_SELECTOR}');
          const before = video?.currentTime || 0;
          let player = null;
          if (root?.player) player = root.player;
          else if (window.videojs && root?.id) player = window.videojs(root.id);
          else if (window.videojs) {{
            const players = window.videojs.getPlayers ? window.videojs.getPlayers() : window.videojs.players;
            if (players) player = Object.values(players)[0] || null;
          }}
          if (!player) return {{ ok: false, reason: 'no-player', before, after: video?.currentTime || 0 }};
          try {{
            if (typeof player.currentTime === 'function') player.currentTime(safeSeek);
            if (typeof player.trigger === 'function') {{
              player.trigger('seeking');
              player.trigger('seeked');
              player.trigger('timeupdate');
            }}
            if (typeof player.play === 'function') player.play();
            const after = video?.currentTime || 0;
            return {{ ok: Math.abs(after - safeSeek) < 1.5, reason: 'videojs', before, after }};
          }} catch (err) {{
            return {{ ok: false, reason: String(err), before, after: video?.currentTime || 0 }};
          }}
        }}
        """,
        safe_seek,
        default={'ok': False, 'reason': 'navigation'},
        label='repair_with_videojs',
    )
    print(f'[debug] Video.js repair: {result}')
    return bool(result.get('ok'))


def repair_with_native_video(page, safe_seek: float) -> bool:
    result = safe_page_evaluate(page,
        f"""
        (safeSeek) => {{
          const video = document.querySelector('{VIDEO_SELECTOR}');
          if (!video) return {{ ok: false, reason: 'no-video' }};
          const before = video.currentTime || 0;
          try {{
            video.currentTime = safeSeek;
            for (const name of ['seeking', 'seeked', 'timeupdate', 'input', 'change']) {{
              video.dispatchEvent(new Event(name, {{ bubbles: true }}));
            }}
            video.play().catch(() => {{}});
            const after = video.currentTime || 0;
            return {{ ok: Math.abs(after - safeSeek) < 1.5, reason: 'native', before, after }};
          }} catch (err) {{
            return {{ ok: false, reason: String(err), before, after: video.currentTime || 0 }};
          }}
        }}
        """,
        safe_seek,
        default={'ok': False, 'reason': 'navigation'},
        label='repair_with_native_video',
    )
    print(f'[debug] Native repair: {result}')
    return bool(result.get('ok'))


def repair_with_progress_click(page, safe_seek: float) -> bool:
    result = safe_page_evaluate(page,
        f"""
        (safeSeek) => {{
          const video = document.querySelector('{VIDEO_SELECTOR}');
          const track = document.querySelector('{PROGRESS_SELECTOR}');
          const duration = video?.duration || 0;
          if (!video || !track || !duration) return {{ ok: false, reason: 'missing-track-or-video' }};
          const before = video.currentTime || 0;
          const rect = track.getBoundingClientRect();
          const ratio = Math.min(0.95, Math.max(0.01, safeSeek / duration));
          const x = rect.left + rect.width * ratio;
          const y = rect.top + rect.height / 2;
          for (const type of ['mousedown', 'mousemove', 'mouseup', 'click']) {{
            track.dispatchEvent(new MouseEvent(type, {{ bubbles: true, clientX: x, clientY: y }}));
          }}
          video.currentTime = safeSeek;
          video.dispatchEvent(new Event('timeupdate', {{ bubbles: true }}));
          video.play().catch(() => {{}});
          const after = video.currentTime || 0;
          return {{ ok: true, reason: 'progress', before, after, targetX: x }};
        }}
        """,
        safe_seek,
        default={'ok': False, 'reason': 'navigation'},
        label='repair_with_progress_click',
    )
    print(f'[debug] Progress repair: {result}')
    return bool(result.get('ok'))


def restore_from_false_end_jump(page, safe_seek: float, *, has_videojs: bool) -> bool:
    for strategy in get_repair_strategy_order(has_videojs=has_videojs):
        if strategy == 'videojs' and repair_with_videojs(page, safe_seek):
            print(f'[fix] 通过 Video.js API 拉回到 {safe_seek} 秒')
            return True
        if strategy == 'native' and repair_with_native_video(page, safe_seek):
            print(f'[fix] 通过原生 video.currentTime 拉回到 {safe_seek} 秒')
            return True
        if strategy == 'progress' and repair_with_progress_click(page, safe_seek):
            print(f'[fix] 通过进度条交互拉回到 {safe_seek} 秒')
            return True
    return False


def should_treat_as_real_finish(snapshot: PlayerSnapshot, watch_elapsed: float) -> bool:
    if snapshot.duration <= 0:
        return False
    near_end = snapshot.current_time >= snapshot.duration - 1 or snapshot.ended
    long_enough = watch_elapsed > max(15.0, snapshot.duration * 0.7)
    return near_end and long_enough


def collection_is_completed(page) -> bool:
    rows = collect_rows(page)
    if not rows:
        return False
    return all('开始观看' not in normalize_text(row.get('status', '')) and '正在播放' not in normalize_text(row.get('status', '')) for row in rows)


def play_detail_collection(page, safe_seek: float, poll_interval: float) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        dismiss_popups(page)
        ensure_video_tab(page)
        if is_detail_page(page):
            break
        time.sleep(0.5)

    ensure_video_tab(page)
    pending_title = None
    pending_started_at = 0.0
    ensure_video_started(page)
    last_key = None
    started_at = time.monotonic()
    last_fix_at = 0.0
    idle_rounds = 0
    idle_warned = False

    while True:
        dismiss_popups(page)
        snapshot = snapshot_player(page)
        rows = collect_rows(page)

        if snapshot.exists:
            if pending_title and normalize_text(snapshot.title) == normalize_text(pending_title):
                pending_title = None
                pending_started_at = 0.0

            if snapshot.key != last_key:
                last_key = snapshot.key
                started_at = time.monotonic()
                print(f'[info] 当前视频: {snapshot.title or "<unknown>"}')
                if should_skip_by_watched_duration(snapshot, rows):
                    print('[info] 当前视频所看时长已接近总时长，直接跳过到下一节')
                    clicked_title = click_next_video(page, require_current=True)
                    if clicked_title:
                        pending_title = clicked_title if clicked_title not in NEXT_TEXT_TOKENS else None
                        pending_started_at = time.monotonic() if pending_title else 0.0
                        time.sleep(3)
                        continue
                    print('[info] 当前集合内已无下一节可播放视频，视为集合完成')
                    return
                ensure_video_started(page, preferred_title=pending_title)

            watch_elapsed = time.monotonic() - started_at
            print(
                f'[state] current={snapshot.current_time:.1f}s duration={snapshot.duration:.1f}s '
                f'display={snapshot.current_display}/{snapshot.duration_display} '
                f'videojs={snapshot.has_videojs} class={snapshot.player_class}'
            )

            if is_false_end_jump(snapshot.duration, snapshot.current_time, watch_elapsed) and time.monotonic() - last_fix_at > 3:
                if restore_from_false_end_jump(page, safe_seek, has_videojs=snapshot.has_videojs):
                    last_fix_at = time.monotonic()
                    time.sleep(1.5)
                    continue

            if should_treat_as_real_finish(snapshot, watch_elapsed):
                clicked_title = click_next_video(page, require_current=True)
                if clicked_title:
                    pending_title = clicked_title if clicked_title not in NEXT_TEXT_TOKENS else None
                    pending_started_at = time.monotonic() if pending_title else 0.0
                    started_at = time.monotonic()
                    time.sleep(3)
                    continue
                print('[info] 当前集合内已无下一节可播放视频，视为集合完成')
                return

            if snapshot.paused and snapshot.current_time < max(2.0, safe_seek + 0.5):
                ensure_video_started(page, preferred_title=pending_title)
            else:
                ensure_playing(page)
            idle_rounds = 0
        else:
            if rows:
                preferred_title = None
                if pending_title and time.monotonic() - pending_started_at <= 8:
                    preferred_title = pending_title
                clicked_title = click_current_or_next_playable(page, preferred_title=preferred_title)
                if clicked_title:
                    if preferred_title:
                        pending_started_at = time.monotonic()
                    time.sleep(2)
                    continue
                if collection_is_completed(page):
                    print('[info] 当前集合列表已无可播放项，集合完成')
                    return
            idle_rounds += 1
            if idle_rounds >= 5:
                if not idle_warned:
                    print('[warn] 长时间未发现视频或可播放项，继续等待页面恢复或手动登录')
                    idle_warned = True
                dismiss_popups(page)
                ensure_video_tab(page)
                time.sleep(max(poll_interval, 3))
                continue

        time.sleep(poll_interval)


def dispatch_collections(page, safe_seek: float, poll_interval: float, parent_url: str) -> None:
    visited_hrefs: set[str] = set()

    while True:
        targets = [target for target in wait_for_collection_targets(page) if target.get('href') not in visited_hrefs]
        if not targets:
            print('[warn] 父页面未找到可播放集合')
            return

        target = targets[0]
        visited_hrefs.add(target.get('href', ''))
        print(f"[info] 进入集合 {len(visited_hrefs)}/{len(visited_hrefs) + len(targets) - 1}: {target['title']} -> {target['url']}")
        open_url(page, target['url'])
        play_detail_collection(page, safe_seek=safe_seek, poll_interval=poll_interval)
        print(f"[info] 集合播放结束: {target['title']}")
        open_url(page, parent_url)


def main() -> int:
    args = parse_args()
    sync_playwright, PlaywrightTimeoutError = load_playwright()
    profile_dir = str(Path(args.profile_dir).expanduser())

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=args.headless,
            viewport={'width': 1440, 'height': 960},
        )
        auth_loaded = apply_auth_state(context, profile_dir)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            open_url(page, args.url)
        except PlaywrightTimeoutError:
            print('[warn] 页面加载超时，继续尝试在当前页面工作')

        print('[info] 页面已打开。')
        if args.login_wait:
            wait_for_manual_ready(True)
            save_auth_state(context, page, profile_dir)

        try:
            dismiss_popups(page)
            parent_url = resolve_parent_url(args.url)
            if is_parent_page(page):
                print('[info] 检测到父页面，开始按最后一个到第一个集合顺序播放')
                dispatch_collections(page, safe_seek=args.safe_seek, poll_interval=args.poll_interval, parent_url=parent_url)
            else:
                print('[info] 检测到详情页，开始播放当前集合')
                play_detail_collection(page, safe_seek=args.safe_seek, poll_interval=args.poll_interval)
                print('[info] 当前集合完成，返回选择页继续调度')
                open_url(page, parent_url)
                dispatch_collections(page, safe_seek=args.safe_seek, poll_interval=args.poll_interval, parent_url=parent_url)
        except KeyboardInterrupt:
            print('\n[info] 用户中断，正在退出...')
        finally:
            try:
                save_auth_state(context, page, profile_dir)
            except Exception as exc:
                print(f'[warn] 保存登录态失败: {exc}')
            try:
                wait_before_close(args.headless)
            except KeyboardInterrupt:
                print('\n[info] 用户中断，正在关闭浏览器...')
            context.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
