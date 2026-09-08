import atexit
import json
import mimetypes
import os
import threading
import time
from pathlib import Path

import websocket  # websocket-client

import flet as ft

# Windows 注册表可能把 .js/.mjs 映射为 text/plain；浏览器会拒绝用 ES module
# 动态 import 加载 text/plain 的 canvaskit.js，导致 Web 端永远卡在启动画面。
# 本地 ft.run 内置 web 服务器用 Python mimetypes 推断 Content-Type，这里强制纠正。
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")

# 默认服务地址（可在界面修改，保存后持久化）
DEFAULT_URL = "ws://192.168.2.101:12347/ws"

# 协议模板：{topic}/{message} 占位符，适配任意服务端协议（MQTT/STOMP/自定义）
DEFAULT_TEMPLATES = {
    "subscribe": '{"action":"subscribe","topic":"{topic}"}',
    "unsubscribe": '{"action":"unsubscribe","topic":"{topic}"}',
    "publish": '{"action":"publish","topic":"{topic}","message":"{message}"}',
}

# 消息缓存上限与看门狗参数
MAX_MESSAGES = 500
CONNECT_TIMEOUT_SEC = 12
RECONNECT_MIN_SEC = 2
RECONNECT_MAX_SEC = 30

# 每次点击循环切换的页面背景色
BG_COLORS = [
    ft.Colors.BLUE_100,
    ft.Colors.GREEN_100,
    ft.Colors.AMBER_100,
    ft.Colors.PURPLE_100,
    ft.Colors.PINK_100,
]


# ---------------- 配置持久化（config.json） ----------------

def config_path() -> Path:
    """优先使用 flet 移动端数据目录，其次用户主目录，最后当前目录。"""
    for var in ("FLET_APP_STORAGE_DATA", "FLET_APP_TEMP"):
        p = os.environ.get(var)
        if p:
            return Path(p) / "config.json"
    try:
        return Path.home() / ".flet_ws_demo" / "config.json"
    except Exception:
        return Path.cwd() / "config.json"


def load_config() -> dict:
    cfg = {
        "url": DEFAULT_URL,
        "topics": ["demo"],
        "templates": dict(DEFAULT_TEMPLATES),
        "auto_subscribe": True,
        "auto_reconnect": True,
    }
    try:
        p = config_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            for k in ("url", "topics", "templates", "auto_subscribe", "auto_reconnect"):
                if k in data:
                    cfg[k] = data[k]
            for k, v in DEFAULT_TEMPLATES.items():
                cfg["templates"].setdefault(k, v)
    except Exception:
        pass
    return cfg


def render_frame(tpl: str, topic: str, message: str = None) -> str:
    """用简单替换渲染模板，避免 str.format 与 JSON 花括号冲突。"""
    s = tpl.replace("{topic}", topic)
    if message is not None:
        s = s.replace("{message}", message)
    return s


def to_ws_url(url: str) -> str:
    """把用户输入的地址规范化为 ws:// 或 wss:// 形式。"""
    url = (url or "").strip()
    if url.startswith("https://"):
        url = "wss://" + url[len("https://"):]
    elif url.startswith("http://"):
        url = "ws://" + url[len("http://"):]
    elif not url.startswith(("ws://", "wss://")):
        url = "wss://" + url
    return url


def now_str() -> str:
    return time.strftime("%H:%M:%S")


