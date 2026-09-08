import json
import threading

import websocket  # websocket-client

import flet as ft

# WebSocket 服务默认地址（http/https 会自动转为 ws/wss）
DEFAULT_WS_URL = "wss://4526436.r40.cpolar.top"

# 每次点击循环切换的页面背景色
BG_COLORS = [
    ft.Colors.BLUE_100,
    ft.Colors.GREEN_100,
    ft.Colors.AMBER_100,
    ft.Colors.PURPLE_100,
    ft.Colors.PINK_100,
]

# 消息列表最多保留条数
MAX_MESSAGES = 200


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


def main(page: ft.Page):
    page.title = "Flet WebSocket 订阅/发布 Demo"
    page.padding = 30
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.bgcolor = BG_COLORS[0]
    page.scroll = ft.ScrollMode.AUTO

    # ---------- 计数 & 换色 ----------
    count = 0

    count_text = ft.Text("0", size=60, weight=ft.FontWeight.BOLD)
    hint_text = ft.Text(
        "点击按钮：计数 +1，同时切换页面背景色",
        size=14,
        color=ft.Colors.GREY_700,
    )

    def on_click(e):
        nonlocal count
        count += 1
        count_text.value = str(count)
        page.bgcolor = BG_COLORS[count % len(BG_COLORS)]
        page.update()

    counter_section = ft.Column(
        [
            hint_text,
            count_text,
            ft.Button("点击我 +1", on_click=on_click),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=15,
    )

    # ---------- WebSocket 订阅/发布 ----------
    ws_app = None  # websocket.WebSocketApp 实例

    url_field = ft.TextField(value=DEFAULT_WS_URL, width=380, label="服务地址", text_size=13)
    topic_field = ft.TextField(value="demo", width=380, label="主题 topic", text_size=13)
    msg_field = ft.TextField(width=380, label="要发布的消息内容", text_size=13)

    conn_status = ft.Text("未连接", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_700)

    # 收到的消息列表：新消息到达自动追加并滚动到底部
    msg_list = ft.ListView(
        expand=False,
        height=260,
        spacing=6,
        auto_scroll=True,
        padding=10,
    )
    msg_panel = ft.Container(
        content=msg_list,
        width=380,
        border=ft.Border.all(1, ft.Colors.GREY_400),
        border_radius=8,
        bgcolor=ft.Colors.with_opacity(0.5, ft.Colors.WHITE),
    )

    def append_msg(line: str, color=None, bold=False):
        """追加一条消息并自动刷新到界面（线程安全：flet 支持线程内 update）。"""
        msg_list.controls.append(
            ft.Text(line, size=13, selectable=True, color=color, weight=ft.FontWeight.BOLD if bold else None)
        )
        if len(msg_list.controls) > MAX_MESSAGES:
            msg_list.controls = msg_list.controls[-MAX_MESSAGES:]
        page.update()

    def set_status(text: str, color=None):
        conn_status.value = text
        conn_status.color = color
        page.update()

    def send_frame(obj: dict) -> bool:
        if ws_app is None:
            set_status("未连接，请先连接服务器", ft.Colors.RED_700)
            return False
        try:
            ws_app.send(json.dumps(obj, ensure_ascii=False))
            return True
        except Exception as err:
            append_msg(f"发送失败：{err}", ft.Colors.RED_700)
            return False

    # ---- WebSocketApp 回调（运行在 ws 接收线程中） ----

    def on_open(ws):
        set_status("已连接", ft.Colors.GREEN_700)
        append_msg("已连接服务器", ft.Colors.GREEN_700, bold=True)
        # 连接后自动订阅当前主题
        t = (topic_field.value or "").strip()
        if t:
            if send_frame({"action": "subscribe", "topic": t}):
                append_msg(f'→ 已发送订阅：{{"action":"subscribe","topic":"{t}"}}')

    def on_message(ws, raw):
        # 尝试解析 JSON 并结构化展示，失败则原样显示
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "topic" in data:
                body = data.get("message", data.get("data", raw))
                append_msg(f'[{data.get("topic")}] {body}')
                return
        except Exception:
            pass
        append_msg(str(raw))

    def on_error(ws, err):
        append_msg(f"连接错误：{err}", ft.Colors.RED_700)

    def on_close(ws, code, reason):
        set_status(f"已断开（code={code}）", ft.Colors.GREY_700)
        append_msg(f"连接已关闭（code={code}）", ft.Colors.GREY_700)

    def on_connect(e):
        nonlocal ws_app
        if ws_app is not None:
            try:
                ws_app.close()
            except Exception:
                pass
            ws_app = None
        url = to_ws_url(url_field.value)
        url_field.value = url
        set_status("连接中…", ft.Colors.AMBER_800)
        page.update()
        ws_app = websocket.WebSocketApp(
            url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        threading.Thread(target=ws_app.run_forever, daemon=True, name="ws-reader").start()

    def on_disconnect(e):
        if ws_app is not None:
            try:
                ws_app.close()
            except Exception:
                pass

    def on_subscribe(e):
        t = (topic_field.value or "").strip()
        if not t:
            append_msg("请先填写主题 topic", ft.Colors.RED_700)
            return
        if send_frame({"action": "subscribe", "topic": t}):
            append_msg(f'→ 订阅主题 "{t}"（已发送）', ft.Colors.BLUE_700)

    def on_unsubscribe(e):
        t = (topic_field.value or "").strip()
        if not t:
            append_msg("请先填写主题 topic", ft.Colors.RED_700)
            return
        if send_frame({"action": "unsubscribe", "topic": t}):
            append_msg(f'→ 取消订阅主题 "{t}"（已发送）', ft.Colors.BLUE_700)

    def on_publish(e):
        t = (topic_field.value or "").strip()
        text = msg_field.value or ""
        if not t or not text:
            append_msg("发布需要填写主题和消息内容", ft.Colors.RED_700)
            return
        if send_frame({"action": "publish", "topic": t, "message": text}):
            append_msg(f'→ 已发布到 "{t}"：{text}', ft.Colors.PURPLE_700)

    ws_section = ft.Column(
        [
            ft.Text("WebSocket 订阅 / 发布", size=18, weight=ft.FontWeight.BOLD),
            url_field,
            ft.Row(
                [ft.Button("连接", on_click=on_connect), ft.Button("断开", on_click=on_disconnect)],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=15,
            ),
            conn_status,
            topic_field,
            ft.Row(
                [ft.Button("订阅", on_click=on_subscribe), ft.Button("取消订阅", on_click=on_unsubscribe)],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=15,
            ),
            msg_field,
            ft.Button("发布到主题", on_click=on_publish),
            msg_panel,
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=12,
    )

    page.add(
        counter_section,
        ft.Divider(),
        ws_section,
    )


# 打包为 APK 时由 flet 运行时加载 main 模块并调用 main(page)；
# 浏览器/桌面模式下 ft.run 直接启动。view 参数在移动端会被忽略。
ft.run(main)
