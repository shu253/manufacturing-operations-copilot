from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from .feishu_core import (
    AssistantGateway,
    FeishuApiClient,
    FeishuBotService,
    FeishuConfig,
    FeishuEventStore,
    configure_proxy_environment,
    load_env_file,
    parse_sdk_message,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_service(config: FeishuConfig) -> FeishuBotService:
    return FeishuBotService(
        config=config,
        store=FeishuEventStore(config.database_path),
        assistant=AssistantGateway(config),
        replies=FeishuApiClient(config),
    )


def run_check(config: FeishuConfig) -> int:
    config.validate()
    replies = FeishuApiClient(config)
    assistant = AssistantGateway(config)
    replies.check_credentials()
    health = assistant.check_health()
    assistant_mode = (health.get("data") or {}).get("assistant_mode", "unknown")
    print("Feishu credentials: OK")
    print(f"Local assistant API: OK ({assistant_mode})")
    print(f"Access mode: {config.access_mode}")
    print(f"Configured users: {len(config.allowed_users)}")
    return 0


def run_bot(config: FeishuConfig) -> int:
    config.validate()
    # lark-oapi currently uses requests/urllib3 internally. NO_PROXY must be
    # configured before importing the SDK so Windows proxy discovery is bypassed.
    configure_proxy_environment(config)
    try:
        import lark_oapi as lark
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTriggerResponse,
        )
    except ImportError as exc:
        raise RuntimeError(
            "The Feishu SDK is not installed. Run: "
            "python -m pip install -r requirements.txt"
        ) from exc

    service = build_service(config)

    def on_message(data: Any) -> None:
        try:
            message = parse_sdk_message(data)
            service.accept(message)
        except Exception:
            logging.getLogger("feishu-bot").exception(
                "Unable to accept a Feishu message event"
            )
        # Do not block here. The SDK treats a normal return as a successful ack.

    def on_card_action(data: Any):
        try:
            event = getattr(data, "event", None)
            operator = getattr(event, "operator", None)
            action = getattr(event, "action", None)
            value = getattr(action, "value", None) or {}
            action_type = str(value.get("action") or "")
            operator_open_id = str(
                getattr(operator, "open_id", "") or ""
            )
            if action_type == "confirm_management_action":
                result = service.assistant.confirm_management_action(
                    str(value.get("confirmation_token") or ""),
                    operator_open_id,
                )
                delivery_status = str(
                    result.get("delivery_status") or ""
                )
                if delivery_status in {"sent", "acknowledged"}:
                    content = "管理动作已发送"
                    toast_type = "success"
                elif delivery_status == "already_processed":
                    content = "该管理动作已经处理，请勿重复点击"
                    toast_type = "info"
                else:
                    content = "管理动作已提交，系统正在发送"
                    toast_type = "success"
                return P2CardActionTriggerResponse(
                    {"toast": {"type": toast_type, "content": content}}
                )
            service.assistant.submit_feedback(
                str(value.get("notification_id") or ""),
                operator_open_id,
                action_type,
                value.get("feedback"),
            )
            return P2CardActionTriggerResponse(
                {"toast": {"type": "success", "content": "回执已提交"}}
            )
        except Exception:
            logging.getLogger("feishu-bot").exception("Unable to process card action")
            return P2CardActionTriggerResponse(
                {"toast": {"type": "error", "content": "回执失败，请稍后重试"}}
            )

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .register_p2_card_action_trigger(on_card_action)
        .build()
    )
    client = lark.ws.Client(
        config.app_id,
        config.app_secret,
        event_handler=event_handler,
        # INFO logs include the full WebSocket URL and short-lived connection
        # ticket. Keep SDK logs at WARNING so credentials never land in logs.
        log_level=lark.LogLevel.WARNING,
    )
    logging.getLogger("feishu-bot").info(
        "Starting Feishu long-connection bot with %d authorized user(s)",
        len(config.allowed_users),
    )
    try:
        client.start()
    finally:
        service.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Feishu long-connection adapter for the business assistant"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate credentials and the local assistant API, then exit",
    )
    args = parser.parse_args()

    load_env_file(PROJECT_ROOT / ".env")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        config = FeishuConfig.from_env(PROJECT_ROOT)
        return run_check(config) if args.check else run_bot(config)
    except Exception as exc:
        logging.getLogger("feishu-bot").exception("Feishu bot failed to start")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
