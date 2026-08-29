-- 华东某精工装备有限公司：订单交付与利润预警助手
-- PostgreSQL 15+ 数据模型
-- 所有业务数据均为虚构演示数据。

CREATE TABLE IF NOT EXISTS companies (
    company_id BIGINT PRIMARY KEY,
    company_code VARCHAR(32) NOT NULL UNIQUE,
    company_name VARCHAR(200) NOT NULL,
    industry VARCHAR(100) NOT NULL,
    headquarters_city VARCHAR(50),
    currency CHAR(3) NOT NULL DEFAULT 'CNY',
    timezone VARCHAR(50) NOT NULL DEFAULT 'Asia/Shanghai',
    is_synthetic BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS plants (
    plant_id BIGINT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    plant_code VARCHAR(32) NOT NULL UNIQUE,
    plant_name VARCHAR(100) NOT NULL,
    city VARCHAR(50),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS departments (
    department_id BIGINT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    department_code VARCHAR(32) NOT NULL,
    department_name VARCHAR(100) NOT NULL,
    UNIQUE (company_id, department_code)
);

CREATE TABLE IF NOT EXISTS employees (
    employee_id BIGINT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    employee_code VARCHAR(32) NOT NULL UNIQUE,
    employee_name VARCHAR(100) NOT NULL,
    department_id BIGINT NOT NULL REFERENCES departments(department_id),
    job_title VARCHAR(100),
    plant_id BIGINT REFERENCES plants(plant_id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id BIGINT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    customer_code VARCHAR(32) NOT NULL UNIQUE,
    customer_name VARCHAR(200) NOT NULL,
    city VARCHAR(50),
    industry VARCHAR(100),
    credit_days INTEGER NOT NULL CHECK (credit_days >= 0),
    customer_level VARCHAR(8),
    is_synthetic BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id BIGINT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    supplier_code VARCHAR(32) NOT NULL UNIQUE,
    supplier_name VARCHAR(200) NOT NULL,
    city VARCHAR(50),
    supplier_category VARCHAR(100),
    payment_terms_days INTEGER NOT NULL CHECK (payment_terms_days >= 0),
    risk_level VARCHAR(16),
    is_synthetic BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS warehouses (
    warehouse_id BIGINT PRIMARY KEY,
    plant_id BIGINT NOT NULL REFERENCES plants(plant_id),
    warehouse_code VARCHAR(32) NOT NULL UNIQUE,
    warehouse_name VARCHAR(100) NOT NULL,
    warehouse_type VARCHAR(32) NOT NULL
);

CREATE TABLE IF NOT EXISTS materials (
    material_id BIGINT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    material_code VARCHAR(32) NOT NULL UNIQUE,
    material_name VARCHAR(200) NOT NULL,
    material_category VARCHAR(100) NOT NULL,
    unit VARCHAR(20) NOT NULL,
    standard_price NUMERIC(18,2) NOT NULL CHECK (standard_price >= 0),
    safety_stock NUMERIC(18,4) NOT NULL DEFAULT 0,
    critical_level VARCHAR(16) NOT NULL,
    default_lead_time_days INTEGER NOT NULL CHECK (default_lead_time_days >= 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS products (
    product_id BIGINT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    product_code VARCHAR(32) NOT NULL UNIQUE,
    product_name VARCHAR(200) NOT NULL,
    product_family VARCHAR(100),
    unit VARCHAR(20) NOT NULL,
    standard_labor_hours NUMERIC(18,4) NOT NULL DEFAULT 0,
    standard_outsource_cost NUMERIC(18,2) NOT NULL DEFAULT 0,
    standard_overhead_rate NUMERIC(10,4) NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS bom_headers (
    bom_id BIGINT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    product_id BIGINT NOT NULL REFERENCES products(product_id),
    bom_version VARCHAR(32) NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    status VARCHAR(20) NOT NULL,
    UNIQUE (product_id, bom_version)
);

CREATE TABLE IF NOT EXISTS bom_lines (
    bom_line_id BIGINT PRIMARY KEY,
    bom_id BIGINT NOT NULL REFERENCES bom_headers(bom_id),
    material_id BIGINT NOT NULL REFERENCES materials(material_id),
    quantity_per NUMERIC(18,4) NOT NULL CHECK (quantity_per > 0),
    scrap_rate NUMERIC(10,4) NOT NULL DEFAULT 0 CHECK (scrap_rate >= 0),
    is_critical BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (bom_id, material_id)
);

CREATE TABLE IF NOT EXISTS supplier_materials (
    supplier_material_id BIGINT PRIMARY KEY,
    supplier_id BIGINT NOT NULL REFERENCES suppliers(supplier_id),
    material_id BIGINT NOT NULL REFERENCES materials(material_id),
    supplier_material_code VARCHAR(64),
    quoted_price NUMERIC(18,2) NOT NULL,
    lead_time_days INTEGER NOT NULL,
    minimum_order_qty NUMERIC(18,4) NOT NULL DEFAULT 0,
    priority_rank INTEGER NOT NULL,
    is_approved BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (supplier_id, material_id)
);

CREATE TABLE IF NOT EXISTS material_price_history (
    price_history_id BIGINT PRIMARY KEY,
    material_id BIGINT NOT NULL REFERENCES materials(material_id),
    month DATE NOT NULL,
    average_purchase_price NUMERIC(18,2) NOT NULL,
    market_reference_price NUMERIC(18,2),
    month_over_month_rate NUMERIC(10,4),
    UNIQUE (material_id, month)
);

CREATE TABLE IF NOT EXISTS supplier_score_snapshots (
    supplier_score_id BIGINT PRIMARY KEY,
    supplier_id BIGINT NOT NULL REFERENCES suppliers(supplier_id),
    month DATE NOT NULL,
    price_score NUMERIC(8,2) NOT NULL,
    delivery_score NUMERIC(8,2) NOT NULL,
    quality_score NUMERIC(8,2) NOT NULL,
    response_score NUMERIC(8,2) NOT NULL,
    stability_score NUMERIC(8,2) NOT NULL,
    total_score NUMERIC(8,2) NOT NULL,
    supplier_grade VARCHAR(8) NOT NULL,
    UNIQUE (supplier_id, month)
);

CREATE TABLE IF NOT EXISTS sales_orders (
    sales_order_id BIGINT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    sales_order_code VARCHAR(32) NOT NULL UNIQUE,
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    plant_id BIGINT NOT NULL REFERENCES plants(plant_id),
    order_date DATE NOT NULL,
    promised_delivery_date DATE NOT NULL,
    status VARCHAR(32) NOT NULL,
    sales_owner_id BIGINT REFERENCES employees(employee_id),
    currency CHAR(3) NOT NULL DEFAULT 'CNY',
    order_amount NUMERIC(18,2) NOT NULL CHECK (order_amount >= 0),
    source_system VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS sales_order_lines (
    sales_order_line_id BIGINT PRIMARY KEY,
    sales_order_id BIGINT NOT NULL REFERENCES sales_orders(sales_order_id),
    line_no INTEGER NOT NULL,
    product_id BIGINT NOT NULL REFERENCES products(product_id),
    order_qty NUMERIC(18,4) NOT NULL CHECK (order_qty > 0),
    unit_price NUMERIC(18,2) NOT NULL,
    line_amount NUMERIC(18,2) NOT NULL,
    UNIQUE (sales_order_id, line_no)
);

CREATE TABLE IF NOT EXISTS production_orders (
    production_order_id BIGINT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    production_order_code VARCHAR(32) NOT NULL UNIQUE,
    sales_order_line_id BIGINT NOT NULL REFERENCES sales_order_lines(sales_order_line_id),
    plant_id BIGINT NOT NULL REFERENCES plants(plant_id),
    product_id BIGINT NOT NULL REFERENCES products(product_id),
    planned_qty NUMERIC(18,4) NOT NULL,
    completed_qty NUMERIC(18,4) NOT NULL DEFAULT 0,
    planned_start_date DATE NOT NULL,
    planned_finish_date DATE NOT NULL,
    actual_finish_date DATE,
    progress_rate NUMERIC(8,2) NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL
);

CREATE TABLE IF NOT EXISTS production_operations (
    production_operation_id BIGINT PRIMARY KEY,
    production_order_id BIGINT NOT NULL REFERENCES production_orders(production_order_id),
    operation_no INTEGER NOT NULL,
    operation_name VARCHAR(100) NOT NULL,
    planned_hours NUMERIC(18,4) NOT NULL,
    actual_hours NUMERIC(18,4) NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL,
    UNIQUE (production_order_id, operation_no)
);

CREATE TABLE IF NOT EXISTS production_material_requirements (
    material_requirement_id BIGINT PRIMARY KEY,
    production_order_id BIGINT NOT NULL REFERENCES production_orders(production_order_id),
    material_id BIGINT NOT NULL REFERENCES materials(material_id),
    required_date DATE NOT NULL,
    required_qty NUMERIC(18,4) NOT NULL,
    issued_qty NUMERIC(18,4) NOT NULL DEFAULT 0,
    shortage_qty NUMERIC(18,4) NOT NULL DEFAULT 0,
    is_critical BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(32) NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_balances (
    inventory_balance_id BIGINT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    plant_id BIGINT NOT NULL REFERENCES plants(plant_id),
    warehouse_id BIGINT NOT NULL REFERENCES warehouses(warehouse_id),
    material_id BIGINT NOT NULL REFERENCES materials(material_id),
    on_hand_qty NUMERIC(18,4) NOT NULL,
    allocated_qty NUMERIC(18,4) NOT NULL,
    available_qty NUMERIC(18,4) NOT NULL,
    safety_stock_qty NUMERIC(18,4) NOT NULL,
    snapshot_date DATE NOT NULL,
    UNIQUE (plant_id, warehouse_id, material_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    purchase_order_id BIGINT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    purchase_order_code VARCHAR(32) NOT NULL UNIQUE,
    supplier_id BIGINT NOT NULL REFERENCES suppliers(supplier_id),
    plant_id BIGINT NOT NULL REFERENCES plants(plant_id),
    order_date DATE NOT NULL,
    promised_delivery_date DATE NOT NULL,
    expected_delivery_date DATE NOT NULL,
    status VARCHAR(32) NOT NULL,
    buyer_id BIGINT REFERENCES employees(employee_id),
    currency CHAR(3) NOT NULL DEFAULT 'CNY',
    order_amount NUMERIC(18,2) NOT NULL,
    source_system VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
    purchase_order_line_id BIGINT PRIMARY KEY,
    purchase_order_id BIGINT NOT NULL REFERENCES purchase_orders(purchase_order_id),
    line_no INTEGER NOT NULL,
    material_id BIGINT NOT NULL REFERENCES materials(material_id),
    ordered_qty NUMERIC(18,4) NOT NULL,
    received_qty NUMERIC(18,4) NOT NULL DEFAULT 0,
    unit_price NUMERIC(18,2) NOT NULL,
    line_amount NUMERIC(18,2) NOT NULL,
    UNIQUE (purchase_order_id, line_no)
);

CREATE TABLE IF NOT EXISTS requirement_allocations (
    requirement_allocation_id BIGINT PRIMARY KEY,
    material_requirement_id BIGINT NOT NULL REFERENCES production_material_requirements(material_requirement_id),
    purchase_order_line_id BIGINT NOT NULL REFERENCES purchase_order_lines(purchase_order_line_id),
    allocated_qty NUMERIC(18,4) NOT NULL CHECK (allocated_qty > 0)
);

CREATE TABLE IF NOT EXISTS receipts (
    receipt_id BIGINT PRIMARY KEY,
    receipt_code VARCHAR(32) NOT NULL UNIQUE,
    purchase_order_id BIGINT NOT NULL REFERENCES purchase_orders(purchase_order_id),
    supplier_id BIGINT NOT NULL REFERENCES suppliers(supplier_id),
    plant_id BIGINT NOT NULL REFERENCES plants(plant_id),
    receipt_date DATE NOT NULL,
    status VARCHAR(32) NOT NULL
);

CREATE TABLE IF NOT EXISTS receipt_lines (
    receipt_line_id BIGINT PRIMARY KEY,
    receipt_id BIGINT NOT NULL REFERENCES receipts(receipt_id),
    purchase_order_line_id BIGINT NOT NULL REFERENCES purchase_order_lines(purchase_order_line_id),
    material_id BIGINT NOT NULL REFERENCES materials(material_id),
    received_qty NUMERIC(18,4) NOT NULL,
    accepted_qty NUMERIC(18,4) NOT NULL,
    rejected_qty NUMERIC(18,4) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quality_inspections (
    quality_inspection_id BIGINT PRIMARY KEY,
    inspection_code VARCHAR(32) NOT NULL UNIQUE,
    inspection_type VARCHAR(32) NOT NULL,
    supplier_id BIGINT REFERENCES suppliers(supplier_id),
    material_id BIGINT REFERENCES materials(material_id),
    production_order_id BIGINT REFERENCES production_orders(production_order_id),
    inspection_date DATE NOT NULL,
    inspected_qty NUMERIC(18,4) NOT NULL,
    accepted_qty NUMERIC(18,4) NOT NULL,
    rejected_qty NUMERIC(18,4) NOT NULL,
    result VARCHAR(32) NOT NULL,
    defect_type VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS order_cost_snapshots (
    order_cost_snapshot_id BIGINT PRIMARY KEY,
    sales_order_id BIGINT NOT NULL REFERENCES sales_orders(sales_order_id),
    snapshot_date DATE NOT NULL,
    material_cost NUMERIC(18,2) NOT NULL,
    labor_cost NUMERIC(18,2) NOT NULL,
    outsource_cost NUMERIC(18,2) NOT NULL,
    overhead_cost NUMERIC(18,2) NOT NULL,
    logistics_cost NUMERIC(18,2) NOT NULL,
    total_cost NUMERIC(18,2) NOT NULL,
    sales_revenue NUMERIC(18,2) NOT NULL,
    gross_profit NUMERIC(18,2) NOT NULL,
    gross_margin_rate NUMERIC(10,4) NOT NULL,
    cost_type VARCHAR(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS order_cost_details (
    order_cost_detail_id BIGINT PRIMARY KEY,
    order_cost_snapshot_id BIGINT NOT NULL REFERENCES order_cost_snapshots(order_cost_snapshot_id),
    cost_component VARCHAR(32) NOT NULL,
    amount NUMERIC(18,2) NOT NULL,
    calculation_basis VARCHAR(200)
);

CREATE TABLE IF NOT EXISTS quotations (
    quotation_id BIGINT PRIMARY KEY,
    quotation_code VARCHAR(32) NOT NULL UNIQUE,
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    product_id BIGINT NOT NULL REFERENCES products(product_id),
    quotation_date DATE NOT NULL,
    quantity NUMERIC(18,4) NOT NULL,
    estimated_cost NUMERIC(18,2) NOT NULL,
    target_margin_rate NUMERIC(10,4) NOT NULL,
    quoted_amount NUMERIC(18,2) NOT NULL,
    status VARCHAR(32) NOT NULL,
    converted_sales_order_id BIGINT REFERENCES sales_orders(sales_order_id)
);

CREATE TABLE IF NOT EXISTS shipments (
    shipment_id BIGINT PRIMARY KEY,
    shipment_code VARCHAR(32) NOT NULL UNIQUE,
    sales_order_id BIGINT NOT NULL REFERENCES sales_orders(sales_order_id),
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    plant_id BIGINT NOT NULL REFERENCES plants(plant_id),
    shipment_date DATE NOT NULL,
    shipment_amount NUMERIC(18,2) NOT NULL,
    status VARCHAR(32) NOT NULL
);

CREATE TABLE IF NOT EXISTS shipment_lines (
    shipment_line_id BIGINT PRIMARY KEY,
    shipment_id BIGINT NOT NULL REFERENCES shipments(shipment_id),
    sales_order_line_id BIGINT NOT NULL REFERENCES sales_order_lines(sales_order_line_id),
    product_id BIGINT NOT NULL REFERENCES products(product_id),
    shipped_qty NUMERIC(18,4) NOT NULL,
    unit_price NUMERIC(18,2) NOT NULL,
    line_amount NUMERIC(18,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id BIGINT PRIMARY KEY,
    invoice_code VARCHAR(32) NOT NULL UNIQUE,
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    sales_order_id BIGINT NOT NULL REFERENCES sales_orders(sales_order_id),
    shipment_id BIGINT NOT NULL REFERENCES shipments(shipment_id),
    invoice_date DATE NOT NULL,
    due_date DATE NOT NULL,
    invoice_amount NUMERIC(18,2) NOT NULL,
    status VARCHAR(32) NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id BIGINT PRIMARY KEY,
    payment_code VARCHAR(32) NOT NULL UNIQUE,
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    payment_date DATE NOT NULL,
    payment_amount NUMERIC(18,2) NOT NULL,
    payment_method VARCHAR(32) NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_allocations (
    payment_allocation_id BIGINT PRIMARY KEY,
    payment_id BIGINT NOT NULL REFERENCES payments(payment_id),
    invoice_id BIGINT NOT NULL REFERENCES invoices(invoice_id),
    allocated_amount NUMERIC(18,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS ar_snapshots (
    ar_snapshot_id BIGINT PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    invoice_id BIGINT NOT NULL REFERENCES invoices(invoice_id),
    invoice_amount NUMERIC(18,2) NOT NULL,
    paid_amount NUMERIC(18,2) NOT NULL,
    outstanding_amount NUMERIC(18,2) NOT NULL,
    due_date DATE NOT NULL,
    overdue_days INTEGER NOT NULL,
    aging_bucket VARCHAR(20) NOT NULL,
    risk_level VARCHAR(16) NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_events (
    risk_event_id BIGINT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    risk_code VARCHAR(32) NOT NULL UNIQUE,
    risk_type VARCHAR(32) NOT NULL,
    rule_code VARCHAR(64) NOT NULL,
    entity_type VARCHAR(32) NOT NULL,
    entity_id BIGINT NOT NULL,
    entity_code VARCHAR(64) NOT NULL,
    risk_score NUMERIC(8,2) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    status VARCHAR(20) NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    summary TEXT NOT NULL,
    potential_amount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS risk_evidence (
    risk_evidence_id BIGINT PRIMARY KEY,
    risk_event_id BIGINT NOT NULL REFERENCES risk_events(risk_event_id),
    evidence_type VARCHAR(64) NOT NULL,
    source_table VARCHAR(64) NOT NULL,
    source_record_code VARCHAR(64) NOT NULL,
    evidence_value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id BIGINT PRIMARY KEY,
    risk_event_id BIGINT NOT NULL REFERENCES risk_events(risk_event_id),
    task_code VARCHAR(32) NOT NULL UNIQUE,
    task_title VARCHAR(200) NOT NULL,
    owner_employee_id BIGINT NOT NULL REFERENCES employees(employee_id),
    due_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL,
    priority VARCHAR(16) NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    message_id BIGINT PRIMARY KEY,
    task_id BIGINT NOT NULL REFERENCES tasks(task_id),
    recipient_employee_id BIGINT NOT NULL REFERENCES employees(employee_id),
    channel VARCHAR(20) NOT NULL,
    message_title VARCHAR(200) NOT NULL,
    message_body TEXT NOT NULL,
    sent_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS simulation_runs (
    simulation_run_id BIGINT PRIMARY KEY,
    simulation_code VARCHAR(32) NOT NULL UNIQUE,
    simulation_type VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    created_by BIGINT REFERENCES employees(employee_id),
    parameter_json JSONB NOT NULL,
    status VARCHAR(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS simulation_results (
    simulation_result_id BIGINT PRIMARY KEY,
    simulation_run_id BIGINT NOT NULL REFERENCES simulation_runs(simulation_run_id),
    sales_order_id BIGINT NOT NULL REFERENCES sales_orders(sales_order_id),
    sales_order_code VARCHAR(32) NOT NULL,
    original_cost NUMERIC(18,2) NOT NULL,
    new_cost NUMERIC(18,2) NOT NULL,
    cost_increase NUMERIC(18,2) NOT NULL,
    original_margin_rate NUMERIC(10,4) NOT NULL,
    new_margin_rate NUMERIC(10,4) NOT NULL,
    margin_change NUMERIC(10,4) NOT NULL,
    recommendation TEXT
);

CREATE TABLE IF NOT EXISTS exchange_rates (
    exchange_rate_id BIGINT PRIMARY KEY,
    month DATE NOT NULL,
    base_currency CHAR(3) NOT NULL,
    quote_currency CHAR(3) NOT NULL,
    average_rate NUMERIC(18,6) NOT NULL,
    UNIQUE (month, base_currency, quote_currency)
);

CREATE TABLE IF NOT EXISTS supplier_price_tiers (
    supplier_price_tier_id BIGINT PRIMARY KEY,
    supplier_material_id BIGINT NOT NULL REFERENCES supplier_materials(supplier_material_id),
    min_qty NUMERIC(18,4) NOT NULL,
    discount_rate NUMERIC(10,4) NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    UNIQUE (supplier_material_id, min_qty, effective_from)
);

CREATE TABLE IF NOT EXISTS price_lock_contracts (
    price_lock_contract_id BIGINT PRIMARY KEY,
    contract_code VARCHAR(32) NOT NULL UNIQUE,
    supplier_material_id BIGINT NOT NULL REFERENCES supplier_materials(supplier_material_id),
    locked_price NUMERIC(18,2) NOT NULL,
    minimum_qty NUMERIC(18,4) NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE NOT NULL,
    status VARCHAR(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_conversations (
    conversation_id VARCHAR(128) PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    role VARCHAR(32) NOT NULL,
    model_provider VARCHAR(64) NOT NULL,
    model_name VARCHAR(128) NOT NULL,
    workflow_version VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_messages (
    message_id VARCHAR(128) PRIMARY KEY,
    conversation_id VARCHAR(128) NOT NULL REFERENCES ai_conversations(conversation_id),
    trace_id VARCHAR(128) NOT NULL,
    message_role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    intent VARCHAR(64),
    model_provider VARCHAR(64),
    model_name VARCHAR(128),
    workflow_version VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    grounding_status VARCHAR(32),
    token_input BIGINT,
    token_output BIGINT,
    token_total BIGINT,
    model_cost NUMERIC(18,6),
    model_cost_currency VARCHAR(16),
    payload_json JSONB,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_tool_calls (
    ai_tool_call_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    trace_id VARCHAR(128) NOT NULL,
    message_id VARCHAR(128),
    tool_name VARCHAR(64) NOT NULL,
    input_json JSONB NOT NULL,
    output_json JSONB,
    status VARCHAR(32) NOT NULL,
    duration_ms BIGINT NOT NULL,
    calculation_id VARCHAR(128),
    sources_json JSONB,
    error_text TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_confirmations (
    token_hash VARCHAR(64) PRIMARY KEY,
    conversation_id VARCHAR(128) NOT NULL REFERENCES ai_conversations(conversation_id),
    action_type VARCHAR(64) NOT NULL,
    payload_json JSONB NOT NULL,
    preview_json JSONB NOT NULL,
    status VARCHAR(32) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    confirmed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS agent_identity_bindings (
    binding_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(employee_id),
    feishu_open_id VARCHAR(128) NOT NULL UNIQUE,
    access_role VARCHAR(32) NOT NULL,
    department_id BIGINT REFERENCES departments(department_id),
    plant_id BIGINT REFERENCES plants(plant_id),
    can_use_agent BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS outbound_notifications (
    notification_id VARCHAR(128) PRIMARY KEY,
    message_id BIGINT NOT NULL REFERENCES messages(message_id),
    recipient_employee_id BIGINT NOT NULL REFERENCES employees(employee_id),
    recipient_open_id VARCHAR(128) NOT NULL,
    channel VARCHAR(32) NOT NULL,
    title VARCHAR(200) NOT NULL,
    body TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    external_message_id VARCHAR(128),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    sent_at TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ,
    feedback_text TEXT,
    feedback_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ai_operation_audit (
    operation_audit_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    trace_id VARCHAR(128) NOT NULL,
    actor_open_id VARCHAR(128),
    actor_role VARCHAR(32),
    action_type VARCHAR(64) NOT NULL,
    target_type VARCHAR(64),
    target_id VARCHAR(128),
    status VARCHAR(32) NOT NULL,
    request_json JSONB,
    result_json JSONB,
    error_text TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sales_orders_delivery ON sales_orders(status, promised_delivery_date);
CREATE INDEX IF NOT EXISTS idx_requirements_shortage ON production_material_requirements(status, material_id, required_date);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_delivery ON purchase_orders(status, expected_delivery_date);
CREATE INDEX IF NOT EXISTS idx_risk_events_entity ON risk_events(entity_type, entity_id, status);
CREATE INDEX IF NOT EXISTS idx_ar_overdue ON ar_snapshots(risk_level, overdue_days);
CREATE INDEX IF NOT EXISTS idx_supplier_scores_month ON supplier_score_snapshots(month, total_score DESC);
CREATE INDEX IF NOT EXISTS idx_ai_tool_calls_trace ON ai_tool_calls(trace_id, ai_tool_call_id);
CREATE INDEX IF NOT EXISTS idx_agent_bindings_employee ON agent_identity_bindings(employee_id, is_active);
CREATE INDEX IF NOT EXISTS idx_outbound_notifications_status ON outbound_notifications(status, created_at);
CREATE INDEX IF NOT EXISTS idx_operation_audit_trace ON ai_operation_audit(trace_id, operation_audit_id);

CREATE OR REPLACE VIEW v_order_profit AS
SELECT
    so.sales_order_id,
    so.sales_order_code,
    so.customer_id,
    so.promised_delivery_date,
    so.status,
    c.total_cost,
    c.sales_revenue,
    c.gross_profit,
    c.gross_margin_rate
FROM sales_orders so
JOIN order_cost_snapshots c ON c.sales_order_id = so.sales_order_id;

CREATE OR REPLACE VIEW v_order_risk_summary AS
SELECT
    entity_id AS sales_order_id,
    entity_code AS sales_order_code,
    SUM(risk_score) AS total_risk_score,
    MAX(potential_amount) AS potential_amount,
    STRING_AGG(summary, '；' ORDER BY risk_event_id) AS risk_reasons,
    COUNT(*) AS risk_count
FROM risk_events
WHERE entity_type = 'sales_order' AND status <> '已关闭'
GROUP BY entity_id, entity_code;

CREATE OR REPLACE VIEW v_supplier_latest_score AS
SELECT DISTINCT ON (supplier_id)
    supplier_id,
    month,
    price_score,
    delivery_score,
    quality_score,
    response_score,
    stability_score,
    total_score,
    supplier_grade
FROM supplier_score_snapshots
ORDER BY supplier_id, month DESC;

CREATE OR REPLACE VIEW v_ar_risk AS
SELECT
    customer_id,
    SUM(outstanding_amount) AS outstanding_amount,
    MAX(overdue_days) AS max_overdue_days,
    COUNT(*) FILTER (WHERE outstanding_amount > 0) AS open_invoice_count,
    MAX(risk_level) AS risk_level
FROM ar_snapshots
GROUP BY customer_id;
