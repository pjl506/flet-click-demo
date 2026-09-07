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


# 打包为 APK 时由 flet 运行时加载 main 模块并调用 main(page)；
# 浏览器/桌面模式下 ft.run 直接启动。view 参数在移动端会被忽略。
ft.run(main)
