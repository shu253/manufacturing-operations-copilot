# Manufacturing Operations Copilot

A trustworthy operations analysis and decision-execution copilot for discrete manufacturing. It sits above existing ERP, MES, procurement, inventory and finance systems, combining deterministic business calculations, Dify workflow orchestration, a React management cockpit and a Feishu action loop.

> Portfolio and technical prototype only. All companies, people and business data are fictional or sanitized. This repository does not represent a production customer deployment.

## Highlights

- 12 management modules covering order risk, shortages, procurement, production, cost, quotation, receivables and reports.
- 15 allow-listed AI tools exposed through FastAPI.
- Multi-step evidence chains linked only by explicit business identifiers.
- Numeric grounding, calculation IDs, formula versions and source evidence.
- Feishu identity mapping, one-time confirmation, acknowledgement, feedback and retry outbox.
- Python/FastAPI backend, React/TypeScript frontend and automated CI.

## Architecture

```text
ERP / MES / Procurement / Inventory / Finance
                     ↓
       Deterministic Business Engine
                     ↓
          Controlled FastAPI Tools
                     ↓
          Dify Workflow + LLM
                     ↓
       React Web + Feishu Action Loop
```

See the [Chinese README](README.md) for setup, screenshots and detailed documentation.

