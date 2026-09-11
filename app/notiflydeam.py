import asyncio

import flet as ft
from flet_android_notifications import FletAndroidNotifications

# 启动后自动推送测试通知的延迟（秒）
AUTO_NOTIFY_DELAY = 6

# 通知内容
NOTIFICATION_TITLE = "任务完成"
NOTIFICATION_BODY = "数据已成功同步到服务器"
NOTIFICATION_ID = 1


def main(page: ft.Page):
    page.title = "通知示例"

    # Android 走系统级通知；浏览器/桌面没有原生实现，回退为应用内横幅
    is_android = page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.ANDROID_TV)
    native = FletAndroidNotifications() if is_android else None

    async def send_native_notification():
        await native.request_permissions()
        await native.show_notification(
            notification_id=NOTIFICATION_ID,
            title=NOTIFICATION_TITLE,
            body=NOTIFICATION_BODY,
        )

    def show_notification():
        if is_android:
            page.run_task(send_native_notification)
            return

        # 回退方案：应用内通知横幅（SnackBar），无需第三方依赖
        page.show_dialog(
            ft.SnackBar(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN_400),
                        ft.Column(
                            [
                                ft.Text(
                                    NOTIFICATION_TITLE,
                                    weight=ft.FontWeight.BOLD,
                                ),
                                ft.Text(NOTIFICATION_BODY),
                            ],
                            spacing=2,
                            tight=True,
                        ),
                    ],
                    spacing=12,
                ),
                bgcolor=ft.Colors.GREY_900,
                behavior=ft.SnackBarBehavior.FLOATING,
                duration=ft.Duration(seconds=4),
            )
        )

    async def auto_notify():
        # 启动后延迟自动推送测试通知
        await asyncio.sleep(AUTO_NOTIFY_DELAY)
        show_notification()

    page.add(
        ft.Button(
            content="发送通知",
            icon=ft.Icons.NOTIFICATIONS,
            on_click=lambda e: show_notification(),
        ),
    )

    page.run_task(auto_notify)


ft.run(main)
