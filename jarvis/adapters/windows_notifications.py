from __future__ import annotations

import asyncio

from jarvis.domain.v2 import Notification


class WindowsNotificationDelivery:
    def __init__(self, *, app_id: str = "Jarvis") -> None:
        self.app_id = app_id

    async def deliver(self, notification: Notification) -> None:
        await asyncio.to_thread(self._deliver_sync, notification)

    def _deliver_sync(self, notification: Notification) -> None:
        try:
            from winrt.windows.data.xml.dom import XmlDocument  # type: ignore
            from winrt.windows.ui.notifications import ToastNotification, ToastNotificationManager  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Windows toast support requires optional WinRT packages") from exc
        xml = XmlDocument()
        xml.load_xml(f'<toast><visual><binding template="ToastGeneric"><text>{self._xml(notification.summary)}</text><text>{self._xml(notification.body)}</text></binding></visual></toast>')
        ToastNotificationManager.create_toast_notifier(self.app_id).show(ToastNotification(xml))

    @staticmethod
    def _xml(value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


class NullNotificationDelivery:
    async def deliver(self, notification: Notification) -> None:
        del notification
