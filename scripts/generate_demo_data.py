from __future__ import annotations

import csv
import json
import math
import random
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path


SEED = 20260805
AS_OF = date(2026, 8, 5)
START_DATE = date(2024, 8, 1)
COMPANY_ID = 1
COMPANY_CODE = "华东某精工"
COMPANY_NAME = "华东某精工装备有限公司"
DISCRETE_UNITS = {"件", "个", "套", "台"}

ROOT = Path(__file__).resolve().parents[1]
CSV_DIR = ROOT / "data" / "demo"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"
DB_PATH = ROOT / "data" / "huadong_jinggong_demo.sqlite3"

rng = random.Random(SEED)


def iso(d: date | None) -> str:
    return d.isoformat() if d else ""


def money(value: float) -> float:
    return round(value + 1e-9, 2)


def qty(value: float) -> float:
    return round(value + 1e-9, 4)


def unit_qty(value: float, unit: str, rounding: str = "nearest") -> float | int:
    """Keep countable materials integral while retaining precision for weight/length units."""
    if unit not in DISCRETE_UNITS:
        return qty(value)
    if rounding == "ceil":
        return int(math.ceil(value - 1e-9))
    if rounding == "floor":
        return int(math.floor(value + 1e-9))
    return int(round(value))


def rand_date(start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, max(0, (end - start).days)))


def month_starts(start: date, end: date) -> list[date]:
    result = []
    current = date(start.year, start.month, 1)
    while current <= end:
        result.append(current)
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return result


def weighted_choice(options: list[tuple[str, float]]) -> str:
    values, weights = zip(*options)
    return rng.choices(values, weights=weights, k=1)[0]


def write_csv(name: str, rows: list[dict]) -> None:
    if not rows:
        return
    path = CSV_DIR / f"{name}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def sqlite_type(values: list[object]) -> str:
    non_empty = [v for v in values if v not in ("", None)]
    if not non_empty:
        return "TEXT"
    if all(isinstance(v, (int, bool)) for v in non_empty):
        return "INTEGER"
    if all(isinstance(v, (int, float, bool)) for v in non_empty):
        return "REAL"
    return "TEXT"


