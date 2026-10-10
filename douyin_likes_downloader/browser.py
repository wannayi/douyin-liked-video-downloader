"""使用 Playwright 处理登录态、点赞列表和视频播放地址。"""

from __future__ import annotations

import html
import logging
import math
import re
from dataclasses import dataclass
from typing import Any

from .config import AppConfig
from .models import VideoItem
from .utils import extract_video_id, is_media_url, normalize_url


class BrowserError(RuntimeError):
    """浏览器自动化失败。"""


class LoginRequired(BrowserError):
    """登录态缺失或已失效。"""


class CollectionError(BrowserError):
    """点赞列表未能可靠采集。"""


@dataclass(frozen=True)
class MediaSource:
    url: str
    content_type: str = ""
    expected_duration_seconds: float | None = None
    source_kind: str = "network"
    data_size: int = 0


def video_items_from_records(records: list[dict[str, Any]], base_url: str) -> list[VideoItem]:
    """将页面 DOM 记录规范化并去重。

    这个函数不依赖浏览器，既便于测试，也把抖音页面 DOM 变化的影响限制在
    `_read_video_records` 一处。
    """

    result: list[VideoItem] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        raw_url = record.get("url")
        if not isinstance(raw_url, str):
            continue
        url = normalize_url(raw_url, base_url)
        video_id = extract_video_id(url)
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        result.append(
            VideoItem(
                video_id=video_id,
                url=url,
                description=str(record.get("description") or "").strip(),
                author=str(record.get("author") or "").strip(),
            )
        )
    return result


