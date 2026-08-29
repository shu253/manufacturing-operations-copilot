from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from api.action_hub import ActionHub  # noqa: E402
from api.ai_store import AIAuditStore  # noqa: E402
from api.store import OperationalStore  # noqa: E402
from channels.feishu_core import load_env_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="管理飞书身份映射和通知发件箱")
    parser.add_argument(
        "--database",
        default=str(PROJECT_ROOT / "data" / "huadong_jinggong_demo.sqlite3"),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    bind = sub.add_parser("bind")
    bind.add_argument("--employee-id", type=int, required=True)
    bind.add_argument("--open-id", required=True)
    bind.add_argument(
        "--role", choices=["owner", "plant_manager", "department_head"], required=True
    )
    bind.add_argument("--department-id", type=int)
    bind.add_argument("--plant-id", type=int)
    bind.add_argument("--actor-open-id")
    sub.add_parser("list-bindings")
    retry = sub.add_parser("retry")
    retry.add_argument("--notification-id", required=True)
    sub.add_parser("retry-failed")
    args = parser.parse_args()

    load_env_file(PROJECT_ROOT / ".env")
    audit = AIAuditStore(args.database)
    store = OperationalStore(args.database)
    hub = ActionHub(args.database, audit, store)
    if args.command == "bind":
        result = hub.upsert_binding(
            {
                "employee_id": args.employee_id,
                "feishu_open_id": args.open_id,
                "access_role": args.role,
                "department_id": args.department_id,
                "plant_id": args.plant_id,
                "actor_open_id": args.actor_open_id,
            }
        )
    elif args.command == "list-bindings":
        result = hub.list_bindings()
    elif args.command == "retry":
        result = hub.send_notification(args.notification_id)
    else:
        result = []
        for item in hub.list_notifications("failed", 500):
            result.append(hub.send_notification(item["notification_id"]))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