def main(page: ft.Page):
    cfg = load_config()
    cfg_lock = threading.Lock()

    page.title = "Flet WebSocket 订阅/发布 调试工具"
    page.padding = 24
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.bgcolor = BG_COLORS[0]
    page.scroll = ft.ScrollMode.AUTO

    # ---------- 计数 & 换色 ----------
    count = 0
    count_text = ft.Text("0", size=54, weight=ft.FontWeight.BOLD)

    def on_click(e):
        nonlocal count
        count += 1
        count_text.value = str(count)
        page.bgcolor = BG_COLORS[count % len(BG_COLORS)]
        page.update()

    counter_section = ft.Column(
        [
            ft.Text("点击按钮：计数 +1，同时切换页面背景色", size=13, color=ft.Colors.BLACK),
            count_text,
            ft.Button("点击我 +1", on_click=on_click),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=10,
    )

    # ---------------- WebSocket 调试区 ----------------

    # ---- 连接状态 ----
    state = {
        "ws": None,              # WebSocketApp 实例
        "url": "",               # 当前连接的地址
        "user_close": False,     # 是否用户主动断开
        "pending_open": False,   # 是否正在等待 on_open（看门狗用）
        "watchdog": None,        # 连接超时看门狗 Timer
        "reconnect_delay": RECONNECT_MIN_SEC,
        "reconnect_timer": None,
    }
    subscribed = set()           # 客户端认为已订阅的主题

    url_field = ft.TextField(value=cfg["url"], width=380, label="服务地址", text_size=13)
    conn_status = ft.Text("未连接", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK)
    auto_reconnect_sw = ft.Switch(label="自动重连", value=cfg["auto_reconnect"], scale=0.85)
    auto_subscribe_sw = ft.Switch(label="连接后自动重订所有主题", value=cfg["auto_subscribe"], scale=0.85)

    # ---- 消息缓存与过滤 ----
    msg_cache = []          # [{"time","topic","line","color"}]
    current_filter = ""     # ""=全部

    msg_list = ft.ListView(height=300, spacing=5, auto_scroll=True, padding=10)
    msg_panel = ft.Container(
        content=msg_list,
        width=420,
        border=ft.Border.all(1, ft.Colors.GREY_400),
        border_radius=8,
        bgcolor=ft.Colors.with_opacity(0.5, ft.Colors.WHITE),
    )
    filter_dd = ft.Dropdown(
        label="按主题过滤消息",
        width=200,
        text_size=13,
        options=[ft.dropdown.Option("全部")],
        value="全部",
        on_select=lambda e: apply_filter(e.control.value),
    )

    def apply_filter(value):
        nonlocal current_filter
        current_filter = "" if value in (None, "", "全部") else value
        render_messages()

    def refresh_filter_options():
        nonlocal current_filter
        topics = sorted({m["topic"] for m in msg_cache if m.get("topic")} | set(cfg["topics"]))
        filter_dd.options = [ft.dropdown.Option("全部")] + [ft.dropdown.Option(t) for t in topics]
        if current_filter and current_filter not in topics:
            current_filter = ""
            filter_dd.value = "全部"

    def render_messages():
        msg_list.controls = [
            ft.Text(
                '[%s] %s' % (m["time"], m["line"]),
                size=12.5,
                selectable=True,
                color=m["color"],
            )
            for m in msg_cache
            if current_filter == "" or m.get("topic") == current_filter
        ]
        page.update()

    def append_msg(line: str, color=None, topic=None):
        """追加消息（ws 线程安全），仅当通过过滤器时刷新到界面。"""
        msg_cache.append({"time": now_str(), "topic": topic, "line": line, "color": color})
        if len(msg_cache) > MAX_MESSAGES:
            del msg_cache[: len(msg_cache) - MAX_MESSAGES]
        refresh_filter_options()
        if current_filter == "" or topic == current_filter:
            m = msg_cache[-1]
            msg_list.controls.append(
                ft.Text('[%s] %s' % (m["time"], m["line"]), size=12.5, selectable=True, color=m["color"])
            )
            page.update()

    def set_status(text: str, color=None):
        conn_status.value = text
        conn_status.color = color
        page.update()

    def save_config(e=None):
        with cfg_lock:
            try:
                cfg["url"] = url_field.value
                cfg["auto_subscribe"] = auto_subscribe_sw.value
                cfg["auto_reconnect"] = auto_reconnect_sw.value
                for k, f in tpl_fields.items():
                    cfg["templates"][k] = f.value or DEFAULT_TEMPLATES[k]
                p = config_path()
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as err:
                append_msg(f"配置保存失败：{err}", ft.Colors.BLACK)

    # ---- 发送帧（模板渲染） ----
    def send_frame(kind: str, topic: str, message: str = None) -> bool:
        ws = state["ws"]
        if ws is None:
            set_status("未连接，请先连接服务器", ft.Colors.BLACK)
            return False
        frame = render_frame(cfg["templates"][kind], topic, message)
        try:
            ws.send(frame)
            append_msg(f"→ {frame}", ft.Colors.BLACK,
                       topic=topic if kind == "publish" else None)
            return True
        except Exception as err:
            append_msg(f"发送失败：{err}", ft.Colors.BLACK)
            return False

    # ---- WebSocketApp 回调（运行在 ws 接收线程） ----

    def on_open(ws):
        state["pending_open"] = False
        state["reconnect_delay"] = RECONNECT_MIN_SEC
        set_status("已连接", ft.Colors.BLACK)
        append_msg(f"已连接 {state['url']}", ft.Colors.BLACK, bold=True)
        subscribed.clear()
        if auto_subscribe_sw.value:
            for t in list(cfg["topics"]):
                if send_frame("subscribe", t):
                    subscribed.add(t)
        render_topics()

    def on_message(ws, raw):
        # 结构化解析优先：{"topic": "...", "message"/"data": ...}
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "topic" in data:
                topic = str(data.get("topic"))
                body = data.get("message", data.get("data", raw))
                append_msg(f"[{topic}] {body}", topic=topic)
                return
        except Exception:
            pass
        append_msg(str(raw))

    def on_error(ws, err):
        append_msg(f"连接错误：{err}", ft.Colors.BLACK)

    def on_close(ws, code, reason):
        state["ws"] = None
        state["pending_open"] = False
        subscribed.clear()
        render_topics()
        if state["user_close"]:
            set_status("已主动断开", ft.Colors.BLACK)
            append_msg(f"已主动断开（code={code}）", ft.Colors.BLACK)
        else:
            set_status("连接异常断开", ft.Colors.BLACK)
            append_msg(f"连接异常断开（code={code}），将自动重连", ft.Colors.BLACK)
            schedule_reconnect()

    def schedule_reconnect():
        """异常断线后按指数退避自动重连。"""
        if not auto_reconnect_sw.value or state["user_close"]:
            return
        delay = state["reconnect_delay"]
        state["reconnect_delay"] = min(delay * 2, RECONNECT_MAX_SEC)
        append_msg(f"{delay}s 后自动重连 {state['url']} …", ft.Colors.BLACK)
        t = threading.Timer(delay, do_connect)
        t.daemon = True
        state["reconnect_timer"] = t
        t.start()

    def cancel_watchdog():
        wd = state["watchdog"]
        if wd is not None:
            wd.cancel()
            state["watchdog"] = None

    def do_connect(e=None):
        """发起连接：断开旧连接 → 打开新 WebSocketApp → 启动超时看门狗。"""
        state["user_close"] = False
        url = to_ws_url(url_field.value)
        if not url:
            set_status("请先填写服务地址", ft.Colors.BLACK)
            return
        rt = state["reconnect_timer"]
        if rt is not None:
            rt.cancel()
            state["reconnect_timer"] = None
        old = state["ws"]
        if old is not None:
            state["user_close"] = True
            try:
                old.close()
            except Exception:
                pass
            state["ws"] = None
        state["url"] = url
        url_field.value = url
        set_status("连接中…", ft.Colors.BLACK)
        page.update()
        ws = websocket.WebSocketApp(
            url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        state["ws"] = ws
        state["pending_open"] = True
        threading.Thread(
            target=ws.run_forever,
            kwargs={"ping_interval": 20, "ping_timeout": 10},
            daemon=True,
            name="ws-reader",
        ).start()

        # 看门狗：超时未完成握手则强制关闭，交给 on_close 重连逻辑
        def watchdog():
            if state["pending_open"]:
                append_msg(f"连接超时（>{CONNECT_TIMEOUT_SEC}s），尝试中断", ft.Colors.BLACK)
                try:
                    ws.close()
                except Exception:
                    pass

        wd = threading.Timer(CONNECT_TIMEOUT_SEC, watchdog)
        wd.daemon = True
        state["watchdog"] = wd
        wd.start()

    def on_disconnect(e=None):
        state["user_close"] = True
        cancel_watchdog()
        ws = state["ws"]
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    atexit.register(on_disconnect)

    # ---- 主题管理（列表化） ----
    pub_topic_dd = ft.Dropdown(label="发布目标主题", width=180, text_size=13)
    new_topic_field = ft.TextField(label="新主题", width=220, text_size=13)
    topics_column = ft.Column(spacing=4)

    def render_topics():
        rows = []
        for t in list(cfg["topics"]):
            is_sub = t in subscribed
            rows.append(
                ft.Row(
                    [
                        ft.Container(
                            ft.Text(t, size=13, weight=ft.FontWeight.BOLD,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            width=150 if len(t) < 18 else 260,
                        ),
                        ft.Container(
                            ft.Text(
                                "已订阅" if is_sub else "未订阅",
                                size=11,
                                color=ft.Colors.BLACK if is_sub else ft.Colors.BLACK,
                            ),
                            width=52,
                        ),
                        ft.TextButton(
                            "退订" if is_sub else "订阅",
                            on_click=lambda e, tt=t, s=is_sub: toggle_topic(tt, s),
                        ),
                        ft.IconButton(
                            ft.Icons.DELETE_OUTLINE,
                            icon_size=18,
                            tooltip="删除主题",
                            on_click=lambda e, tt=t: delete_topic(tt),
                        ),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        topics_column.controls = rows
        pub_topic_dd.options = [ft.dropdown.Option(t) for t in cfg["topics"]]
        pub_topic_dd.value = cfg["topics"][0] if cfg["topics"] else None
        page.update()

    def add_topic(e=None):
        t = (new_topic_field.value or "").strip()
        if not t:
            return
        if t not in cfg["topics"]:
            cfg["topics"].append(t)
            save_config()
        new_topic_field.value = ""
        render_topics()
        # 已连接时动态添加立即生效
        if state["ws"] is not None:
            if send_frame("subscribe", t):
                subscribed.add(t)
                render_topics()

    def toggle_topic(t, is_sub):
        if is_sub:
            if send_frame("unsubscribe", t):
                subscribed.discard(t)
        else:
            if send_frame("subscribe", t):
                subscribed.add(t)
        render_topics()

    def delete_topic(t):
        if t in subscribed:
            send_frame("unsubscribe", t)
            subscribed.discard(t)
        if t in cfg["topics"]:
            cfg["topics"].remove(t)
            save_config()
        render_topics()

    def subscribe_all(e=None):
        ok = 0
        for t in list(cfg["topics"]):
            if send_frame("subscribe", t):
                subscribed.add(t)
                ok += 1
        append_msg(f"批量订阅完成：{ok}/{len(cfg['topics'])}", ft.Colors.BLACK)
        render_topics()

    def unsubscribe_all(e=None):
        for t in list(subscribed):
            send_frame("unsubscribe", t)
        subscribed.clear()
        append_msg("已退订全部主题", ft.Colors.BLACK)
        render_topics()

    # ---- 发布 ----
    def on_publish(e=None):
        t = pub_topic_dd.value
        text = msg_field.value or ""
        if not t:
            append_msg("请选择发布目标主题", ft.Colors.BLACK)
            return
        if not text:
            append_msg("请填写消息内容", ft.Colors.BLACK)
            return
        send_frame("publish", t, text)

    msg_field = ft.TextField(
        label="要发布的消息内容", width=240, text_size=13, on_submit=on_publish
    )

    # ---- 协议模板编辑 ----
    tpl_fields = {
        k: ft.TextField(
            value=cfg["templates"][k],
            width=420,
            text_size=12,
            label={"subscribe": "订阅帧模板", "unsubscribe": "退订帧模板", "publish": "发布帧模板"}[k],
            on_blur=save_config,
        )
        for k in ("subscribe", "unsubscribe", "publish")
    }

    tpl_tile = ft.ExpansionTile(
        title=ft.Text("协议模板（{topic} / {message} 占位符，适配任意服务端）", size=13),
        expanded=False,
        controls=[
            ft.Container(
                ft.Column(
                    list(tpl_fields.values()),
                    spacing=8,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                width=440,
            )
        ],
    )

    # ---- 布局 ----
    conn_section = ft.Column(
        [
            ft.Row(
                [
                    ft.Button("连接", on_click=do_connect),
                    ft.Button("断开", on_click=on_disconnect),
                    auto_reconnect_sw,
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=12,
            ),
            conn_status,
            ft.Container(auto_subscribe_sw, alignment=ft.Alignment.CENTER),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=8,
    )

    topics_section = ft.Column(
        [
            ft.Text("主题管理", size=16, weight=ft.FontWeight.BOLD),
            ft.Row(
                [new_topic_field, ft.Button("添加", on_click=add_topic)],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=8,
            ),
            ft.Container(
                content=topics_column,
                width=420,
                border=ft.Border.all(1, ft.Colors.GREY_300),
                border_radius=8,
                padding=8,
            ),
            ft.Row(
                [ft.Button("全部订阅", on_click=subscribe_all), ft.Button("全部退订", on_click=unsubscribe_all)],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=10,
            ),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=8,
    )

    pub_section = ft.Column(
        [
            ft.Text("发布消息", size=16, weight=ft.FontWeight.BOLD),
            ft.Row(
                [pub_topic_dd, msg_field, ft.Button("发布", on_click=on_publish)],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=8,
            ),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=8,
    )

    log_section = ft.Column(
        [
            ft.Text("消息日志", size=16, weight=ft.FontWeight.BOLD),
            ft.Row(
                [filter_dd, ft.Button("清空日志", on_click=lambda e: (msg_cache.clear(), refresh_filter_options(), render_messages()))],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=10,
            ),
            msg_panel,
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=8,
    )

    page.add(
        counter_section,
        ft.Divider(),
        conn_section,
        url_field,
        tpl_tile,
        ft.Divider(),
        topics_section,
        ft.Divider(),
        pub_section,
        ft.Divider(),
        log_section,
    )

    render_topics()
    append_msg("就绪。先修改地址/协议模板，点击“连接”。", ft.Colors.BLACK)


# Web 本地服务（no_cdn 模式）下，flet 模板把字体回退基址指到 assets/fonts/，
# 该目录不存在 Noto Sans SC 分片，CanvasKit 拿不到中文字体导致中文全部乱码。
# 这里对 flet_web 的 index.html 打补丁过程做一层包装，把回退基址改回
# Google Fonts 标准基址（fonts.gstatic.com 国内可直连，分片路径由引擎内置拼出）。
# 仅影响本地 Web 调试；APK 走 Android 系统字体，不受影响。导入失败（移动端）则跳过。
def _patch_web_font_fallback():
    try:
        from flet_web.fastapi import flet_static_files as _fsf

        _orig = _fsf.patch_index_html

        def _with_font_fallback(index_path, **kwargs):
            _orig(index_path, **kwargs)
            try:
                with open(index_path, encoding="utf-8") as f:
                    html = f.read()
                if "flet.fontFallbackBaseUrl" not in html and "flet.noCdn=" in html:
                    html = html.replace(
                        "flet.noCdn=",
                        'flet.fontFallbackBaseUrl="https://fonts.gstatic.com/s/";\nflet.noCdn=',
                        1,
                    )
                    with open(index_path, "w", encoding="utf-8") as f:
                        f.write(html)
            except Exception:
                pass

        _fsf.patch_index_html = _with_font_fallback
    except Exception:
        pass


_patch_web_font_fallback()

# 打包为 APK 时由 flet 运行时加载 main 模块并调用 main(page)；
# 浏览器/桌面模式下 ft.run 直接启动。view/web_renderer/no_cdn 参数在移动端会被忽略。
# web_renderer 用 CANVAS_KIT：skwasm 渲染器会直连 gstatic.com 拉取资源（国内被墙导致页面卡死）
ft.run(main, view=ft.AppView.WEB_BROWSER, web_renderer=ft.WebRenderer.CANVAS_KIT, no_cdn=True)
