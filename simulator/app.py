"""Supplier catalogue pages served from a data file.

The data file is read on every request, so changes of prices, assortment and
mode apply from the next request without a restart (REQ-NF-027, REQ-NF-028).
"""

from __future__ import annotations

import asyncio
import json
from html import escape
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

DEFAULT_DATA_PATH = Path(__file__).resolve().parent / "data.json"

NO_PRICE_TEXT = "ціну уточнюйте"
MODES = {"normal", "unavailable", "slow", "broken", "reduced"}


def load_data(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_supplier(data: dict, slug: str) -> dict | None:
    return next((s for s in data.get("suppliers", []) if s["slug"] == slug), None)


def _grouped(price: str) -> str:
    """1250.50 -> '1 250,50'."""
    whole, _, fraction = price.partition(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return " ".join(groups) + ("," + fraction if fraction else "")


# Each layout shows the price its own way, as real supplier sites do.
def _price(item: dict, layout: str) -> str:
    price = item.get("price")
    if price is None:
        return NO_PRICE_TEXT
    if layout == "table":
        return f"{_grouped(price)} грн"
    if layout == "list":
        return f"{price.replace('.', ',')} грн"
    return f"{price} грн"


def _table(items: list[dict]) -> str:
    rows = "".join(
        "<tr>"
        f'<td class="sku">{escape(i["sku"])}</td>'
        f'<td class="name">{escape(i["name"])}</td>'
        f'<td class="unit">{escape(i["unit"])}</td>'
        f'<td class="price">{escape(_price(i, "table"))}</td>'
        "</tr>"
        for i in items
    )
    return (
        '<table class="catalog">'
        "<thead><tr><th>Артикул</th><th>Найменування</th><th>Од.</th>"
        "<th>Ціна</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _cards(items: list[dict]) -> str:
    cards = "".join(
        '<div class="card">'
        f'<h2 class="card-title">{escape(i["name"])}</h2>'
        f'<p class="card-sku">Арт. {escape(i["sku"])}</p>'
        f'<p class="card-price">{escape(_price(i, "cards"))}'
        f' / <span class="card-unit">{escape(i["unit"])}</span></p>'
        "</div>"
        for i in items
    )
    return f'<div class="catalog-grid">{cards}</div>'


def _list(items: list[dict]) -> str:
    entries = "".join(
        '<li class="product">'
        f'<span class="product-sku">{escape(i["sku"])}</span> — '
        f'<span class="product-name">{escape(i["name"])}</span>, '
        f'<span class="product-unit">{escape(i["unit"])}</span>: '
        f'<span class="product-price">{escape(_price(i, "list"))}</span>'
        "</li>"
        for i in items
    )
    return f'<ul class="catalog-list">{entries}</ul>'


def _broken(items: list[dict]) -> str:
    """A redesigned page none of the parsers knows (mode "broken")."""
    rows = "".join(
        '<div class="goods-row">'
        f"<span>{escape(i['sku'])}</span><span>{escape(i['name'])}</span>"
        "</div>"
        for i in items
    )
    return f'<section class="goods">{rows}</section>'


LAYOUTS = {"table": _table, "cards": _cards, "list": _list}


def render_page(supplier: dict, body: str) -> str:
    name = escape(supplier["name"])
    return (
        '<!doctype html><html lang="uk"><head><meta charset="utf-8">'
        f"<title>{name} — каталог</title></head>"
        f"<body><h1>{name}</h1>{body}</body></html>"
    )


def create_app(data_path: Path) -> FastAPI:
    data_path = Path(data_path)
    app = FastAPI(
        title="Імітатор постачальників",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/catalog/{slug}")
    async def catalog(slug: str) -> Response:
        supplier = find_supplier(load_data(data_path), slug)
        if supplier is None:
            return PlainTextResponse("Каталог не знайдено.", status_code=404)

        mode = supplier.get("mode", "normal")
        items = list(supplier.get("items", []))
        if mode not in MODES:
            return PlainTextResponse(f"Невідомий режим: {mode}", status_code=500)
        if mode == "unavailable":
            return PlainTextResponse("Сервіс тимчасово недоступний.", status_code=503)
        if mode == "slow":
            # Non-blocking: other suppliers are served during the delay.
            await asyncio.sleep(float(supplier.get("delay_seconds", 0)))
        if mode == "reduced":
            items = items[: int(supplier.get("keep_items", len(items)))]

        if mode == "broken":
            body = _broken(items)
        else:
            body = LAYOUTS[supplier["layout"]](items)
        return HTMLResponse(render_page(supplier, body))

    return app