class DouyinSession:
    """一个可复用的抖音浏览器会话。"""

    def __init__(self, config: AppConfig, logger: logging.Logger | None = None, *, headless: bool | None = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.headless = config.headless if headless is None else headless
        self._playwright = None
        self.context = None
        self.page = None
        self._user_agent = ""

    def __enter__(self) -> "DouyinSession":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserError(
                "未安装 Playwright。请先运行 python -m pip install -r requirements.txt，"
                "再运行 python -m playwright install chromium。"
            ) from exc

        self.config.ensure_directories()
        self._playwright = sync_playwright().start()
        try:
            self.context = self._launch_context()
        except Exception as exc:
            self._playwright.stop()
            self._playwright = None
            raise BrowserError(
                "启动浏览器失败。请确认已运行 python -m playwright install chromium，"
                f"或检查 browser_channel 配置：{exc}"
            ) from exc

        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_default_timeout(self.config.page_timeout_seconds * 1000)
        try:
            self._user_agent = self.page.evaluate("() => navigator.userAgent") or ""
        except Exception:
            self._user_agent = "Mozilla/5.0"
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            if self.context is not None:
                self._save_storage_state()
                self.context.close()
        finally:
            if self._playwright is not None:
                self._playwright.stop()
            self.context = None
            self.page = None
            self._playwright = None

    def _launch_context(self):
        assert self._playwright is not None
        kwargs = {
            "user_data_dir": str(self.config.browser_profile_dir),
            "headless": self.headless,
            "accept_downloads": True,
            "locale": "zh-CN",
            "viewport": {"width": 1440, "height": 960},
            # Playwright 默认会关闭 Chromium sandbox，Edge 会因此显示
            # “--no-sandbox” 安全提示；Windows Edge 支持启用 sandbox。
            "chromium_sandbox": True,
        }
        if self.config.browser_channel:
            try:
                return self._playwright.chromium.launch_persistent_context(
                    channel=self.config.browser_channel, **kwargs
                )
            except Exception as exc:
                self.logger.warning(
                    "无法启动浏览器 channel=%s，将尝试 Playwright Chromium：%s",
                    self.config.browser_channel,
                    exc,
                )
        return self._playwright.chromium.launch_persistent_context(**kwargs)

    def _save_storage_state(self) -> None:
        if self.context is None:
            return
        try:
            # 新版本 Playwright 可保存 IndexedDB；旧版本不接受该参数时回退。
            self.context.storage_state(path=str(self.config.storage_state_path), indexed_db=True)
        except TypeError:
            self.context.storage_state(path=str(self.config.storage_state_path))
        except Exception as exc:
            self.logger.warning("保存登录态快照失败（不影响浏览器 profile）：%s", exc)

    @property
    def user_agent(self) -> str:
        return self._user_agent or "Mozilla/5.0"

    def cookie_header(self) -> str:
        if self.context is None:
            return ""
        cookies = self.context.cookies()
        return "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in cookies)

    def login(self) -> None:
        """打开可见浏览器，用户手动完成登录后按回车保存登录态。"""

        if self.headless:
            raise BrowserError("登录命令必须使用可见浏览器；请在 CLI 中以 login 命令运行。")
        assert self.page is not None
        # 重新进入登录流程时，先取消旧的成功标记；只有本次验证通过才恢复。
        try:
            self.config.login_marker_path.unlink()
        except FileNotFoundError:
            pass
        self.logger.info("打开抖音登录页面：%s", self.config.likes_url)
        self.page.goto(
            self.config.likes_url,
            wait_until="commit",
            timeout=self.config.page_timeout_seconds * 1000,
        )
        self.page.wait_for_timeout(3000)
        print("浏览器窗口已打开，请等待页面显示后完成抖音登录（推荐扫码登录）。")
        input("确认已经登录并能看到账号内容后，只按一次 Enter：")
        try:
            self.page.goto(
                self.config.likes_url,
                wait_until="domcontentloaded",
                timeout=self.config.page_timeout_seconds * 1000,
            )
            self.page.wait_for_timeout(2000)
        except Exception as exc:
            raise LoginRequired("登录页面未能刷新，请确认浏览器中的登录操作已完成后重试。") from exc
        if not self._is_authenticated_page():
            raise LoginRequired(
                "当前页面仍未确认登录成功，登录态不会保存。请关闭窗口后重新运行一键启动。"
            )
        self._save_storage_state()
        self.config.login_marker_path.write_text("login verified\n", encoding="utf-8")
        self.logger.info("登录态已保存到 %s", self.config.browser_profile_dir)

    def collect_liked_videos(self) -> list[VideoItem]:
        """滚动点赞列表并收集所有视频链接。"""

        assert self.page is not None
        self._open_likes_page()
        collected: dict[str, VideoItem] = {}
        stable_rounds = 0
        previous_count = 0
        previous_height = 0
        empty_dom_retry_done = False

        for _round in range(self.config.max_scroll_rounds):
            records = self._read_video_records()
            # 抖音的点赞卡片由接口异步填充；首轮 DOM 可能只有空容器。
            # 空结果时稍等后重读，避免把加载时序误判为“没有点赞视频”。
            if not records and not collected and not empty_dom_retry_done:
                self.page.wait_for_timeout(2500)
                records = self._read_video_records()
                empty_dom_retry_done = True
            for item in video_items_from_records(records, self.config.likes_url):
                collected.setdefault(item.video_id, item)
                if self.config.max_items and len(collected) >= self.config.max_items:
                    break
            if self.config.max_items and len(collected) >= self.config.max_items:
                break

            height = self._page_height()
            at_bottom = self._scroll_to_bottom()
            if len(collected) == previous_count and height == previous_height and at_bottom:
                stable_rounds += 1
            else:
                stable_rounds = 0
            previous_count = len(collected)
            previous_height = height
            if stable_rounds >= 3:
                break

        if not collected:
            body_text = self._body_text()
            page_url = self.page.url.lower()
            if self._looks_like_login_page(body_text) or any(
                marker in page_url for marker in ("passport", "/login")
            ):
                raise LoginRequired("抖音登录态已失效，请重新运行 python app.py login")
            self.logger.warning("点赞列表中没有采集到视频链接；可能是账号没有点赞视频，或页面结构已变化。")

        self.logger.info("点赞列表采集完成：%d 个视频", len(collected))
        return list(collected.values())

    def _open_likes_page(self) -> None:
        assert self.page is not None
        try:
            self.page.goto(
                self.config.likes_url,
                wait_until="domcontentloaded",
                timeout=self.config.page_timeout_seconds * 1000,
            )
        except Exception as exc:
            raise CollectionError(f"打开点赞页面失败：{exc}") from exc
        self.page.wait_for_timeout(4000)

        # 只点击明确标记为 tab 的“喜欢”控件，避免误点普通点赞按钮。
        self._click_likes_tab()
        self.page.wait_for_timeout(2000)

    def _click_likes_tab(self) -> None:
        assert self.page is not None
        try:
            locator = self.page.locator('[role="tab"]')
            for index in range(locator.count() - 1, -1, -1):
                candidate = locator.nth(index)
                if not candidate.is_visible():
                    continue
                label = re.sub(r"\s+", "", candidate.inner_text(timeout=1000))
                if label != "喜欢" and not re.fullmatch(r"喜欢\d+", label):
                    continue
                classes = candidate.get_attribute("class") or ""
                is_selected = (
                    candidate.get_attribute("aria-selected") == "true"
                    or candidate.get_attribute("aria-current") == "page"
                    or candidate.get_attribute("data-state") == "active"
                    or re.search(r"(^|[\s_-])(active|selected)([\s_-]|$)", classes, re.IGNORECASE)
                )
                if not is_selected:
                    candidate.click(timeout=2500)
                    self.page.wait_for_timeout(1500)
                return
        except Exception as exc:
            self.logger.debug("点击喜欢标签失败：%s", exc)
        self.logger.debug("未找到明确标记的喜欢标签；采集时将要求页面列表范围可验证。")

    def _read_video_records(self) -> list[dict[str, Any]]:
        assert self.page is not None
        script = """
        () => {
          const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
          const labelOf = (element) => normalize(
            element.getAttribute('aria-label') || element.innerText || element.textContent
          );
          const isVisible = (element) => {
            const style = window.getComputedStyle(element);
            return element.getClientRects().length > 0 &&
              style.visibility !== 'hidden' && style.display !== 'none';
          };
          const roleTabs = Array.from(document.querySelectorAll('[role="tab"]'));
          const tabCandidates = roleTabs.length ? roleTabs : Array.from(
            document.querySelectorAll('[aria-selected], [aria-current], [data-state], [data-active]')
          );
          const likeTabs = tabCandidates.filter((element) => {
            const label = labelOf(element).replace(/\\s+/g, '');
            return isVisible(element) && label.startsWith('喜欢') && label.length <= 20;
          });
          const isSelected = (element) => {
            const state = (element.getAttribute('data-state') || '').toLowerCase();
            const active = (element.getAttribute('data-active') || '').toLowerCase();
            const classes = (typeof element.className === 'string' ? element.className : '').toLowerCase();
            return element.getAttribute('aria-selected') === 'true' ||
              ['page', 'true'].includes((element.getAttribute('aria-current') || '').toLowerCase()) ||
              element.getAttribute('aria-pressed') === 'true' ||
              state === 'active' || active === 'true' ||
              /(^|[\\s_-])(active|selected)([\\s_-]|$)/.test(classes);
          };
          const selectedLikeTabs = likeTabs.filter(isSelected);
          if (selectedLikeTabs.length !== 1) return { ok: false, records: [] };

          const tab = selectedLikeTabs[0];
          const panels = new Set();
          const controlledIds = (tab.getAttribute('aria-controls') || '')
            .split(/\\s+/).filter(Boolean);
          for (const id of controlledIds) {
            const panel = document.getElementById(id);
            if (panel) panels.add(panel);
          }
          if (tab.id) {
            for (const panel of document.querySelectorAll('[role="tabpanel"][aria-labelledby]')) {
              if ((panel.getAttribute('aria-labelledby') || '').split(/\\s+/).includes(tab.id)) {
                panels.add(panel);
              }
            }
          }
          const visiblePanels = Array.from(panels).filter(isVisible);
          if (visiblePanels.length !== 1) return { ok: false, records: [] };

          const recordFromNode = (candidate, scope) => {
            const values = [
              candidate.getAttribute && candidate.getAttribute('href'),
              candidate.getAttribute && candidate.getAttribute('data-id'),
              candidate.getAttribute && candidate.getAttribute('data-aweme-id'),
              candidate.getAttribute && candidate.getAttribute('data-awemeid'),
              candidate.getAttribute && candidate.getAttribute('data-video-id'),
              candidate.getAttribute && candidate.getAttribute('data-videoid'),
              candidate.getAttribute && candidate.getAttribute('data-e2e'),
              candidate.getAttribute && candidate.getAttribute('aria-label'),
              candidate.innerHTML,
            ].filter(Boolean).map(String);
            let href = candidate.href || candidate.getAttribute?.('href') || '';
            let match = values.map((value) => value.match(/(?:\\/video\\/|video[_-]?id["'=:/\\s]+|aweme[_-]?id["'=:/\\s]+)(\\d+)/i)).find(Boolean);
            if (!match) return null;
            if (!/\\/video\\/\\d+/i.test(href)) href = `https://www.douyin.com/video/${match[1]}`;

            let node = candidate;
            for (let i = 0; i < 6 && node.parentElement && node.parentElement !== scope; i += 1) {
              const parent = node.parentElement;
              const text = (parent.innerText || '').trim();
              if (text.length <= 600 && parent.querySelectorAll('a[href*="/video/"]').length <= 2) {
                node = parent;
              } else {
                break;
              }
            }
            const image = node.querySelector('img');
            const description = (candidate.getAttribute?.('aria-label') ||
              candidate.getAttribute?.('title') ||
              (image && (image.getAttribute('alt') || image.getAttribute('title'))) ||
              node.innerText || '').replace(/\\s+/g, ' ').trim();
            const authorNode = node.querySelector('a[href*="/user/"]');
            return {
              url: href,
              description: description.slice(0, 240),
              author: authorNode ? (authorNode.innerText || '').trim().slice(0, 80) : ''
            };
          };

          const recordsFromScope = (scope) => {
            if (!scope) return [];
            const candidates = Array.from(scope.querySelectorAll(
              'a[href], [data-id], [data-aweme-id], [data-awemeid], [data-video-id], [data-videoid], [data-e2e]'
            ));
            const records = candidates.map((candidate) => recordFromNode(candidate, scope)).filter(Boolean);
            // 某些版本把链接只放进序列化状态，而不渲染成 a[href]。
            // 仅在当前点赞容器内补读 /video/<id>，避免扫描整页推荐内容。
            const htmlMatches = String(scope.innerHTML || '').matchAll(/(?:\\/video\\/|\\\\\\/video\\\\\\/)(\\d+)/gi);
            for (const match of htmlMatches) {
              records.push({url: `https://www.douyin.com/video/${match[1]}`, description: '', author: ''});
            }
            const unique = new Map();
            for (const record of records) {
              if (record && record.url) unique.set(record.url, record);
            }
            return Array.from(unique.values());
          };

          const panel = visiblePanels[0];
          let records = recordsFromScope(panel);
          if (!records.length) {
            // 兼容新布局：tabpanel 只包含占位节点，实际卡片挂在喜欢标签的祖先容器。
            let container = tab.parentElement;
            for (let i = 0; i < 5 && container && !records.length; i += 1) {
              records = recordsFromScope(container);
              container = container.parentElement;
            }
          }
          return { ok: true, records };
        }
        """
        try:
            result = self.page.evaluate(script)
        except Exception as exc:
            raise CollectionError(f"读取点赞列表 DOM 失败：{exc}") from exc
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise CollectionError(
                "无法确认当前页面的视频区域属于“喜欢”列表，已停止采集以避免下载其他视频。"
            )
        records = result.get("records")
        return records if isinstance(records, list) else []

    def _page_height(self) -> int:
        assert self.page is not None
        try:
            value = self.page.evaluate("() => document.documentElement.scrollHeight")
            return int(value or 0)
        except Exception:
            return 0

    def _scroll_to_bottom(self) -> bool:
        assert self.page is not None
        try:
            self.page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
            self.page.wait_for_timeout(int(self.config.scroll_pause_seconds * 1000))
            return bool(
                self.page.evaluate(
                    "() => window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 8"
                )
            )
        except Exception:
            return False

    def _body_text(self) -> str:
        assert self.page is not None
        try:
            return self.page.locator("body").inner_text(timeout=3000)
        except Exception:
            return ""

    @staticmethod
    def _looks_like_login_page(text: str) -> bool:
        compact = re.sub(r"\s+", "", text)
        return "登录" in compact and any(marker in compact for marker in ("手机号", "扫码", "验证码"))

    def _is_authenticated_page(self) -> bool:
        """用 URL 和页面文本做轻量校验，避免空登录页被保存为有效登录态。"""

        assert self.page is not None
        page_url = self.page.url.lower()
        if any(marker in page_url for marker in ("passport", "/login")):
            return False
        body_text = self._body_text()
        if not body_text:
            return False
        return not self._looks_like_login_page(body_text)

    def find_media_source(self, item: VideoItem) -> MediaSource | None:
        """兼容单地址调用，返回优先级最高的候选。"""

        sources = self.find_media_sources(item)
        return sources[0] if sources else None

    def find_media_sources(self, item: VideoItem) -> list[MediaSource]:
        """提取详情 API、播放器和网络中的媒体候选，优先返回下载地址。"""

        assert self.page is not None
        candidates: list[MediaSource] = []

        def on_response(response) -> None:
            try:
                url = response.url
                content_type = response.headers.get("content-type", "")
                status = response.status
            except Exception:
                return
            if "json" in content_type.lower() and any(
                marker in url.lower() for marker in ("aweme", "detail")
            ):
                try:
                    candidates.extend(_media_sources_from_payload(response.json(), item.video_id))
                except Exception:
                    pass
                return
            try:
                request_headers = response.request.headers
                has_range = any(key.lower() == "range" for key in request_headers)
                has_content_range = bool(response.headers.get("content-range"))
            except Exception:
                has_range = False
                has_content_range = False
            if status == 206 or has_range or has_content_range:
                return
            if is_media_url(url) or content_type.lower().startswith("video/") or "mpegurl" in content_type.lower():
                candidates.append(
                    MediaSource(url=url, content_type=content_type, source_kind="network")
                )

        self.page.on("response", on_response)
        try:
            last_navigation_error = None
            for attempt in range(2):
                try:
                    self.page.goto(
                        item.url,
                        wait_until="domcontentloaded",
                        timeout=self.config.page_timeout_seconds * 1000,
                    )
                    last_navigation_error = None
                    break
                except Exception as exc:
                    last_navigation_error = exc
                    if attempt == 0:
                        self.page.wait_for_timeout(1000)
            if last_navigation_error is not None:
                raise last_navigation_error
            self.page.wait_for_timeout(int(self.config.detail_wait_seconds * 1000))

            video_records = self.page.locator("video").evaluate_all(
                """nodes => nodes.flatMap(node => {
                  const duration = Number.isFinite(node.duration) && node.duration > 0
                    ? node.duration : null;
                  return [node.currentSrc, node.src,
                    ...Array.from(node.querySelectorAll('source')).map(source => source.src)]
                    .filter(Boolean).map(url => ({url, duration}));
                })"""
            )
            for record in video_records if isinstance(video_records, list) else []:
                if not isinstance(record, dict):
                    continue
                url = record.get("url")
                duration = record.get("duration")
                if isinstance(url, str) and not url.startswith("blob:"):
                    candidates.append(
                        MediaSource(
                            url=url,
                            content_type="video/mp4",
                            expected_duration_seconds=(
                                float(duration) if isinstance(duration, (int, float)) else None
                            ),
                            source_kind="player",
                        )
                    )

            resource_urls = self.page.evaluate(
                """() => performance.getEntriesByType('resource').map(entry => entry.name)"""
            )
            for url in resource_urls if isinstance(resource_urls, list) else []:
                if isinstance(url, str) and is_media_url(url):
                    candidates.append(MediaSource(url=url, source_kind="performance"))

            # 部分页面把播放地址放在 SSR JSON 中，作为最后的兼容回退。
            for url in _media_urls_from_html(self.page.content()):
                candidates.append(MediaSource(url=url, source_kind="html"))
        except Exception as exc:
            self.logger.warning("读取视频 %s 的播放地址失败：%s", item.video_id, exc)
        finally:
            try:
                self.page.remove_listener("response", on_response)
            except Exception:
                pass

        return _select_media_sources(candidates)


def _media_urls_from_html(content: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"https?://[^\"'<>\s]+", content or ""):
        url = html.unescape(raw)
        url = url.replace("\\u002F", "/").replace("\\u0026", "&").replace("\\/", "/")
        url = url.rstrip("\\.,;)")
        if is_media_url(url) and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _media_sources_from_payload(payload: Any, video_id: str) -> list[MediaSource]:
    """从匹配当前视频 ID 的抖音详情 JSON 中提取 download_addr/play_addr。"""

    records: list[dict[str, Any]] = []
    pending = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            record_id = str(value.get("aweme_id") or value.get("awemeId") or "")
            if record_id == video_id and isinstance(value.get("video"), dict):
                records.append(value)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)

    candidates: list[MediaSource] = []
    for record in records:
        video = record.get("video")
        if not isinstance(video, dict):
            continue
        try:
            duration_ms = float(video.get("duration"))
            expected_duration = (
                duration_ms / 1000
                if math.isfinite(duration_ms) and duration_ms > 0
                else None
            )
        except (TypeError, ValueError):
            expected_duration = None
        for field_name, source_kind in (
            ("download_addr", "download"),
            ("play_addr", "play"),
            ("play_addr_265", "play"),
            ("play_addr_h264", "play"),
        ):
            address = video.get(field_name)
            if not isinstance(address, dict):
                continue
            raw_urls = address.get("url_list")
            if not isinstance(raw_urls, list):
                raw_urls = [address.get("url")]
            try:
                data_size = int(address.get("data_size") or 0)
            except (TypeError, ValueError):
                data_size = 0
            for url in raw_urls:
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    candidates.append(
                        MediaSource(
                            url=url,
                            content_type="video/mp4",
                            expected_duration_seconds=expected_duration,
                            source_kind=source_kind,
                            data_size=data_size,
                        )
                    )
    return candidates


