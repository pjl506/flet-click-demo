import flet as ft

# 每次点击循环切换的页面背景色
BG_COLORS = [
    ft.Colors.BLUE_100,
    ft.Colors.GREEN_100,
    ft.Colors.AMBER_100,
    ft.Colors.PURPLE_100,
    ft.Colors.PINK_100,
]


def main(page: ft.Page):
    page.title = "Flet 点击计数 & 换色 Demo"
    page.padding = 40
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.bgcolor = BG_COLORS[0]

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

    page.add(
        ft.Column(
            [hint_text, count_text, click_btn],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=20,
        )
    )


# 本机装有天锐绿盾（Tipray LdTerm）等安全软件，会在进程创建时向 flet 桌面客户端
# （flet.exe）注入钩子，导致其插件 DLL 被加载器判定为"损坏的映像"(0xc000012f)，
# 桌面窗口模式无法启动。因此这里使用浏览器模式渲染同样的 UI。
# 若日后在绿盾控制台将 flet.exe 加白，可将 VIEW 改回 ft.AppView.FLET_APP。
VIEW = ft.AppView.WEB_BROWSER

ft.run(main, view=VIEW)
#ft.run(main)
