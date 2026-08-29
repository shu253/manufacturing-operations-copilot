# 阶段三业务计算引擎

## 运行要求

- Python 3.10及以上。
- Pydantic 2.x。
- 默认只读数据库：`data/huadong_jinggong_demo.sqlite3`。

引擎不依赖FastAPI和大模型，不修改采购、订单、库存或财务数据。

## 推荐调用方式

```python
from business_engine import default_engine

engine = default_engine()

risk = engine.calculate_order_risk("销售-20260718-01", "2026-08-05")
print(risk.to_dict())

scenario = engine.run_procurement_scenario(
    "material_price_change",
    {
        "order_code": "销售-20260718-01",
        "material_code": "物料-0001",
        "change_rate": 0.08,
    },
    "2026-08-05",
)
print(scenario.to_dict())
```

`BusinessEngine`是供阶段四FastAPI包装的稳定门面；底层业务函数继续支持注入其他Repository，以便后续适配PostgreSQL。

## 业务域

- `fulfillment.py`：齐套率、缺料、采购迟交、生产进度和订单风险。
- `procurement.py`：采购价格异常、供应商指标、综合评分和替代推荐。
- `costing.py`：订单成本、报价和七类采购情景模拟。
- `finance.py`：应收账款风险和自动经营早报。
- `core.py`：只读Repository、Pydantic结果模型、金额精度和统一异常。
- `service.py`：对外业务门面。

## 自动测试

```powershell
python scripts/run_business_engine_tests.py
```

运行后会生成`data/business_engine_test_report.json`。
