import unittest
from unittest.mock import patch

import main
from logic import (
    build_storage_restore_script,
    choose_next_item_after_current,
    choose_next_item_label,
    filter_playable_collections,
    get_auth_state_path,
    get_autoplay_strategy_order,
    get_collection_script_template,
    get_collection_visit_order,
    get_repair_strategy_order,
    get_video_tab_labels,
    is_false_end_jump,
    is_navigation_context_error,
    normalize_text,
)


class LogicTests(unittest.TestCase):
    def test_resolve_active_video_title_prefers_pending_title_during_switch_window(self):
        snapshot = main.PlayerSnapshot(
            exists=True,
            current_time=1.5,
            duration=230.0,
            paused=False,
            title='2.退役士兵安置地规定',
        )

        title = main.resolve_active_video_title(
            snapshot,
            pending_title='7.自主就业退役士兵一次性退役金发放',
            pending_started_at=100.0,
            now=103.0,
        )

        self.assertEqual(title, '7.自主就业退役士兵一次性退役金发放')

    def test_should_skip_by_watched_duration_uses_override_title(self):
        rows = [
            {'title': '2.退役士兵安置地规定', 'status': '开始观看', 'raw': '2.退役士兵安置地规定 所看时长: 03:45'},
            {'title': '7.自主就业退役士兵一次性退役金发放', 'status': '开始观看', 'raw': '7.自主就业退役士兵一次性退役金发放 所看时长: 00:10'},
        ]
        snapshot = main.PlayerSnapshot(
            exists=True,
            duration=230.0,
            current_time=1.5,
            paused=False,
            title='2.退役士兵安置地规定',
        )

        self.assertFalse(
            main.should_skip_by_watched_duration(
                snapshot,
                rows,
                target_title='7.自主就业退役士兵一次性退役金发放',
                tolerance_seconds=5.0,
            )
        )

    def test_wait_for_collection_targets_scrolls_until_count_stabilizes(self):
        page = object()
        target_rounds = iter([
            [],
            [{'title': '集合1', 'url': 'https://example.com/1', 'href': '#1', 'status': '未开始'}] * 5,
            [{'title': '集合1', 'url': 'https://example.com/1', 'href': '#1', 'status': '未开始'}] * 8,
            [{'title': '集合1', 'url': 'https://example.com/1', 'href': '#1', 'status': '未开始'}] * 8,
            [{'title': '集合1', 'url': 'https://example.com/1', 'href': '#1', 'status': '未开始'}] * 8,
        ])
        scroll_calls = []
        sleep_calls = []

        with patch.object(main, 'get_collection_targets', lambda current_page: next(target_rounds, [])), \
             patch.object(main, 'scroll_parent_collection_list', lambda current_page: scroll_calls.append('scroll')), \
             patch.object(main.time, 'sleep', lambda seconds: sleep_calls.append(seconds)), \
             patch.object(main.time, 'monotonic', side_effect=range(100, 120)):
            targets = main.wait_for_collection_targets(page, timeout_seconds=15.0, poll_interval=0.5)

        self.assertEqual(len(targets), 8)
        self.assertGreaterEqual(len(scroll_calls), 2)
        self.assertGreaterEqual(len(sleep_calls), 2)

    def test_wait_for_collection_targets_retries_until_targets_appear(self):
        page = object()
        target_rounds = iter([
            [],
            [{'title': '集合A', 'url': 'https://example.com/a', 'href': '#a', 'status': '未开始'}],
            [{'title': '集合A', 'url': 'https://example.com/a', 'href': '#a', 'status': '未开始'}],
            [{'title': '集合A', 'url': 'https://example.com/a', 'href': '#a', 'status': '未开始'}],
        ])
        sleep_calls = []

        with patch.object(main, 'get_collection_targets', lambda current_page: next(target_rounds, [])), \
             patch.object(main, 'scroll_parent_collection_list', lambda current_page: None), \
             patch.object(main.time, 'sleep', lambda seconds: sleep_calls.append(seconds)), \
             patch.object(main.time, 'monotonic', side_effect=range(100, 110)):
            targets = main.wait_for_collection_targets(page, timeout_seconds=5.0, poll_interval=0.5)

        self.assertEqual(len(targets), 1)
        self.assertGreaterEqual(len(sleep_calls), 2)

    def test_ensure_video_tab_clicks_video_when_detail_tab_active(self):
        clicked_labels = []

        class DummyCountLocator:
            def __init__(self, count_value=0, text_value=''):
                self._count_value = count_value
                self._text_value = text_value
                self.first = self

            def count(self):
                return self._count_value

            def inner_text(self, timeout=None):
                return self._text_value

            def click(self, timeout=None):
                clicked_labels.append(self._text_value or '视频')

        class DummyPage:
            def __init__(self):
                self.after_click = False

            def locator(self, selector):
                if selector in (main.ITEM_SELECTOR, main.VIDEO_TAB_CONTENT_SELECTOR):
                    return DummyCountLocator(1 if self.after_click else 0)
                if selector == '.van-tab--active':
                    return DummyCountLocator(1, '详情')
                return DummyCountLocator(0)

            def get_by_text(self, text, exact=False):
                if text == '视频':
                    page = self

                    class VideoLocator(DummyCountLocator):
                        def __init__(self):
                            super().__init__(1, '视频')

                        def click(self, timeout=None):
                            page.after_click = True
                            clicked_labels.append('视频')

                    return VideoLocator()
                return DummyCountLocator(0)

            def wait_for_timeout(self, ms):
                return None

        page = DummyPage()

        self.assertTrue(main.ensure_video_tab(page))
        self.assertEqual(clicked_labels, ['视频'])

    def test_play_detail_collection_attempts_video_tab_before_detail_page_detected(self):
        calls = []

        def fake_sleep(seconds):
            raise RuntimeError('stop loop')

        with patch.object(main, 'dismiss_popups', lambda page: None), \
             patch.object(main, 'is_detail_page', lambda page: False), \
             patch.object(main, 'ensure_video_tab', lambda page: calls.append('ensure_video_tab') or False), \
             patch.object(main.time, 'sleep', fake_sleep), \
             patch.object(main.time, 'monotonic', side_effect=[0, 1]):
            with self.assertRaisesRegex(RuntimeError, 'stop loop'):
                main.play_detail_collection(object(), safe_seek=2.0, poll_interval=0.1)

        self.assertIn('ensure_video_tab', calls)

    def test_wait_before_close_prompts_in_non_headless_mode(self):
        prompts = []

        main.wait_before_close(headless=False, prompt=prompts.append)

        self.assertEqual(len(prompts), 1)
        self.assertIn('按回车关闭浏览器', prompts[0])

    def test_click_next_video_after_current_returns_none_without_current_item(self):
        rows = [
            {'title': '1-第一节', 'status': '开始观看'},
            {'title': '2-第二节', 'status': '开始观看'},
        ]

        with patch.object(main, 'collect_rows', lambda page: rows), \
             patch.object(main, 'click_row_by_title', lambda page, title: True):
            title = main.click_next_video(page=object(), require_current=True)

        self.assertIsNone(title)

    def test_resolve_parent_url_maps_online_train_to_online_train_list(self):
        self.assertEqual(
            main.resolve_parent_url('https://zxsp.tyjr.sh.gov.cn/#/onlineTrain'),
            'https://peixun.tyjr.sh.gov.cn/azqPhoneService/#/onlineTrainList',
        )

    def test_resolve_parent_url_maps_train_detail_to_online_train_list(self):
        self.assertEqual(
            main.resolve_parent_url('https://peixun.tyjr.sh.gov.cn/azqPhoneService/#/trainDetail?id=1&relationId=2'),
            'https://peixun.tyjr.sh.gov.cn/azqPhoneService/#/onlineTrainList',
        )

    def test_should_skip_by_watched_duration_when_near_video_end(self):
        rows = [
            {
                'title': '5-目标视频',
                'status': '开始观看',
                'raw': '5-目标视频 所看时长: 02:33',
            }
        ]
        snapshot = main.PlayerSnapshot(
            exists=True,
            duration=156.0,
            current_time=0.0,
            paused=False,
            title='5-目标视频',
        )

        self.assertTrue(main.should_skip_by_watched_duration(snapshot, rows, tolerance_seconds=5.0))

    def test_should_not_skip_by_watched_duration_when_gap_is_large(self):
        rows = [
            {
                'title': '5-目标视频',
                'status': '开始观看',
                'raw': '5-目标视频 所看时长: 01:20',
            }
        ]
        snapshot = main.PlayerSnapshot(
            exists=True,
            duration=156.0,
            current_time=0.0,
            paused=False,
            title='5-目标视频',
        )

        self.assertFalse(main.should_skip_by_watched_duration(snapshot, rows, tolerance_seconds=5.0))

    def test_dispatch_collections_reloads_parent_page_between_collections(self):
        page = object()
        opened_urls = []
        played_titles = []
        target_rounds = iter([
            [
                {'title': '集合A', 'url': 'https://example.com/a', 'href': '#a', 'status': '未开始'},
                {'title': '集合B', 'url': 'https://example.com/b', 'href': '#b', 'status': '未开始'},
            ],
            [
                {'title': '集合B', 'url': 'https://example.com/b', 'href': '#b', 'status': '未开始'},
            ],
            [],
        ])

        with patch.object(main, 'wait_for_collection_targets', lambda current_page: next(target_rounds, [])), \
             patch.object(main, 'open_url', lambda current_page, url: opened_urls.append(url)), \
             patch.object(main, 'play_detail_collection', lambda current_page, safe_seek, poll_interval: played_titles.append(opened_urls[-1])):
            main.dispatch_collections(page, safe_seek=2.0, poll_interval=1.0, parent_url='https://example.com/#/onlineTrain')

        self.assertEqual(
            opened_urls,
            [
                'https://example.com/a',
                'https://example.com/#/onlineTrain',
                'https://example.com/b',
                'https://example.com/#/onlineTrain',
            ],
        )
        self.assertEqual(played_titles, ['https://example.com/a', 'https://example.com/b'])

    def test_ensure_video_started_prefers_pending_title_over_generic_next(self):
        clicked_titles = []
        snapshots = iter([
            main.PlayerSnapshot(exists=False),
            main.PlayerSnapshot(exists=True, current_time=1.2, paused=False, title='5-目标视频'),
        ])
        rows = [
            {'title': '4-当前视频', 'status': '已完成'},
            {'title': '5-目标视频', 'status': '开始观看'},
            {'title': '6-被错误跳过的视频', 'status': '开始观看'},
        ]

        with patch.object(main, 'click_row_by_title', lambda page, title: clicked_titles.append(title) or True), \
             patch.object(main, 'collect_rows', lambda page: rows), \
             patch.object(main, 'autoplay_with_videojs', lambda page: False), \
             patch.object(main, 'ensure_playing', lambda page: None), \
             patch.object(main, 'snapshot_player', lambda page: next(snapshots)), \
             patch.object(main.time, 'sleep', lambda seconds: None):
            started = main.ensure_video_started(object(), preferred_title='5-目标视频')

        self.assertTrue(started)
        self.assertEqual(clicked_titles, ['5-目标视频'])

    def test_click_next_video_returns_clicked_title(self):
        rows = [
            {'title': '4-当前视频', 'status': '正在播放'},
            {'title': '5-目标视频', 'status': '开始观看'},
            {'title': '6-下一个视频', 'status': '开始观看'},
        ]

        with patch.object(main, 'collect_rows', lambda page: rows), \
             patch.object(main, 'click_row_by_title', lambda page, title: title == '5-目标视频'):
            title = main.click_next_video(object())

        self.assertEqual(title, '5-目标视频')

    def test_wait_for_manual_ready_prompts_when_login_wait_enabled(self):
        prompts = []

        main.wait_for_manual_ready(True, prompt=prompts.append)

        self.assertEqual(len(prompts), 1)
        self.assertIn('按回车继续', prompts[0])

    def test_play_detail_collection_keeps_waiting_when_no_video_info(self):
        sleep_calls = []

        def fake_sleep(seconds):
            sleep_calls.append(seconds)
            if len(sleep_calls) >= 8:
                raise RuntimeError('stop loop')

        monotonic_values = iter(range(100, 200))

        with patch.object(main, 'dismiss_popups', lambda page: None), \
             patch.object(main, 'is_detail_page', lambda page: True), \
             patch.object(main, 'ensure_video_tab', lambda page: True), \
             patch.object(main, 'ensure_video_started', lambda page: False), \
             patch.object(main, 'snapshot_player', lambda page: main.PlayerSnapshot(exists=False)), \
             patch.object(main, 'collect_rows', lambda page: []), \
             patch.object(main.time, 'sleep', fake_sleep), \
             patch.object(main.time, 'monotonic', lambda: next(monotonic_values)):
            with self.assertRaisesRegex(RuntimeError, 'stop loop'):
                main.play_detail_collection(object(), safe_seek=2.0, poll_interval=0.1)

        self.assertGreaterEqual(len(sleep_calls), 8)

    def test_open_url_handles_hash_route_response_failure_with_base_fallback(self):
        class DummyPage:
            def __init__(self):
                self.goto_calls = []
                self.wait_calls = []
                self.evaluate_calls = []
                self.url = 'about:blank'

            def goto(self, url, wait_until=None, timeout=None):
                self.goto_calls.append((url, wait_until, timeout))
                if len(self.goto_calls) <= 2:
                    raise Exception(
                        f'Page.goto: net::ERR_HTTP_RESPONSE_CODE_FAILURE at {url}'
                    )
                self.url = url

            def wait_for_load_state(self, state=None, timeout=None):
                self.wait_calls.append((state, timeout))

            def evaluate(self, expression, arg=None):
                self.evaluate_calls.append((expression, arg))
                if arg:
                    self.url = arg

        page = DummyPage()

        main.open_url(page, 'https://zxsp.tyjr.sh.gov.cn/#/onlineTrain')

        self.assertEqual(
            page.goto_calls[:2],
            [
                ('https://zxsp.tyjr.sh.gov.cn/#/onlineTrain', 'domcontentloaded', 60_000),
                ('https://zxsp.tyjr.sh.gov.cn/', 'domcontentloaded', 60_000),
            ],
        )
        self.assertEqual(
            page.wait_calls,
            [('domcontentloaded', 60_000), ('domcontentloaded', 60_000)],
        )
        self.assertEqual(page.evaluate_calls[-1][1], 'https://zxsp.tyjr.sh.gov.cn/#/onlineTrain')

    def test_install_storage_restore_injects_init_script(self):
        class DummyContext:
            def __init__(self):
                self.script = None

            def add_init_script(self, script):
                self.script = script

        context = DummyContext()
        auth_state = {
            'origins': [
                {
                    'origin': 'https://example.com',
                    'localStorage': [{'name': 'x-token', 'value': 'abc'}],
                    'sessionStorage': [],
                }
            ]
        }

        main.install_storage_restore(context, auth_state)
        self.assertIsNotNone(context.script)
        self.assertIn('window.localStorage.setItem', context.script)

    def test_false_end_jump_detected_when_video_near_end_too_early(self):
        self.assertTrue(is_false_end_jump(duration=1200, current_time=1199, watch_elapsed=3))

    def test_false_end_jump_not_detected_for_real_finish(self):
        self.assertFalse(is_false_end_jump(duration=1200, current_time=1199, watch_elapsed=1180))

    def test_normalize_text_collapses_whitespace(self):
        self.assertEqual(normalize_text(' 正在\n播放  '), '正在播放')

    def test_choose_next_item_prefers_start_watch_status(self):
        rows = [
            {'title': '1-军人退役面临的转换与变化', 'status': '已完成'},
            {'title': '2-常见心理问题分析-茫然和焦虑心理', 'status': '开始观看'},
            {'title': '3-常见心理问题分析-自卑心理', 'status': '未学习'},
        ]
        self.assertEqual(choose_next_item_label(rows), '2-常见心理问题分析-茫然和焦虑心理')

    def test_choose_next_item_after_current_prefers_following_start_watch_item(self):
        rows = [
            {'title': '1-军人退役面临的转换与变化', 'status': '开始观看'},
            {'title': '2-常见心理问题分析-茫然和焦虑心理', 'status': '正在播放'},
            {'title': '3-常见心理问题分析-自卑心理', 'status': '开始观看'},
            {'title': '4-常见心理问题分析-失落心理', 'status': '开始观看'},
        ]
        self.assertEqual(choose_next_item_after_current(rows), '3-常见心理问题分析-自卑心理')

    def test_choose_next_item_after_current_returns_none_when_no_current_item(self):
        rows = [
            {'title': '1-军人退役面临的转换与变化', 'status': '开始观看'},
            {'title': '2-常见心理问题分析-茫然和焦虑心理', 'status': '开始观看'},
        ]
        self.assertIsNone(choose_next_item_after_current(rows))

    def test_repair_strategy_prefers_videojs_then_native_then_progress(self):
        self.assertEqual(get_repair_strategy_order(has_videojs=True), ['videojs', 'native', 'progress'])

    def test_repair_strategy_without_videojs_skips_player_api(self):
        self.assertEqual(get_repair_strategy_order(has_videojs=False), ['native', 'progress'])

    def test_reverse_collection_order_returns_last_to_first(self):
        rows = [
            {'title': 'A', 'href': '#/trainDetail?id=1', 'status': '未开始'},
            {'title': 'B', 'href': '#/trainDetail?id=2', 'status': '未开始'},
        ]
        self.assertEqual(get_collection_visit_order(rows), ['#/trainDetail?id=2', '#/trainDetail?id=1'])

    def test_pick_unfinished_collection_rows_filters_finished_items(self):
        rows = [
            {'title': 'A', 'href': '#/trainDetail?id=1', 'status': '未开始'},
            {'title': 'B', 'href': '#/trainDetail?id=2', 'status': '已完成'},
        ]
        self.assertEqual(filter_playable_collections(rows), ['#/trainDetail?id=1'])

    def test_autoplay_strategy_order_prefers_click_then_videojs_then_big_button(self):
        self.assertEqual(get_autoplay_strategy_order(), ['click-current', 'videojs-play', 'big-play-button'])

    def test_navigation_context_error_matches_execution_context_destroyed(self):
        self.assertTrue(is_navigation_context_error('Page.evaluate: Execution context was destroyed, most likely because of a navigation.'))

    def test_navigation_context_error_ignores_other_errors(self):
        self.assertFalse(is_navigation_context_error('Page.evaluate: SyntaxError: Unexpected token'))

    def test_collection_script_template_keeps_js_object_braces(self):
        script = get_collection_script_template('.onlineTrain_li', '.title', '.btn a', '.btn div')
        self.assertIn('map((node, index) => ({', script)
        self.assertIn('})).filter(row => row.href)', script)

    def test_auth_state_path_is_inside_profile_dir(self):
        path = get_auth_state_path('/tmp/browser-profile')
        self.assertEqual(path, '/tmp/browser-profile/auth_state.json')

    def test_video_tab_labels_prefers_video_first(self):
        self.assertEqual(get_video_tab_labels()[0], '视频')

    def test_build_storage_restore_script_embeds_local_storage_keys(self):
        script = build_storage_restore_script([
            {
                'origin': 'https://example.com',
                'localStorage': [{'name': 'x-token', 'value': 'abc'}],
                'sessionStorage': []
            }
        ])
        self.assertIn('x-token', script)
        self.assertIn('window.localStorage.setItem', script)


if __name__ == '__main__':
    unittest.main()
