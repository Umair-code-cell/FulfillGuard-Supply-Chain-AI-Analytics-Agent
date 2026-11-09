"""Allowlisted read-only SQLite analytics for historical Olist delivery performance.

SQL values are parameterized; permitted grouping expressions are fixed constants.
"""
from __future__ import annotations
from datetime import date
from typing import Any
from .store import connect
import re


class ToolInputError(ValueError):
    """Raise for invalid, unsafe, or unrecognized tool arguments."""


def _date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ToolInputError('Date must use YYYY-MM-DD')
    try:
        date.fromisoformat(value)

    except ValueError as exc:
        raise ToolInputError("Invalid date") from exc
    return value


BRAZIL_STATES = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF",
    "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS",
    "RO", "RR", "SC", "SP", "SE", "TO",
}


def _state(value: str | None) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{2}", value):
        raise ToolInputError(
            "State must be two uppercase letters, e.g. SP"
        )

    if value not in BRAZIL_STATES:
        raise ToolInputError(
            f"Unknown Brazilian state code: {value}"
        )

    return value


def _period(start: str, end: str) -> tuple[str, str]:
    start, end = _date(start), _date(end)
    if start>end:
        raise ToolInputError("Start date cannot be after end date")

    return start, end

def _where(start: str, end: str, state: str | None):
    start, end = _period(start, end)
    state = _state(state)

    clause = """
        o.order_status = 'delivered'
        AND date(o.order_purchase_timestamp) BETWEEN ? AND ?
        AND o.order_delivered_customer_date IS NOT NULL
        AND o.order_estimated_delivery_date IS NOT NULL
    """

    params = [start, end]

    if state is not None:
        clause += " AND c.customer_state = ?"
        params.append(state)

    return clause, params

def delivery_kpis(start: str, end: str, state: str | None = None) -> dict:
    clause, params = _where(start, end, state)

    sql = f"""
        SELECT
            COUNT(*) AS delivered_orders,

            COALESCE(SUM(
                CASE
                    WHEN date(o.order_delivered_customer_date) >
                         date(o.order_estimated_delivery_date)
                    THEN 1 ELSE 0
                END
            ), 0) AS late_orders,

            ROUND(100.0 * AVG(
                CASE
                    WHEN date(o.order_delivered_customer_date) >
                         date(o.order_estimated_delivery_date)
                    THEN 1.0 ELSE 0.0
                END
            ), 2) AS late_rate_pct,

            ROUND(AVG(
                julianday(o.order_delivered_customer_date) -
                julianday(o.order_purchase_timestamp)
            ), 2) AS avg_delivery_days

        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        WHERE {clause}
    """

    with connect() as con:
        result = dict(con.execute(sql, params).fetchone())

    return {
        "metric_definition": (
            "Late = actual delivery after estimated delivery; "
            "purchase-date cohort; delivered orders with known dates"
        ),
        "filters": {
            "start": start,
            "end": end,
            "customer_state": state
        },
        "result": result,
        "evidence_source": ["orders", "customers"]
    }


def compare_periods(
    current_start: str,
    current_end: str,
    previous_start: str,
    previous_end: str,
    state: str | None = None
) -> dict:

    current = delivery_kpis(current_start, current_end, state)
    previous = delivery_kpis(previous_start, previous_end, state)

    current_rate = current["result"]["late_rate_pct"]
    previous_rate = previous["result"]["late_rate_pct"]

    if current_rate is None or previous_rate is None:
        delta = None
    else:
        delta = round(current_rate - previous_rate, 2)

    return {
        "current": current,
        "previous": previous,
        "late_rate_delta_pp": delta,
        "caveat": "Descriptive comparison, not proof of causality."
    }