def _media_source_score(candidate: MediaSource) -> int:
    lowered = candidate.url.lower()
    content_type = candidate.content_type.lower()
    score = {
        "download": 40,
        "play": 30,
        "player": 20,
        "network": 5,
        "performance": 2,
        "html": 1,
    }.get(candidate.source_kind, 0)
    if content_type.startswith("video/"):
        score += 8
    if "mpegurl" in content_type or ".m3u8" in lowered:
        score += 6
    if ".mp4" in lowered:
        score += 5
    if "download" in lowered:
        score += 2
    if candidate.expected_duration_seconds is not None:
        score += 4
    if candidate.data_size > 0:
        score += 2
    if "playwm" in lowered:
        score -= 2
    if any(marker in lowered for marker in ("avatar", "head", "cover")):
        score -= 8
    return score


def _select_media_sources(candidates: list[MediaSource]) -> list[MediaSource]:
    """按来源可信度排序，并合并同一 URL 的重复候选。"""

    unique: dict[str, MediaSource] = {}
    for candidate in candidates:
        url = candidate.url
        if url.startswith("blob:") or not url.startswith(("http://", "https://")):
            continue
        previous = unique.get(url)
        if previous is None or _media_source_score(candidate) > _media_source_score(previous):
            unique[url] = candidate
    return sorted(unique.values(), key=_media_source_score, reverse=True)


def _select_media_source(candidates: list[MediaSource]) -> MediaSource | None:
    """兼容旧调用的单候选选择器。"""

    sources = _select_media_sources(candidates)
    return sources[0] if sources else None
