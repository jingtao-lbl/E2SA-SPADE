"""Concrete per-dataset adapters (one BaseAdapter subclass per source).

Each adapter owns parse_to_schema + the variables it `serves`. Connector-backed
adapters (Option C) also set `data_center` and delegate `fetch` to their
connector in `e2sa/data/connectors/`. Adapters are registered in
`e2sa/data/registry.py`. The shared contract is `e2sa/data/base.py`.
"""