def write_sqlite(tables: dict[str, list[dict]]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    try:
        for table, rows in tables.items():
            if not rows:
                continue
            columns = list(rows[0].keys())
            definitions = []
            for col in columns:
                definitions.append(f'"{col}" {sqlite_type([r[col] for r in rows])}')
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
            conn.execute(f'CREATE TABLE "{table}" ({", ".join(definitions)})')
            placeholders = ", ".join("?" for _ in columns)
            quoted_columns = ", ".join(f'"{column}"' for column in columns)
            conn.executemany(
                f'INSERT INTO "{table}" ({quoted_columns}) VALUES ({placeholders})',
                [[row[col] for col in columns] for row in rows],
            )
        conn.commit()
    finally:
        conn.close()


def build_master_data() -> dict[str, list[dict]]:
    companies = [{
        "company_id": COMPANY_ID,
        "company_code": COMPANY_CODE,
        "company_name": COMPANY_NAME,
        "industry": "非标自动化装备制造",
        "headquarters_city": "嘉兴市",
        "currency": "CNY",
        "timezone": "Asia/Shanghai",
        "is_synthetic": 1,
    }]

    plants = [
        {"plant_id": 1, "company_id": 1, "plant_code": "工厂-苏州", "plant_name": "苏州装配基地", "city": "苏州市", "is_active": 1},
        {"plant_id": 2, "company_id": 1, "plant_code": "工厂-嘉兴", "plant_name": "嘉兴制造基地", "city": "嘉兴市", "is_active": 1},
    ]

    department_names = ["经营管理部", "销售部", "技术研发部", "计划部", "采购部", "生产部", "质量部", "财务部", "仓储物流部", "信息化部"]
    departments = [
        {"department_id": i, "company_id": 1, "department_code": f"部门-{i:02d}", "department_name": name}
        for i, name in enumerate(department_names, 1)
    ]

    employee_names = [
        "张伟明", "王晓峰", "李俊杰", "赵文博", "陈志远", "周海涛", "吴建华", "徐立新", "孙国强", "胡志鹏",
        "朱晓东", "高宇航", "张雨辰", "王佳宁", "李思远", "赵晨曦", "陈浩然", "周子涵", "吴泽宇", "徐嘉怡",
        "孙博文", "胡明轩", "朱静怡", "高欣悦", "张一鸣", "王凯旋", "李梦琪", "赵梓涵", "陈天佑", "周雅雯",
        "吴承泽", "徐若琳", "孙浩宇", "胡佳琪", "朱文昊", "高思琪", "张昊然", "王语桐", "李嘉豪", "赵诗涵",
        "陈奕辰", "周欣妍", "吴俊驰", "徐婉清", "孙睿哲", "胡依诺", "朱景程", "高雨萱", "张启航", "王心怡",
        "李卓远", "赵可欣", "陈彦博", "周舒婷", "吴铭轩", "徐安琪", "孙景行", "胡悦宁", "朱嘉诚", "高曼文",
    ]
    employees = []
    roles = ["经理", "主管", "专员", "工程师", "计划员", "采购员", "质检员", "会计"]
    for i in range(1, 61):
        department_id = (i - 1) % len(departments) + 1
        employees.append({
            "employee_id": i,
            "company_id": 1,
            "employee_code": f"员工-{i:04d}",
            "employee_name": employee_names[i - 1],
            "department_id": department_id,
            "job_title": roles[(i * 5) % len(roles)],
            "plant_id": 1 if i % 3 else 2,
            "is_active": 1,
        })

    customers = []
    cities = ["上海", "苏州", "无锡", "常州", "南京", "杭州", "宁波", "嘉兴", "绍兴", "湖州"]
    customer_industries = ["汽车零部件", "新能源电池", "光伏", "电子电气", "医疗器械", "家电", "通用机械"]
    customer_brands = [
        "启辰", "德瑞", "博远", "科盛", "华锐", "金澜", "鼎新", "朗拓", "瑞恒", "嘉联",
        "宏泽", "新迈", "卓航", "联创", "信达", "凯卓", "远川", "明泰", "正源", "优成",
    ]
    customer_suffixes = {
        "汽车零部件": "汽车部件有限公司", "新能源电池": "新能源科技有限公司", "光伏": "光伏设备有限公司",
        "电子电气": "电子科技有限公司", "医疗器械": "医疗设备有限公司", "家电": "电器制造有限公司",
        "通用机械": "机械制造有限公司",
    }
    for i in range(1, 81):
        city = cities[(i * 7) % len(cities)]
        industry = customer_industries[(i * 5) % len(customer_industries)]
        brand = customer_brands[(i - 1) % len(customer_brands)] + ("精工" if i > len(customer_brands) else "")
        customers.append({
            "customer_id": i,
            "company_id": 1,
            "customer_code": f"客户-{i:04d}",
            "customer_name": f"{city}{brand}{customer_suffixes[industry]}",
            "city": city,
            "industry": industry,
            "credit_days": rng.choice([30, 45, 60, 90]),
            "customer_level": weighted_choice([("A", 0.2), ("B", 0.5), ("C", 0.3)]),
            "is_synthetic": 1,
        })

    suppliers = []
    supplier_categories = ["金属材料", "机加工", "钣金", "电气元件", "气动液压", "标准件", "外协服务"]
    supplier_brands = [
        "恒鑫", "锐科", "佳诚", "泰隆", "盛达", "华坤", "景程", "联盛", "中瑞", "博创",
        "精诚", "宏远", "德昌", "科力", "鑫源", "嘉泰", "鼎丰", "明辉", "卓越", "启航",
        "万通", "瑞达", "华顺", "凯盛", "远大",
    ]
    supplier_suffixes = {
        "金属材料": "金属材料有限公司", "机加工": "精密机械有限公司", "钣金": "钣金制造有限公司",
        "电气元件": "自动化科技有限公司", "气动液压": "液压科技有限公司", "标准件": "工业紧固件有限公司",
        "外协服务": "工业技术服务有限公司",
    }
    for i in range(1, 51):
        city = cities[(i * 3) % len(cities)]
        category = supplier_categories[(i * 2) % len(supplier_categories)]
        brand = supplier_brands[(i - 1) % len(supplier_brands)] + ("精密" if i > len(supplier_brands) else "")
        suppliers.append({
            "supplier_id": i,
            "company_id": 1,
            "supplier_code": f"供应商-{i:04d}",
            "supplier_name": f"{city}{brand}{supplier_suffixes[category]}",
            "city": city,
            "supplier_category": category,
            "payment_terms_days": rng.choice([30, 45, 60, 90]),
            "risk_level": weighted_choice([("低", 0.65), ("中", 0.28), ("高", 0.07)]),
            "is_synthetic": 1,
        })

    warehouses = [
        {"warehouse_id": 1, "plant_id": 1, "warehouse_code": "仓库-苏州-原料", "warehouse_name": "苏州原材料库", "warehouse_type": "原材料"},
        {"warehouse_id": 2, "plant_id": 1, "warehouse_code": "仓库-苏州-成品", "warehouse_name": "苏州成品库", "warehouse_type": "成品"},
        {"warehouse_id": 3, "plant_id": 2, "warehouse_code": "仓库-嘉兴-原料", "warehouse_name": "嘉兴原材料库", "warehouse_type": "原材料"},
        {"warehouse_id": 4, "plant_id": 2, "warehouse_code": "仓库-嘉兴-成品", "warehouse_name": "嘉兴成品库", "warehouse_type": "成品"},
    ]

    category_specs = [
        ("铜材", "CU", "kg", 72.0, 110.0),
        ("钢材", "ST", "kg", 4.5, 13.0),
        ("铝材", "AL", "kg", 18.0, 32.0),
        ("机加工件", "MC", "件", 80.0, 850.0),
        ("钣金件", "SM", "件", 60.0, 680.0),
        ("电气元件", "EL", "件", 35.0, 2800.0),
        ("气动液压", "PN", "件", 45.0, 1600.0),
        ("标准件", "STD", "件", 0.5, 35.0),
    ]
    materials = [{
        "material_id": 1,
        "company_id": 1,
        "material_code": "物料-0001",
        "material_name": "电解铜板",
        "material_category": "铜材",
        "unit": "kg",
        "standard_price": 86.00,
        "safety_stock": 280.0,
        "critical_level": "关键",
        "default_lead_time_days": 18,
        "is_active": 1,
    }]
    material_names = {
        "铜材": ["T2紫铜板", "无氧铜排", "H62黄铜棒", "镀锡铜排", "紫铜管", "黄铜板", "接地铜排", "铜母线", "紫铜棒", "铜编织带", "异形铜排", "磷青铜板", "黄铜管", "紫铜箔", "铜合金套料"],
        "钢材": ["Q235B热轧钢板", "45号圆钢", "40Cr合金圆钢", "304不锈钢板", "Q355B低合金板", "20号无缝钢管", "冷轧钢板", "镀锌钢板", "316L不锈钢板", "矩形钢管", "槽钢", "工字钢", "弹簧钢带", "模具钢板", "精密光轴"],
        "铝材": ["6061铝板", "6063铝型材", "7075航空铝板", "5052铝板", "工业铝型材", "铝合金方管", "铝合金圆棒", "花纹铝板", "阳极氧化铝板", "铝合金角件", "铝合金导轨", "铝合金支撑梁", "铝合金连接板", "铝合金防护框", "铝合金安装座"],
        "机加工件": ["主轴连接法兰", "减速机安装座", "直线导轨底座", "轴承支撑座", "定位销轴", "夹具基板", "传动轴", "滚轮安装轴", "机械手连接块", "升降平台底座", "气缸连接座", "同步轮轴套", "检测工装底板", "旋转台支座", "电机过渡法兰"],
        "钣金件": ["电控柜门板", "设备防护罩", "线槽支架", "传感器安装板", "操作台面板", "机架封板", "底部接油盘", "安全门框", "侧面检修板", "顶部盖板", "电机防护罩", "工位隔板", "拖链支撑板", "气路安装板", "铭牌固定板"],
        "电气元件": ["伺服驱动器", "可编程控制器", "接近开关", "光电传感器", "旋转编码器", "安全继电器", "小型断路器", "开关电源", "触摸屏", "变频器", "交流接触器", "工业交换机", "温度控制器", "急停按钮", "端子排组件"],
        "气动液压": ["标准气缸", "薄型气缸", "电磁换向阀", "过滤减压阀", "气动接头", "压力开关", "真空发生器", "液压油缸", "节流阀", "气源处理组件", "真空吸盘", "气动夹爪", "液压泵站", "高压软管", "快速排气阀"],
        "标准件": ["内六角圆柱头螺钉", "深沟球轴承", "直线导轨", "同步带", "梅花联轴器", "弹簧垫圈", "六角螺母", "圆柱销", "滚珠丝杠", "链轮", "胀紧套", "拖链", "油封", "卡簧", "调节脚杯"],
    }
    category_positions = defaultdict(int)
    for i in range(2, 121):
        category, prefix, unit, low, high = category_specs[(i - 2) % len(category_specs)]
        position = category_positions[category]
        category_positions[category] += 1
        material_code = f"物料-{i:04d}"
        materials.append({
            "material_id": i,
            "company_id": 1,
            "material_code": material_code,
            "material_name": material_names[category][position],
            "material_category": category,
            "unit": unit,
            "standard_price": money(rng.uniform(low, high)),
            "safety_stock": unit_qty(rng.uniform(20, 500) if unit == "kg" else rng.uniform(5, 80), unit, "ceil"),
            "critical_level": weighted_choice([("关键", 0.22), ("重要", 0.38), ("一般", 0.4)]),
            "default_lead_time_days": rng.randint(5, 35),
            "is_active": 1,
        })

    product_families = ["自动装配设备", "自动检测设备", "机器人工作站", "自动上下料设备", "定制生产线"]
    product_models = {
        "自动装配设备": ["HT-ZP1200精密装配机", "HT-ZP1600高速装配机", "HT-ZP2000柔性装配机", "HT-ZP800小型装配机", "HT-ZP1800伺服装配机", "HT-ZP2200多工位装配机", "HT-ZP1500转盘装配机", "HT-ZP2600模块化装配机"],
        "自动检测设备": ["HT-JC600视觉检测机", "HT-JC800尺寸检测机", "HT-JC1000气密检测机", "HT-JC1200综合检测机", "HT-JC500外观检测机", "HT-JC1500在线检测机", "HT-JC900性能检测机", "HT-JC1800终检工作站"],
        "机器人工作站": ["HT-RB10搬运工作站", "HT-RB20焊接工作站", "HT-RB30装配工作站", "HT-RB40码垛工作站", "HT-RB50上下料工作站", "HT-RB60打磨工作站", "HT-RB70涂胶工作站", "HT-RB80协作机器人站"],
        "自动上下料设备": ["HT-SX500料盘上料机", "HT-SX800振动盘上料机", "HT-SX1000桁架上下料机", "HT-SX1200机器人上下料机", "HT-SX600柔性供料机", "HT-SX1500料仓上料机", "HT-SX900输送上下料机", "HT-SX1800高速上下料机"],
        "定制生产线": ["HT-CX01电机装配线", "HT-CX02减速器装配线", "HT-CX03泵阀装配线", "HT-CX04汽车零件检测线", "HT-CX05电池模组装配线", "HT-CX06家电部件装配线", "HT-CX07医疗器械装配线", "HT-CX08精密部件生产线"],
    }
    family_positions = defaultdict(int)
    products = []
    for i in range(1, 41):
        family = product_families[(i - 1) % len(product_families)]
        position = family_positions[family]
        family_positions[family] += 1
        products.append({
            "product_id": i,
            "company_id": 1,
            "product_code": f"产品-{i:03d}",
            "product_name": product_models[family][position],
            "product_family": family,
            "unit": "套",
            "standard_labor_hours": qty(rng.uniform(80, 420)),
            "standard_outsource_cost": money(rng.uniform(3000, 35000)),
            "standard_overhead_rate": round(rng.uniform(0.12, 0.22), 4),
            "is_active": 1,
        })

    bom_headers, bom_lines = [], []
    bom_by_product: dict[int, list[dict]] = {}
    bom_line_id = 1
    for product in products:
        product_id = product["product_id"]
        header_id = product_id
        bom_headers.append({
            "bom_id": header_id,
            "company_id": 1,
            "product_id": product_id,
            "bom_version": "V1.0",
            "effective_from": "2024-01-01",
            "effective_to": "",
            "status": "生效",
        })
        chosen_ids = set(rng.sample(range(2, 121), rng.randint(13, 20)))
        if product_id == 1:
            chosen_ids.add(1)
        product_lines = []
        for material_id in sorted(chosen_ids):
            material = materials[material_id - 1]
            usage = rng.uniform(8, 160) if material["unit"] == "kg" else rng.uniform(1, 18)
            if product_id == 1 and material_id == 1:
                usage = 600.0
            row = {
                "bom_line_id": bom_line_id,
                "bom_id": header_id,
                "material_id": material_id,
                "quantity_per": qty(usage),
                "scrap_rate": round(rng.uniform(0.005, 0.04), 4),
                "is_critical": 1 if material["critical_level"] == "关键" else 0,
            }
            bom_lines.append(row)
            product_lines.append(row)
            bom_line_id += 1
        bom_by_product[product_id] = product_lines

    supplier_materials = []
    supplier_material_id = 1
    for material in materials:
        supplier_ids = rng.sample(range(1, 51), rng.randint(3, 6))
        for rank, supplier_id in enumerate(supplier_ids, 1):
            supplier_materials.append({
                "supplier_material_id": supplier_material_id,
                "supplier_id": supplier_id,
                "material_id": material["material_id"],
                "supplier_material_code": f"供料-{supplier_id:03d}-{material['material_id']:03d}",
                "quoted_price": money(material["standard_price"] * rng.uniform(0.92, 1.12)),
                "lead_time_days": max(3, material["default_lead_time_days"] + rng.randint(-4, 7)),
                "minimum_order_qty": unit_qty(rng.uniform(5, 80), material["unit"], "ceil"),
                "priority_rank": rank,
                "is_approved": 1,
            })
            supplier_material_id += 1

    return {
        "companies": companies,
        "plants": plants,
        "departments": departments,
        "employees": employees,
        "customers": customers,
        "suppliers": suppliers,
        "warehouses": warehouses,
        "materials": materials,
        "products": products,
        "bom_headers": bom_headers,
        "bom_lines": bom_lines,
        "supplier_materials": supplier_materials,
        "_bom_by_product": bom_by_product,
    }


def build_price_and_supplier_history(master: dict) -> dict[str, list[dict]]:
    months = month_starts(START_DATE, AS_OF)
    material_price_history = []
    current_price: dict[int, float] = {}
    price_id = 1
    for material in master["materials"]:
        price = float(material["standard_price"]) * rng.uniform(0.92, 1.03)
        for month in months:
            drift = rng.uniform(-0.025, 0.035)
            if material["material_id"] == 1 and month >= date(2026, 4, 1):
                drift = rng.uniform(0.025, 0.055)
            price = max(0.1, price * (1 + drift))
            market_price = price * rng.uniform(0.97, 1.03)
            material_price_history.append({
                "price_history_id": price_id,
                "material_id": material["material_id"],
                "month": iso(month),
                "average_purchase_price": money(price),
                "market_reference_price": money(market_price),
                "month_over_month_rate": round(drift, 4),
            })
            price_id += 1
        current_price[material["material_id"]] = price

    supplier_score_snapshots = []
    score_id = 1
    for supplier in master["suppliers"]:
        base_delivery = rng.uniform(72, 98)
        base_quality = rng.uniform(84, 99.5)
        base_price = rng.uniform(68, 98)
        for month in months:
            price_score = min(100, max(45, base_price + rng.uniform(-6, 6)))
            delivery_score = min(100, max(40, base_delivery + rng.uniform(-8, 5)))
            quality_score = min(100, max(50, base_quality + rng.uniform(-5, 3)))
            response_score = rng.uniform(65, 98)
            stability_score = rng.uniform(70, 98)
            total = price_score * 0.25 + delivery_score * 0.30 + quality_score * 0.25 + response_score * 0.10 + stability_score * 0.10
            supplier_score_snapshots.append({
                "supplier_score_id": score_id,
                "supplier_id": supplier["supplier_id"],
                "month": iso(month),
                "price_score": round(price_score, 2),
                "delivery_score": round(delivery_score, 2),
                "quality_score": round(quality_score, 2),
                "response_score": round(response_score, 2),
                "stability_score": round(stability_score, 2),
                "total_score": round(total, 2),
                "supplier_grade": "A" if total >= 90 else "B" if total >= 80 else "C" if total >= 70 else "D",
            })
            score_id += 1
    return {
        "material_price_history": material_price_history,
        "supplier_score_snapshots": supplier_score_snapshots,
        "_current_price": current_price,
    }


def build_inventory(master: dict) -> list[dict]:
    rows = []
    inventory_id = 1
    for plant in master["plants"]:
        for material in master["materials"]:
            on_hand = rng.uniform(material["safety_stock"] * 0.4, material["safety_stock"] * 3.5)
            allocated = on_hand * rng.uniform(0.05, 0.55)
            if plant["plant_id"] == 1 and material["material_id"] == 1:
                on_hand, allocated = 90.0, 60.0
            normalized_on_hand = unit_qty(on_hand, material["unit"], "floor")
            normalized_allocated = min(
                normalized_on_hand,
                unit_qty(allocated, material["unit"], "floor"),
            )
            rows.append({
                "inventory_balance_id": inventory_id,
                "company_id": 1,
                "plant_id": plant["plant_id"],
                "warehouse_id": 1 if plant["plant_id"] == 1 else 3,
                "material_id": material["material_id"],
                "on_hand_qty": normalized_on_hand,
                "allocated_qty": normalized_allocated,
                "available_qty": unit_qty(
                    float(normalized_on_hand) - float(normalized_allocated),
                    material["unit"],
                    "floor",
                ),
                "safety_stock_qty": material["safety_stock"],
                "snapshot_date": iso(AS_OF),
            })
            inventory_id += 1
    return rows


def product_unit_cost(product: dict, bom_lines: list[dict], materials: list[dict], current_price: dict[int, float]) -> dict[str, float]:
    material_cost = 0.0
    for line in bom_lines:
        material_cost += float(line["quantity_per"]) * (1 + float(line["scrap_rate"])) * current_price[line["material_id"]]
    labor_cost = float(product["standard_labor_hours"]) * 92.0
    outsource_cost = float(product["standard_outsource_cost"])
    overhead_cost = (material_cost + labor_cost + outsource_cost) * float(product["standard_overhead_rate"])
    logistics_cost = (material_cost + outsource_cost) * 0.025
    total = material_cost + labor_cost + outsource_cost + overhead_cost + logistics_cost
    return {
        "material": money(material_cost),
        "labor": money(labor_cost),
        "outsource": money(outsource_cost),
        "overhead": money(overhead_cost),
        "logistics": money(logistics_cost),
        "total": money(total),
    }


def build_sales_production_and_costs(master: dict, history: dict) -> dict[str, list[dict]]:
    products = master["products"]
    current_price = history["_current_price"]
    bom_by_product = master["_bom_by_product"]

    sales_orders, sales_order_lines = [], []
    production_orders, production_operations = [], []
    requirements = []
    order_cost_snapshots, order_cost_details = [], []
    quotations = []
    requirement_id = operation_id = cost_detail_id = 1

    order_dates = [rand_date(START_DATE, AS_OF) for _ in range(1999)]
    order_dates.sort()
    order_specs = []
    for i, order_date in enumerate(order_dates, 1):
        product_id = rng.randint(1, 40)
        order_specs.append({
            "sales_order_id": i,
            "sales_order_code": f"销售-{i:06d}",
            "order_date": order_date,
            "product_id": product_id,
            "order_qty": rng.choice([1, 1, 1, 2, 2, 3, 4, 5]),
            "customer_id": rng.randint(1, 80),
            "plant_id": 1 if rng.random() < 0.58 else 2,
            "fixed": False,
        })
    order_specs.append({
        "sales_order_id": 2000,
        "sales_order_code": "销售-20260718-01",
        "order_date": date(2026, 7, 18),
        "product_id": 1,
        "order_qty": 3,
        "customer_id": 1,
        "plant_id": 1,
        "fixed": True,
    })

    for spec in order_specs:
        product = products[spec["product_id"] - 1]
        lead_days = 16 if spec["fixed"] else rng.randint(35, 120)
        promised = spec["order_date"] + timedelta(days=lead_days)
        if spec["fixed"]:
            promised = date(2026, 8, 8)
        if promised < AS_OF - timedelta(days=10):
            status = "已完成"
        elif promised <= AS_OF + timedelta(days=45):
            status = weighted_choice([("生产中", 0.72), ("待生产", 0.18), ("部分发货", 0.10)])
        else:
            status = "已确认"

        unit_cost = product_unit_cost(product, bom_by_product[spec["product_id"]], master["materials"], current_price)
        target_margin = 0.165 if spec["fixed"] else rng.uniform(0.18, 0.34)
        unit_price = unit_cost["total"] / (1 - target_margin)
        if spec["fixed"]:
            unit_price = unit_cost["total"] / (1 - 0.165)
        order_amount = money(unit_price * spec["order_qty"])
        sales_orders.append({
            "sales_order_id": spec["sales_order_id"],
            "company_id": 1,
            "sales_order_code": spec["sales_order_code"],
            "customer_id": spec["customer_id"],
            "plant_id": spec["plant_id"],
            "order_date": iso(spec["order_date"]),
            "promised_delivery_date": iso(promised),
            "status": status,
            "sales_owner_id": (spec["customer_id"] % 10) + 1,
            "currency": "CNY",
            "order_amount": order_amount,
            "source_system": "ERP",
        })
        sales_orders_line_id = spec["sales_order_id"]
        sales_order_lines.append({
            "sales_order_line_id": sales_orders_line_id,
            "sales_order_id": spec["sales_order_id"],
            "line_no": 1,
            "product_id": spec["product_id"],
            "order_qty": spec["order_qty"],
            "unit_price": money(unit_price),
            "line_amount": order_amount,
        })

        planned_start = spec["order_date"] + timedelta(days=5)
        planned_finish = promised - timedelta(days=4)
        if status == "已完成":
            progress = 100.0
            actual_finish = planned_finish + timedelta(days=rng.randint(-4, 7))
        elif spec["fixed"]:
            progress = 68.0
            actual_finish = None
        elif status == "部分发货":
            progress = rng.uniform(80, 98)
            actual_finish = None
        elif status == "生产中":
            progress = rng.uniform(20, 88)
            actual_finish = None
        else:
            progress = rng.uniform(0, 12)
            actual_finish = None
        production_orders.append({
            "production_order_id": spec["sales_order_id"],
            "company_id": 1,
            "production_order_code": f"生产-{spec['sales_order_id']:06d}",
            "sales_order_line_id": sales_orders_line_id,
            "plant_id": spec["plant_id"],
            "product_id": spec["product_id"],
            "planned_qty": spec["order_qty"],
            "completed_qty": qty(spec["order_qty"] * progress / 100),
            "planned_start_date": iso(planned_start),
            "planned_finish_date": iso(planned_finish),
            "actual_finish_date": iso(actual_finish),
            "progress_rate": round(progress, 2),
            "status": "已完成" if progress >= 100 else "生产中" if progress > 0 else "待生产",
        })

        operation_names = ["机械加工", "电气装配", "整机装配", "调试检验"]
        for op_no, op_name in enumerate(operation_names, 1):
            threshold = op_no * 25
            op_status = "已完成" if progress >= threshold else "进行中" if progress >= threshold - 25 else "未开始"
            production_operations.append({
                "production_operation_id": operation_id,
                "production_order_id": spec["sales_order_id"],
                "operation_no": op_no,
                "operation_name": op_name,
                "planned_hours": qty(float(product["standard_labor_hours"]) / 4),
                "actual_hours": qty(float(product["standard_labor_hours"]) / 4 * rng.uniform(0.85, 1.18)) if op_status == "已完成" else 0,
                "status": op_status,
            })
            operation_id += 1

        for line in bom_by_product[spec["product_id"]]:
            material = master["materials"][line["material_id"] - 1]
            required_raw = float(line["quantity_per"]) * spec["order_qty"] * (1 + float(line["scrap_rate"]))
            required = unit_qty(required_raw, material["unit"], "ceil")
            issued_ratio = 1.0 if status == "已完成" else min(1.0, progress / 100 * rng.uniform(0.85, 1.1))
            if spec["fixed"] and line["material_id"] == 1:
                issued_ratio = 0.10
            issued = unit_qty(float(required) * issued_ratio, material["unit"], "floor")
            requirements.append({
                "material_requirement_id": requirement_id,
                "production_order_id": spec["sales_order_id"],
                "material_id": line["material_id"],
                "required_date": iso(planned_start),
                "required_qty": required,
                "issued_qty": issued,
                "shortage_qty": unit_qty(max(0, float(required) - float(issued)), material["unit"], "ceil"),
                "is_critical": line["is_critical"],
                "status": "已满足" if issued_ratio >= 0.999 else "部分满足" if issued_ratio > 0 else "未满足",
            })
            requirement_id += 1

        total_cost = money(unit_cost["total"] * spec["order_qty"])
        gross_profit = money(order_amount - total_cost)
        margin = round(gross_profit / order_amount, 4)
        order_cost_snapshots.append({
            "order_cost_snapshot_id": spec["sales_order_id"],
            "sales_order_id": spec["sales_order_id"],
            "snapshot_date": iso(AS_OF if status != "已完成" else min(AS_OF, promised)),
            "material_cost": money(unit_cost["material"] * spec["order_qty"]),
            "labor_cost": money(unit_cost["labor"] * spec["order_qty"]),
            "outsource_cost": money(unit_cost["outsource"] * spec["order_qty"]),
            "overhead_cost": money(unit_cost["overhead"] * spec["order_qty"]),
            "logistics_cost": money(unit_cost["logistics"] * spec["order_qty"]),
            "total_cost": total_cost,
            "sales_revenue": order_amount,
            "gross_profit": gross_profit,
            "gross_margin_rate": margin,
            "cost_type": "预测" if status != "已完成" else "实际",
        })
        for component, amount in [
            ("材料", unit_cost["material"]),
            ("人工", unit_cost["labor"]),
            ("外协", unit_cost["outsource"]),
            ("制造费用", unit_cost["overhead"]),
            ("包装物流", unit_cost["logistics"]),
        ]:
            order_cost_details.append({
                "order_cost_detail_id": cost_detail_id,
                "order_cost_snapshot_id": spec["sales_order_id"],
                "cost_component": component,
                "amount": money(amount * spec["order_qty"]),
                "calculation_basis": "BOM与当前价格" if component == "材料" else "标准费率",
            })
            cost_detail_id += 1

        if spec["sales_order_id"] <= 800:
            quotation_date = spec["order_date"] - timedelta(days=rng.randint(3, 18))
            quotations.append({
                "quotation_id": spec["sales_order_id"],
                "quotation_code": f"报价-{spec['sales_order_id']:06d}",
                "customer_id": spec["customer_id"],
                "product_id": spec["product_id"],
                "quotation_date": iso(quotation_date),
                "quantity": spec["order_qty"],
                "estimated_cost": total_cost,
                "target_margin_rate": round(target_margin, 4),
                "quoted_amount": order_amount,
                "status": "已转订单",
                "converted_sales_order_id": spec["sales_order_id"],
            })

    return {
        "sales_orders": sales_orders,
        "sales_order_lines": sales_order_lines,
        "production_orders": production_orders,
        "production_operations": production_operations,
        "production_material_requirements": requirements,
        "order_cost_snapshots": order_cost_snapshots,
        "order_cost_details": order_cost_details,
        "quotations": quotations,
    }


def build_procurement_and_quality(master: dict, sales: dict, history: dict) -> dict[str, list[dict]]:
    supplier_material_map: dict[int, list[dict]] = defaultdict(list)
    for row in master["supplier_materials"]:
        supplier_material_map[row["material_id"]].append(row)

    purchase_orders, purchase_order_lines = [], []
    receipts, receipt_lines, quality_inspections = [], [], []
    requirement_allocations = []
    po_line_by_material_plant: dict[tuple[int, int], list[dict]] = defaultdict(list)

    specs = []
    for i in range(1, 4000):
        material_id = rng.randint(1, 120)
        supplier_option = rng.choice(supplier_material_map[material_id])
        order_date = rand_date(START_DATE, AS_OF)
        plant_id = 1 if rng.random() < 0.58 else 2
        specs.append((i, material_id, supplier_option, order_date, plant_id, False))
    fixed_supplier = sorted(supplier_material_map[1], key=lambda x: x["priority_rank"])[0]
    specs.append((4000, 1, fixed_supplier, date(2026, 7, 3), 1, True))

    receipt_id = receipt_line_id = inspection_id = 1
    for po_id, material_id, supplier_option, order_date, plant_id, fixed in specs:
        lead = int(supplier_option["lead_time_days"])
        promised = order_date + timedelta(days=lead)
        delay_days = 0
        if rng.random() < 0.10:
            delay_days = rng.randint(2, 15)
        if fixed:
            promised = date(2026, 7, 29)
            delay_days = 15
        expected = promised + timedelta(days=delay_days)
        po_code = "采购-20260703-01" if fixed else f"采购-{po_id:06d}"
        if expected <= AS_OF:
            status = "已完成"
        elif promised < AS_OF:
            status = "已逾期"
        else:
            status = "在途"
        material = master["materials"][material_id - 1]
        ordered_qty = unit_qty(
            rng.uniform(30, 1200) if material["unit"] == "kg" else rng.uniform(5, 160),
            material["unit"],
            "ceil",
        )
        if fixed:
            ordered_qty = 450.0
        current_price = history["_current_price"][material_id]
        unit_price = current_price * rng.uniform(0.93, 1.10)
        if fixed:
            unit_price = current_price * 1.07
        purchase_orders.append({
            "purchase_order_id": po_id,
            "company_id": 1,
            "purchase_order_code": po_code,
            "supplier_id": supplier_option["supplier_id"],
            "plant_id": plant_id,
            "order_date": iso(order_date),
            "promised_delivery_date": iso(promised),
            "expected_delivery_date": iso(expected),
            "status": status,
            "buyer_id": 21 + (po_id % 6),
            "currency": "CNY",
            "order_amount": money(ordered_qty * unit_price),
            "source_system": "ERP",
        })
        line = {
            "purchase_order_line_id": po_id,
            "purchase_order_id": po_id,
            "line_no": 1,
            "material_id": material_id,
            "ordered_qty": unit_qty(ordered_qty, material["unit"]),
            "received_qty": unit_qty(ordered_qty if status == "已完成" else 0, material["unit"]),
            "unit_price": money(unit_price),
            "line_amount": money(ordered_qty * unit_price),
        }
        purchase_order_lines.append(line)
        po_line_by_material_plant[(material_id, plant_id)].append({
            **line,
            "promised_delivery_date": promised,
            "expected_delivery_date": expected,
        })

        if status == "已完成":
            actual_date = expected
            receipts.append({
                "receipt_id": receipt_id,
                "receipt_code": f"入库-{receipt_id:06d}",
                "purchase_order_id": po_id,
                "supplier_id": supplier_option["supplier_id"],
                "plant_id": plant_id,
                "receipt_date": iso(actual_date),
                "status": "已入库",
            })
            receipt_lines.append({
                "receipt_line_id": receipt_line_id,
                "receipt_id": receipt_id,
                "purchase_order_line_id": po_id,
                "material_id": material_id,
                "received_qty": unit_qty(ordered_qty, material["unit"]),
                "accepted_qty": unit_qty(float(ordered_qty) * rng.uniform(0.96, 1.0), material["unit"], "floor"),
                "rejected_qty": 0,
            })
            fail = rng.random() < 0.035
            inspected = ordered_qty
            rejected = inspected * rng.uniform(0.02, 0.12) if fail else 0
            quality_inspections.append({
                "quality_inspection_id": inspection_id,
                "inspection_code": f"来料检验-{inspection_id:06d}",
                "inspection_type": "来料检验",
                "supplier_id": supplier_option["supplier_id"],
                "material_id": material_id,
                "production_order_id": "",
                "inspection_date": iso(actual_date),
                "inspected_qty": unit_qty(inspected, material["unit"]),
                "accepted_qty": unit_qty(inspected - rejected, material["unit"], "floor"),
                "rejected_qty": unit_qty(rejected, material["unit"], "ceil"),
                "result": "不合格" if fail else "合格",
                "defect_type": rng.choice(["尺寸超差", "表面缺陷", "性能不达标"]) if fail else "",
            })
            receipt_id += 1
            receipt_line_id += 1
            inspection_id += 1

    allocation_id = 1
    for req in sales["production_material_requirements"]:
        if float(req["shortage_qty"]) <= 0:
            continue
        production = sales["production_orders"][req["production_order_id"] - 1]
        candidates = po_line_by_material_plant[(req["material_id"], production["plant_id"])]
        if req["production_order_id"] == 2000 and req["material_id"] == 1:
            selected = next(x for x in candidates if x["purchase_order_id"] == 4000)
        elif candidates:
            target_date = date.fromisoformat(req["required_date"])
            selected = min(candidates, key=lambda x: abs((x["expected_delivery_date"] - target_date).days))
        else:
            continue
        requirement_allocations.append({
            "requirement_allocation_id": allocation_id,
            "material_requirement_id": req["material_requirement_id"],
            "purchase_order_line_id": selected["purchase_order_line_id"],
            "allocated_qty": unit_qty(
                min(float(req["shortage_qty"]), float(selected["ordered_qty"])),
                master["materials"][req["material_id"] - 1]["unit"],
                "floor",
            ),
        })
        allocation_id += 1

    # Production quality inspections for a sample of production orders.
    for production in sales["production_orders"]:
        if production["status"] != "已完成" or rng.random() > 0.35:
            continue
        fail = rng.random() < 0.025
        inspected = float(production["planned_qty"])
        rejected = min(inspected, 1.0) if fail else 0
        quality_inspections.append({
            "quality_inspection_id": inspection_id,
            "inspection_code": f"成品检验-{inspection_id:06d}",
            "inspection_type": "成品检验",
            "supplier_id": "",
            "material_id": "",
            "production_order_id": production["production_order_id"],
            "inspection_date": production["actual_finish_date"],
            "inspected_qty": qty(inspected),
            "accepted_qty": qty(inspected - rejected),
            "rejected_qty": qty(rejected),
            "result": "返工" if fail else "合格",
            "defect_type": "调试参数异常" if fail else "",
        })
        inspection_id += 1

    return {
        "purchase_orders": purchase_orders,
        "purchase_order_lines": purchase_order_lines,
        "receipts": receipts,
        "receipt_lines": receipt_lines,
        "quality_inspections": quality_inspections,
        "requirement_allocations": requirement_allocations,
    }


def build_delivery_and_finance(master: dict, sales: dict) -> dict[str, list[dict]]:
    shipments, shipment_lines = [], []
    invoices, payments, payment_allocations, ar_snapshots = [], [], [], []
    shipment_id = invoice_id = payment_id = allocation_id = ar_id = 1
    for order in sales["sales_orders"]:
        line = sales["sales_order_lines"][order["sales_order_id"] - 1]
        promised = date.fromisoformat(order["promised_delivery_date"])
        if order["status"] == "已完成":
            shipped_qty = float(line["order_qty"])
            shipment_date = promised + timedelta(days=rng.randint(-4, 7))
        elif order["status"] == "部分发货":
            shipped_qty = max(1, math.floor(float(line["order_qty"]) * rng.uniform(0.4, 0.8)))
            shipment_date = min(AS_OF, promised)
        else:
            continue
        shipped_amount = money(float(line["unit_price"]) * shipped_qty)
        shipments.append({
            "shipment_id": shipment_id,
            "shipment_code": f"发货-{shipment_id:06d}",
            "sales_order_id": order["sales_order_id"],
            "customer_id": order["customer_id"],
            "plant_id": order["plant_id"],
            "shipment_date": iso(shipment_date),
            "shipment_amount": shipped_amount,
            "status": "已发货",
        })
        shipment_lines.append({
            "shipment_line_id": shipment_id,
            "shipment_id": shipment_id,
            "sales_order_line_id": line["sales_order_line_id"],
            "product_id": line["product_id"],
            "shipped_qty": shipped_qty,
            "unit_price": line["unit_price"],
            "line_amount": shipped_amount,
        })

        should_invoice = rng.random() < 0.92
        if should_invoice:
            invoice_date = shipment_date + timedelta(days=rng.randint(2, 25))
            due_days = master["customers"][order["customer_id"] - 1]["credit_days"]
            due_date = invoice_date + timedelta(days=due_days)
            invoice_amount = shipped_amount
            invoices.append({
                "invoice_id": invoice_id,
                "invoice_code": f"发票-{invoice_id:06d}",
                "customer_id": order["customer_id"],
                "sales_order_id": order["sales_order_id"],
                "shipment_id": shipment_id,
                "invoice_date": iso(invoice_date),
                "due_date": iso(due_date),
                "invoice_amount": invoice_amount,
                "status": "已开票",
            })
            paid_ratio = weighted_choice([("0", 0.10), ("0.5", 0.10), ("0.8", 0.10), ("1", 0.70)])
            paid_amount = money(invoice_amount * float(paid_ratio))
            if paid_amount > 0:
                payment_date = min(AS_OF, due_date + timedelta(days=rng.randint(-10, 35)))
                payments.append({
                    "payment_id": payment_id,
                    "payment_code": f"回款-{payment_id:06d}",
                    "customer_id": order["customer_id"],
                    "payment_date": iso(payment_date),
                    "payment_amount": paid_amount,
                    "payment_method": rng.choice(["银行转账", "承兑汇票"]),
                })
                payment_allocations.append({
                    "payment_allocation_id": allocation_id,
                    "payment_id": payment_id,
                    "invoice_id": invoice_id,
                    "allocated_amount": paid_amount,
                })
                payment_id += 1
                allocation_id += 1
            invoice_id += 1
        shipment_id += 1

    # Keep daily receivable snapshots for the latest five weeks so the UI can
    # query recent historical dates instead of only the dataset's final day.
    payments_by_id = {row["payment_id"]: row for row in payments}
    allocations_by_invoice: dict[int, list[dict]] = defaultdict(list)
    for allocation in payment_allocations:
        allocations_by_invoice[allocation["invoice_id"]].append(allocation)
    snapshot_start = AS_OF - timedelta(days=35)
    for day_offset in range((AS_OF - snapshot_start).days + 1):
        snapshot_date = snapshot_start + timedelta(days=day_offset)
        for invoice in invoices:
            if date.fromisoformat(invoice["invoice_date"]) > snapshot_date:
                continue
            paid_to_date = sum(
                float(allocation["allocated_amount"])
                for allocation in allocations_by_invoice[invoice["invoice_id"]]
                if date.fromisoformat(
                    payments_by_id[allocation["payment_id"]]["payment_date"]
                ) <= snapshot_date
            )
            outstanding = money(float(invoice["invoice_amount"]) - paid_to_date)
            due_date = date.fromisoformat(invoice["due_date"])
            age_days = max(0, (snapshot_date - due_date).days) if outstanding > 0 else 0
            ar_snapshots.append({
                "ar_snapshot_id": ar_id,
                "snapshot_date": iso(snapshot_date),
                "customer_id": invoice["customer_id"],
                "invoice_id": invoice["invoice_id"],
                "invoice_amount": invoice["invoice_amount"],
                "paid_amount": money(paid_to_date),
                "outstanding_amount": outstanding,
                "due_date": invoice["due_date"],
                "overdue_days": age_days,
                "aging_bucket": "未到期" if due_date >= snapshot_date else "1-30天" if age_days <= 30 else "31-60天" if age_days <= 60 else "61-90天" if age_days <= 90 else "90天以上",
                "risk_level": "低" if outstanding == 0 or due_date >= snapshot_date else "中" if age_days <= 30 else "高",
            })
            ar_id += 1
    return {
        "shipments": shipments,
        "shipment_lines": shipment_lines,
        "invoices": invoices,
        "payments": payments,
        "payment_allocations": payment_allocations,
        "ar_snapshots": ar_snapshots,
    }


def build_risks_tasks_and_simulations(master: dict, sales: dict, procurement: dict, history: dict) -> tuple[dict[str, list[dict]], dict]:
    risk_events, risk_evidence, tasks, messages = [], [], [], []
    simulation_runs, simulation_results = [], []
    ground_truth_events = []
    risk_id = evidence_id = task_id = message_id = 1

    open_orders = [o for o in sales["sales_orders"] if o["status"] != "已完成"]
    fixed_order = next(o for o in open_orders if o["sales_order_code"] == "销售-20260718-01")
    fixed_requirement = next(
        r for r in sales["production_material_requirements"]
        if r["production_order_id"] == 2000 and r["material_id"] == 1
    )
    fixed_po = next(p for p in procurement["purchase_orders"] if p["purchase_order_code"] == "采购-20260703-01")

    def add_risk(order: dict, rule_code: str, score: int, severity: str, cause: str, entity_ref: str, amount: float) -> None:
        nonlocal risk_id, evidence_id, task_id, message_id
        risk_events.append({
            "risk_event_id": risk_id,
            "company_id": 1,
            "risk_code": f"风险-{risk_id:06d}",
            "risk_type": "订单交付",
            "rule_code": rule_code,
            "entity_type": "sales_order",
            "entity_id": order["sales_order_id"],
            "entity_code": order["sales_order_code"],
            "risk_score": score,
            "severity": severity,
            "status": "待处理",
            "detected_at": f"{AS_OF.isoformat()}T08:00:00+08:00",
            "summary": cause,
            "potential_amount": money(amount),
        })
        risk_evidence.append({
            "risk_evidence_id": evidence_id,
            "risk_event_id": risk_id,
            "evidence_type": rule_code,
            "source_table": "production_material_requirements" if "MATERIAL" in rule_code else "production_orders",
            "source_record_code": entity_ref,
            "evidence_value": cause,
        })
        owner_id = 24 if "MATERIAL" in rule_code or "PURCHASE" in rule_code else 32
        tasks.append({
            "task_id": task_id,
            "risk_event_id": risk_id,
            "task_code": f"任务-{task_id:06d}",
            "task_title": f"处理{order['sales_order_code']}风险",
            "owner_employee_id": owner_id,
            "due_date": iso(AS_OF + timedelta(days=1)),
            "status": "待处理",
            "priority": severity,
        })
        messages.append({
            "message_id": message_id,
            "task_id": task_id,
            "recipient_employee_id": owner_id,
            "channel": "站内",
            "message_title": f"{severity}风险：{order['sales_order_code']}",
            "message_body": cause,
            "sent_at": f"{AS_OF.isoformat()}T08:05:00+08:00",
            "status": "已发送",
        })
        ground_truth_events.append({
            "risk_code": f"风险-{risk_id:06d}",
            "order_code": order["sales_order_code"],
            "rule_code": rule_code,
            "expected_score": score,
            "expected_severity": severity,
            "expected_cause": cause,
            "evidence_record": entity_ref,
        })
        risk_id += 1
        evidence_id += 1
        task_id += 1
        message_id += 1

    add_risk(
        fixed_order,
        "MATERIAL_SHORTAGE",
        40,
        "高",
        f"关键物料电解铜板（物料-0001）短缺{fixed_requirement['shortage_qty']}kg",
        str(fixed_requirement["material_requirement_id"]),
        fixed_order["order_amount"],
    )
    add_risk(
        fixed_order,
        "PURCHASE_LATE",
        25,
        "高",
        "采购单采购-20260703-01预计晚于订单需求日期5天以上",
        fixed_po["purchase_order_code"],
        fixed_order["order_amount"],
    )
    add_risk(
        fixed_order,
        "PRODUCTION_DELAY",
        20,
        "高",
        "生产完成率68%，低于计划进度",
        "生产-002000",
        fixed_order["order_amount"],
    )

    candidates = [o for o in open_orders if o["sales_order_code"] != "销售-20260718-01"]
    for order in rng.sample(candidates, min(120, len(candidates))):
        rule = weighted_choice([("MATERIAL_SHORTAGE", 0.45), ("PURCHASE_LATE", 0.30), ("PRODUCTION_DELAY", 0.20), ("QUALITY_REWORK", 0.05)])
        score = {"MATERIAL_SHORTAGE": 40, "PURCHASE_LATE": 25, "PRODUCTION_DELAY": 20, "QUALITY_REWORK": 15}[rule]
        severity = "高" if score >= 40 else "中"
        cause = {
            "MATERIAL_SHORTAGE": "存在关键物料缺口",
            "PURCHASE_LATE": "关联采购订单预计迟到",
            "PRODUCTION_DELAY": "生产进度低于计划",
            "QUALITY_REWORK": "质量返工影响计划",
        }[rule]
        add_risk(order, rule, score, severity, cause, f"AUTO-{order['sales_order_id']}", order["order_amount"])

    # Fixed 8% copper price simulation.
    fixed_cost = sales["order_cost_snapshots"][1999]
    fixed_bom = master["_bom_by_product"][1]
    copper_line = next(x for x in fixed_bom if x["material_id"] == 1)
    copper_current = history["_current_price"][1]
    copper_cost = float(copper_line["quantity_per"]) * (1 + float(copper_line["scrap_rate"])) * 3 * copper_current
    increase = money(copper_cost * 0.08)
    new_total = money(float(fixed_cost["total_cost"]) + increase)
    new_profit = money(float(fixed_cost["sales_revenue"]) - new_total)
    new_margin = round(new_profit / float(fixed_cost["sales_revenue"]), 4)
    simulation_runs.append({
        "simulation_run_id": 1,
        "simulation_code": "测算-铜价上涨8%",
        "simulation_type": "物料价格变化",
        "created_at": f"{AS_OF.isoformat()}T10:00:00+08:00",
        "created_by": 1,
        "parameter_json": json.dumps({"material_code": "物料-0001", "change_rate": 0.08}, ensure_ascii=False),
        "status": "已完成",
    })
    simulation_results.append({
        "simulation_result_id": 1,
        "simulation_run_id": 1,
        "sales_order_id": 2000,
        "sales_order_code": "销售-20260718-01",
        "original_cost": fixed_cost["total_cost"],
        "new_cost": new_total,
        "cost_increase": increase,
        "original_margin_rate": fixed_cost["gross_margin_rate"],
        "new_margin_rate": new_margin,
        "margin_change": round(new_margin - float(fixed_cost["gross_margin_rate"]), 4),
        "recommendation": "优先与现有供应商议价，并评估备选供应商交付稳定性",
    })

    ground_truth = {
        "dataset_name": COMPANY_NAME,
        "seed": SEED,
        "as_of_date": iso(AS_OF),
        "fixed_story": {
            "sales_order_code": "销售-20260718-01",
            "product_code": "产品-001",
            "material_code": "物料-0001",
            "purchase_order_code": "采购-20260703-01",
            "promised_delivery_date": "2026-08-08",
            "production_progress_rate": 68.0,
            "purchase_expected_delivery_date": fixed_po["expected_delivery_date"],
            "simulation_change_rate": 0.08,
            "simulation_cost_increase": increase,
            "simulation_new_margin_rate": new_margin,
        },
        "risk_events": ground_truth_events,
    }
    return {
        "risk_events": risk_events,
        "risk_evidence": risk_evidence,
        "tasks": tasks,
        "messages": messages,
        "simulation_runs": simulation_runs,
        "simulation_results": simulation_results,
    }, ground_truth


def build_scenario_support_data(master: dict) -> dict[str, list[dict]]:
    exchange_rates = []
    rate_id = 1
    for idx, month in enumerate(month_starts(START_DATE, AS_OF)):
        exchange_rates.append({
            "exchange_rate_id": rate_id,
            "month": iso(month),
            "base_currency": "USD",
            "quote_currency": "CNY",
            "average_rate": round(7.08 + 0.12 * math.sin(idx / 3), 4),
        })
        rate_id += 1
        exchange_rates.append({
            "exchange_rate_id": rate_id,
            "month": iso(month),
            "base_currency": "EUR",
            "quote_currency": "CNY",
            "average_rate": round(7.72 + 0.15 * math.cos(idx / 4), 4),
        })
        rate_id += 1

    supplier_price_tiers = []
    tier_id = 1
    for row in master["supplier_materials"]:
        for min_qty, discount in ((50, 0.02), (200, 0.05), (500, 0.08)):
            supplier_price_tiers.append({
                "supplier_price_tier_id": tier_id,
                "supplier_material_id": row["supplier_material_id"],
                "min_qty": min_qty,
                "discount_rate": discount,
                "effective_from": "2026-01-01",
                "effective_to": "2026-12-31",
            })
            tier_id += 1

    price_lock_contracts = []
    for index, row in enumerate(master["supplier_materials"][:40], 1):
        price_lock_contracts.append({
            "price_lock_contract_id": index,
            "contract_code": f"锁价-{index:04d}",
            "supplier_material_id": row["supplier_material_id"],
            "locked_price": money(float(row["quoted_price"]) * 0.98),
            "minimum_qty": max(50, float(row["minimum_order_qty"])),
            "valid_from": "2026-04-01",
            "valid_to": "2026-09-30",
            "status": "生效",
        })
    return {
        "exchange_rates": exchange_rates,
        "supplier_price_tiers": supplier_price_tiers,
        "price_lock_contracts": price_lock_contracts,
    }


def main() -> None:
    master = build_master_data()
    history = build_price_and_supplier_history(master)
    inventory = build_inventory(master)
    sales = build_sales_production_and_costs(master, history)
    procurement = build_procurement_and_quality(master, sales, history)
    delivery_finance = build_delivery_and_finance(master, sales)
    app, ground_truth = build_risks_tasks_and_simulations(master, sales, procurement, history)
    scenario_support = build_scenario_support_data(master)

    tables: dict[str, list[dict]] = {}
    for source in (master, history, sales, procurement, delivery_finance, app, scenario_support):
        for name, rows in source.items():
            if not name.startswith("_"):
                tables[name] = rows
    tables["inventory_balances"] = inventory

    CSV_DIR.mkdir(parents=True, exist_ok=True)
    GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    for old_file in CSV_DIR.glob("*.csv"):
        old_file.unlink()
    for name, rows in tables.items():
        write_csv(name, rows)
    write_sqlite(tables)

    ground_truth_path = GROUND_TRUTH_DIR / "expected_results.json"
    ground_truth_path.write_text(json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "dataset": COMPANY_NAME,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "seed": SEED,
        "as_of_date": iso(AS_OF),
        "tables": {name: len(rows) for name, rows in tables.items()},
        "csv_directory": str(CSV_DIR),
        "sqlite_database": str(DB_PATH),
        "ground_truth": str(ground_truth_path),
    }
    (ROOT / "data" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
