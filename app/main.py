import urllib.request

import flet as ft

# 每次点击循环切换的页面背景色
BG_COLORS = [
    ft.Colors.BLUE_100,
    ft.Colors.GREEN_100,
    ft.Colors.AMBER_100,
    ft.Colors.PURPLE_100,
    ft.Colors.PINK_100,
]

# GET 请求按钮的默认地址
DEFAULT_URL = "https://4526436.r40.cpolar.top"

# 响应内容最大显示字符数，避免超长内容卡顿
MAX_BODY_CHARS = 20000


def main(page: ft.Page):
    page.title = "Flet 点击计数 & 换色 Demo"
    page.padding = 40
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.bgcolor = BG_COLORS[0]
    # 内容超出屏幕时可上下滚动（响应内容可能很长）
    page.scroll = ft.ScrollMode.AUTO

    # ---------- 计数 & 换色 ----------
    count = 0

    count_text = ft.Text("0", size=72, weight=ft.FontWeight.BOLD)
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

    click_btn = ft.Button("点击我 +1", on_click=on_click)

    counter_section = ft.Column(
        [hint_text, count_text, click_btn],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=20,
    )

    # ---------- GET 请求 ----------
    url_field = ft.TextField(
        value=DEFAULT_URL,
        width=380,
        label="请求地址",
        text_size=13,
    )

    status_text = ft.Text("尚未请求", size=14, color=ft.Colors.GREY_700)
    body_text = ft.Text("", size=13, selectable=True)

    def do_request(url: str):
        """在线程中执行 GET 请求，完成后更新界面。"""
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "FletDemo/1.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                status_text.value = (
                    f"HTTP {resp.status} · {len(data)} 字节 · {charset}"
                )
                body = data.decode(charset, errors="replace")
                if len(body) > MAX_BODY_CHARS:
                    body = body[:MAX_BODY_CHARS] + "\n…（内容过长，已截断）"
                body_text.value = body
        except Exception as err:
            status_text.value = f"请求失败：{err}"
            body_text.value = ""
        finally:
            get_btn.disabled = False
            page.update()

    def on_get(e):
        url = (url_field.value or "").strip()
        if not url:
            status_text.value = "请先填写 URL"
            body_text.value = ""
            page.update()
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        status_text.value = "请求中…"
        body_text.value = ""
        get_btn.disabled = True
        page.update()
        # 后台线程执行网络请求，避免阻塞 UI
        page.run_thread(do_request, url)

    get_btn = ft.Button("GET 请求", on_click=on_get)

    get_section = ft.Column(
        [url_field, get_btn, status_text, body_text],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=15,
    )

    page.add(
        counter_section,
        ft.Divider(),
        get_section,
    )


# 打包为 APK 时由 flet 运行时加载 main 模块并调用 main(page)；
# 浏览器/桌面模式下 ft.run 直接启动。view 参数在移动端会被忽略。
ft.run(main)
