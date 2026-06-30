from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message

from application.use_cases.services import AppServices


class RbacMiddleware(BaseMiddleware):
    def __init__(self, services: AppServices) -> None:
        self._services = services

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.text:
            cmd = event.text.strip().split()[0]
            permission = _permission_for_command(cmd)
            if permission is not None and event.from_user is not None:
                user = data.get("current_user")
                if user is None:
                    user = await self._services.register_or_get_user(
                        event.from_user.id,
                        language_code=event.from_user.language_code,
                    )
                    data["current_user"] = user
                async with self._services._uow.transaction():
                    allowed = await self._services._roles.user_has_permission(user.id, permission)
                if not allowed:
                    await event.answer("Forbidden")
                    return None
        return await handler(event, data)


def _permission_for_command(cmd: str) -> str | None:
    cmd = cmd.split("@", 1)[0].lower()
    mapping: dict[str, str] = {
        "/setprice": "manage_prices",
        "/grantrole": "manage_roles",
        "/approveorder": "approve_payments",
        "/rejectorder": "reject_payments",
        "/approvepayment": "approve_payments",
        "/rejectpayment": "reject_payments",
        "/trialbalance": "view_financial_reports",
        "/pnl": "view_financial_reports",
        "/balancesheet": "view_financial_reports",
        "/cashflow": "view_financial_reports",
        "/financialdashboard": "view_financial_reports",
        "/dailyreport": "view_financial_reports",
        "/weeklyreport": "view_financial_reports",
        "/monthlyreport": "view_financial_reports",
        "/yearlyreport": "view_financial_reports",
        "/exporttrialbalance": "export_reports",
        "/exportpnl": "export_reports",
        "/exportbalancesheet": "export_reports",
        "/exportcashflow": "export_reports",
        "/manualjournal": "manage_accounts",
        "/addbankaccount": "manage_accounts",
        "/listbankaccounts": "manage_accounts",
        "/addcard": "manage_accounts",
        "/listcards": "manage_accounts",
        "/reviewkyc": "verify_identity",
        "/setrisk": "approve_critical_actions",
        "/pendingcancels": "manage_orders",
        "/approvecancel": "manage_orders",
        "/rejectcancel": "manage_orders",
        "/backup": "configure_system",
        "/restore": "configure_system",
        "/maintenance": "configure_system",
        "/maintenanceon": "configure_system",
        "/maintenanceoff": "configure_system",
        "/broadcast": "broadcast_messages",
        "/broadcastrole": "broadcast_messages",
        "/broadcastlang": "broadcast_messages",
        "/broadcastkyc": "broadcast_messages",
        "/broadcastactive": "broadcast_messages",
        "/broadcastschedule": "broadcast_messages",
        "/broadcastreply": "broadcast_messages",
        "/settle": "manage_settlement",
        "/settlementhistory": "manage_settlement",
        "/settlementstatus": "manage_settlement",
        "/rollbacksettlement": "manage_settlement",
        "/replaysettlement": "manage_settlement",
    }
    return mapping.get(cmd)