def breakdown(
    start: str,
    end: str,
    dimension: str = "customer_state",
    state: str | None = None,
    limit: int = 10
) -> dict:

    clause, params = _where(start, end, state)

    fields = {
        "customer_state": "c.customer_state",
        "purchase_month": "substr(o.order_purchase_timestamp, 1, 7)",
        "seller_state": "s.seller_state"
    }

    if dimension not in fields:
        raise ToolInputError("Invalid breakdown dimension")

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ToolInputError("Limit must be an integer between 1 and 20")

    expr = fields[dimension]

    if dimension == "seller_state":
        joins = """
            JOIN (
                SELECT DISTINCT order_id, seller_id
                FROM order_items
            ) oi ON oi.order_id = o.order_id
            JOIN sellers s ON oi.seller_id = s.seller_id
        """
        unit = "order-seller pair"
    else:
        joins = ""
        unit = "order"

    sql = f"""
        SELECT
            {expr} AS segment,
            COUNT(*) AS delivered_count,

            SUM(
                CASE WHEN date(o.order_delivered_customer_date) >
                          date(o.order_estimated_delivery_date)
                     THEN 1 ELSE 0 END
            ) AS late_count,

            ROUND(100.0 * AVG(
                CASE WHEN date(o.order_delivered_customer_date) >
                          date(o.order_estimated_delivery_date)
                     THEN 1.0 ELSE 0.0 END
            ), 2) AS late_rate_pct

        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        {joins}
        WHERE {clause}
        GROUP BY {expr}
        ORDER BY late_count DESC, segment
        LIMIT ?
    """

    with connect() as con:
        rows = [
            dict(row)
            for row in con.execute(sql, params + [limit]).fetchall()
        ]

    return {
        "dimension": dimension,
        "unit": unit,
        "filters": {
            "start": start,
            "end": end,
            "customer_state": state
        },
        "rows": rows,
        "evidence_source": ["orders", "customers"]
            + (["order_items", "sellers"] if joins else []),
        "caveat": "Associations do not establish causality."
    }

def inspect_order(order_id: str) -> dict:

    if not isinstance(order_id, str) or not re.fullmatch(r"[0-9a-f]{32}", order_id):
        raise ToolInputError(
            "Order ID must be a 32-character lowercase hexadecimal string"
        )

    sql = """
        SELECT
            o.order_id,
            o.order_status,
            o.order_purchase_timestamp,
            o.order_delivered_customer_date,
            o.order_estimated_delivery_date,
            c.customer_state
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        WHERE o.order_id = ?
    """

    with connect() as con:
        row = con.execute(sql, (order_id,)).fetchone()

    return {
        "order": dict(row) if row else None,
        "evidence_source": ["orders", "customers"]
    }

def schema_info() -> dict:
    return {
        "dataset": "Olist Brazilian E-Commerce (2016–2018; anonymized)",
        "available_tools": list(TOOL_FUNCTIONS.keys()),
        "time_basis": "Purchase date, not delivery date",
        "interpretation": "Historical data. Correlation does not prove causation."
    }
def _spec(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False
            }
        }
    }


DAY = {"type": "string", "description": "Date in YYYY-MM-DD format"}
STATE = {"type": "string", "description": "Two uppercase letters, e.g. SP"}

TOOL_SPECS = [
    _spec(
        "delivery_kpis",
        "Calculate delivery performance for a period",
        {"start": DAY, "end": DAY, "state": STATE},
        ["start", "end"]
    ),
    _spec(
        "compare_periods",
        "Compare delivery performance between two periods",
        {
            "current_start": DAY,
            "current_end": DAY,
            "previous_start": DAY,
            "previous_end": DAY,
            "state": STATE
        },
        ["current_start", "current_end", "previous_start", "previous_end"]
    ),
    _spec(
        "breakdown",
        "Analyze late deliveries by segment",
        {
            "start": DAY,
            "end": DAY,
            "dimension": {
                "type": "string",
                "enum": ["customer_state", "purchase_month", "seller_state"]
            },
            "state": STATE,
            "limit": {"type": "integer", "minimum": 1, "maximum": 20}
        },
        ["start", "end"]
    ),
    _spec(
        "inspect_order",
        "Retrieve information about an order",
        {"order_id": {"type": "string"}},
        ["order_id"]
    ),
    _spec(
        "schema_info",
        "Explain available tools and dataset limitations",
        {},
        []
    )
]

TOOL_FUNCTIONS = {
    'delivery_kpis': delivery_kpis,
    'compare_periods': compare_periods,
    'breakdown': breakdown,
    'inspect_order': inspect_order,
    'schema_info': schema_info,
}



def execute_tool(name: str, args: dict) -> dict:
    if name not in TOOL_FUNCTIONS:
        raise ToolInputError("Unknown tool")

    if not isinstance(args, dict):
        raise ToolInputError("Tool arguments must be an object")

    try:
        return TOOL_FUNCTIONS[name](**args)
    except TypeError as exc:
        raise ToolInputError("Incorrect tool arguments") from exc
