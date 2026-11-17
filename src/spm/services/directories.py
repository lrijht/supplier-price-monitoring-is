"""Directories of suppliers and materials, supplier items and links.

REQ-F-007…REQ-F-015, REQ-F-048, REQ-F-050, REQ-F-057, REQ-F-069. The web
interface and the API call the same functions (REQ-NF-031); nothing here knows
about HTTP.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from spm.services.actions import ActionRecorder, Actor
from spm.services.errors import (
    CATALOG_URL_INVALID,
    PARSER_UNKNOWN,
    REFERENCE_NOT_FOUND,
    REQUIRED,
    UNIT_LOCKED,
    Conflict,
    FieldError,
    NotFound,
    ServiceError,
    ValidationFailed,
)
from spm.services.ordering import Page, matches, paginate, sort_by
from spm.storage import Database, repositories, updates
from spm.storage.repositories import MaterialRow, SupplierItemRow

# Rows of storage are the services' read models; the web interface and the API
# name them through services, not through storage.
Material = MaterialRow
SupplierItem = SupplierItemRow

SUPPLIER = "supplier"
MATERIAL = "material"
SUPPLIER_ITEM = "supplier_item"
PARSER = "parser"

SUPPLIER_FIELDS = ("name", "catalog_url", "parser", "active")
MATERIAL_FIELDS = ("name", "unit", "active")


@dataclass(frozen=True, slots=True)
class Supplier:
    id: int
    name: str
    catalog_url: str
    parser: str
    active: bool
    # The date of the last update (REQ-F-034); None — «ще не оновлювався».
    last_update_date: date | None = None


@dataclass(frozen=True, slots=True)
class LinkResult:
    item: SupplierItemRow
    material: MaterialRow
    created: bool  # a new link (not a relink or the same link again)


def _supplier(
    row: repositories.SupplierRow, last_update_date: date | None = None
) -> Supplier:
    return Supplier(
        row.id, row.name, row.catalog_url, row.parser, row.active, last_update_date
    )


def name_key(name: str) -> str:
    return name.casefold()


def normalize_unit(unit: str) -> str:
    """REQ-F-014: lower case, without dots and spaces."""
    return "".join(ch for ch in unit.lower() if ch != "." and not ch.isspace())


def _is_http_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme.lower() in ("http", "https") and bool(parts.hostname)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _activity_action(kind: str, before: bool, after: bool) -> str | None:
    if before and not after:
        return f"{kind}_deactivate"
    if after and not before:
        return f"{kind}_activate"
    return None


class Directories:
    def __init__(
        self,
        database: Database,
        recorder: ActionRecorder,
        parser_names: Callable[[], Iterable[str]],
    ) -> None:
        self._db = database
        self._record = recorder
        # Parsers live in the update component; the list is supplied when the
        # application is assembled, so services do not depend on update.
        self._parser_names = parser_names

    # --- parsers (REQ-F-007, REQ-NF-006) ------------------------------------------------

    def parsers(self) -> list[str]:
        return list(dict.fromkeys(self._parser_names()))

    # --- suppliers (REQ-F-007, REQ-F-010, REQ-F-011) ---------------------------------------

    def list_suppliers(
        self, page: int = 1, active: bool | None = None
    ) -> Page[Supplier]:
        with self._db.transaction() as conn:
            rows = repositories.all_suppliers(conn)
            dates = updates.last_update_dates(conn)
        if active is not None:
            rows = [r for r in rows if r.active is active]
        rows = sort_by(rows, lambda r: r.name)
        return paginate([_supplier(r, dates.get(r.id)) for r in rows], page)

    def get_supplier(self, supplier_id: int) -> Supplier:
        with self._db.transaction() as conn:
            row = repositories.get_supplier(conn, supplier_id)
            dates = updates.last_update_dates(conn)
        if row is None:
            raise NotFound()
        return _supplier(row, dates.get(row.id))

    def _check_supplier(
        self,
        conn: sqlite3.Connection,
        values: dict[str, Any],
        own_id: int | None,
    ) -> None:
        errors: list[FieldError] = []
        if not _text(values.get("name")):
            errors.append(FieldError("name", "required", REQUIRED))
        url = _text(values.get("catalog_url"))
        if not url:
            errors.append(FieldError("catalog_url", "required", REQUIRED))
        elif not _is_http_url(url):
            errors.append(
                FieldError("catalog_url", "catalog_url_invalid", CATALOG_URL_INVALID)
            )
        parser = values.get("parser")
        if not _text(parser):
            errors.append(FieldError("parser", "required", REQUIRED))
        elif parser not in self.parsers():
            errors.append(FieldError("parser", "parser_unknown", PARSER_UNKNOWN))
        if not isinstance(values.get("active"), bool):
            errors.append(FieldError("active", "required", REQUIRED))
        if errors:
            raise ValidationFailed(errors)
        name = _text(values["name"])
        same = repositories.find_supplier_by_name_key(conn, name_key(name))
        if same is not None and same.id != own_id:
            detail = f"Постачальник з назвою «{name}» уже є."
            raise Conflict("supplier_name_taken", detail, field="name")

    def create_supplier(
        self,
        actor: Actor,
        *,
        name: str | None,
        catalog_url: str | None,
        parser: str | None,
        active: bool | None,
    ) -> Supplier:
        values = {
            "name": name,
            "catalog_url": catalog_url,
            "parser": parser,
            "active": active,
        }
        try:
            with self._db.transaction() as conn:
                self._check_supplier(conn, values, own_id=None)
                supplier_id = repositories.insert_supplier(
                    conn,
                    name=_text(name),
                    name_key=name_key(_text(name)),
                    catalog_url=_text(catalog_url),
                    parser=str(parser),
                    active=bool(active),
                )
                created = repositories.get_supplier(conn, supplier_id)
        except ServiceError as exc:
            self._record.rejected(actor, "supplier_create", SUPPLIER, None, exc.code)
            raise
        self._record.success(actor, "supplier_create", SUPPLIER, supplier_id)
        return _supplier(created)

    def supplier_action(self, supplier_id: int, changes: dict[str, Any]) -> str:
        """Name of the action a change is: update, deactivation or activation."""
        try:
            current = self.get_supplier(supplier_id)
        except NotFound:
            return "supplier_update"
        after = changes.get("active", current.active)
        if not isinstance(after, bool):
            return "supplier_update"
        return _activity_action(SUPPLIER, current.active, after) or "supplier_update"

    def update_supplier(
        self, actor: Actor, supplier_id: int, changes: dict[str, Any]
    ) -> Supplier:
        """Change any of name, catalog_url, parser, active (others are ignored)."""
        action = self.supplier_action(supplier_id, changes)
        try:
            with self._db.transaction() as conn:
                row = repositories.get_supplier(conn, supplier_id)
                if row is None:
                    raise NotFound()
                values = {
                    "name": row.name,
                    "catalog_url": row.catalog_url,
                    "parser": row.parser,
                    "active": row.active,
                }
                values.update({k: v for k, v in changes.items() if k in values})
                self._check_supplier(conn, values, own_id=supplier_id)
                name = _text(values["name"])
                catalog_url = _text(values["catalog_url"])
                parser = str(values["parser"])
                active = bool(values["active"])
                repositories.update_supplier(
                    conn,
                    supplier_id,
                    name=name,
                    name_key=name_key(name),
                    catalog_url=catalog_url,
                    parser=parser,
                    active=active,
                )
                # REQ-F-056: activation, a new address or a new parser — the
                # next run is the first one for this supplier.
                if (
                    (active and not row.active)
                    or catalog_url != row.catalog_url
                    or parser != row.parser
                ):
                    updates.reset_supplier_feed(conn, supplier_id)
                updated = repositories.get_supplier(conn, supplier_id)
        except NotFound:
            raise
        except ServiceError as exc:
            self._record.rejected(actor, action, SUPPLIER, supplier_id, exc.code)
            raise
        self._record.success(actor, action, SUPPLIER, supplier_id)
        return _supplier(updated, self.get_supplier(supplier_id).last_update_date)

    # --- materials (REQ-F-008, REQ-F-009, REQ-F-010) ----------------------------------------

    def list_materials(
        self, page: int = 1, active: bool | None = None, q: str | None = None
    ) -> Page[MaterialRow]:
        return paginate(self.choose_materials(q, active), page)

    def choose_materials(
        self, q: str | None = None, active: bool | None = None
    ) -> list[MaterialRow]:
        """All materials matching the search, in alphabetical order (REQ-F-057)."""
        with self._db.transaction() as conn:
            rows = repositories.all_materials(conn)
        rows = [
            r
            for r in rows
            if (active is None or r.active is active) and matches(q, r.name)
        ]
        return sort_by(rows, lambda r: r.name)

    def get_material(self, material_id: int) -> MaterialRow:
        with self._db.transaction() as conn:
            row = repositories.get_material(conn, material_id)
        if row is None:
            raise NotFound()
        return row

    def _check_material(
        self,
        conn: sqlite3.Connection,
        values: dict[str, Any],
        current: MaterialRow | None,
    ) -> None:
        errors: list[FieldError] = []
        if not _text(values.get("name")):
            errors.append(FieldError("name", "required", REQUIRED))
        if not _text(values.get("unit")):
            errors.append(FieldError("unit", "required", REQUIRED))
        if not isinstance(values.get("active"), bool):
            errors.append(FieldError("active", "required", REQUIRED))
        if errors:
            raise ValidationFailed(errors)
        name = _text(values["name"])
        same = repositories.find_material_by_name_key(conn, name_key(name))
        if same is not None and (current is None or same.id != current.id):
            detail = f"Матеріал з найменуванням «{name}» уже є."
            raise Conflict("material_name_taken", detail, field="name")
        if current is not None and _text(values["unit"]) != current.unit:
            locked = current.linked_items_count > 0 or (
                repositories.material_has_daily_prices(conn, current.id)
            )
            if locked:
                raise Conflict("unit_locked", UNIT_LOCKED, field="unit")

    def create_material(
        self,
        actor: Actor,
        *,
        name: str | None,
        unit: str | None,
        active: bool | None,
    ) -> MaterialRow:
        values = {"name": name, "unit": unit, "active": active}
        try:
            with self._db.transaction() as conn:
                self._check_material(conn, values, current=None)
                material_id = repositories.insert_material(
                    conn,
                    name=_text(name),
                    name_key=name_key(_text(name)),
                    unit=_text(unit),
                    active=bool(active),
                )
                created = repositories.get_material(conn, material_id)
        except ServiceError as exc:
            self._record.rejected(actor, "material_create", MATERIAL, None, exc.code)
            raise
        self._record.success(actor, "material_create", MATERIAL, material_id)
        return created

    def material_action(self, material_id: int, changes: dict[str, Any]) -> str:
        try:
            current = self.get_material(material_id)
        except NotFound:
            return "material_update"
        after = changes.get("active", current.active)
        if not isinstance(after, bool):
            return "material_update"
        return _activity_action(MATERIAL, current.active, after) or "material_update"

    def update_material(
        self, actor: Actor, material_id: int, changes: dict[str, Any]
    ) -> MaterialRow:
        """Change any of name, unit, active (others are ignored)."""
        action = self.material_action(material_id, changes)
        try:
            with self._db.transaction() as conn:
                current = repositories.get_material(conn, material_id)
                if current is None:
                    raise NotFound()
                values = {
                    "name": current.name,
                    "unit": current.unit,
                    "active": current.active,
                }
                values.update({k: v for k, v in changes.items() if k in values})
                self._check_material(conn, values, current=current)
                name = _text(values["name"])
                repositories.update_material(
                    conn,
                    material_id,
                    name=name,
                    name_key=name_key(name),
                    unit=_text(values["unit"]),
                    active=bool(values["active"]),
                )
                if values["active"] and not current.active:  # REQ-F-051
                    updates.rebase_material_feed(conn, material_id)
                updated = repositories.get_material(conn, material_id)
        except NotFound:
            raise
        except ServiceError as exc:
            self._record.rejected(actor, action, MATERIAL, material_id, exc.code)
            raise
        self._record.success(actor, action, MATERIAL, material_id)
        return updated

    # --- supplier items and links (REQ-F-012…REQ-F-015, REQ-F-048, REQ-F-050, REQ-F-069) ---

    def list_unlinked_items(
        self, page: int = 1, q: str | None = None
    ) -> Page[SupplierItemRow]:
        with self._db.transaction() as conn:
            rows = repositories.unlinked_items(conn)
        rows = [r for r in rows if matches(q, r.sku, r.name)]
        return paginate(sort_by(rows, lambda r: r.supplier.name, lambda r: r.sku), page)

    def list_material_links(
        self, material_id: int, page: int = 1
    ) -> tuple[MaterialRow, Page[SupplierItemRow]]:
        with self._db.transaction() as conn:
            material = repositories.get_material(conn, material_id)
            if material is None:
                raise NotFound()
            rows = repositories.linked_items(conn, material_id)
        rows = sort_by(rows, lambda r: r.supplier.name, lambda r: r.sku)
        return material, paginate(rows, page)

    def get_supplier_item(self, item_id: int) -> SupplierItemRow:
        with self._db.transaction() as conn:
            row = repositories.get_supplier_item(conn, item_id)
        if row is None:
            raise NotFound()
        return row

    def link_action(self, item_id: int) -> str:
        try:
            item = self.get_supplier_item(item_id)
        except NotFound:
            return "link_create"
        return "link_change" if item.material_id is not None else "link_create"

    def record_rejected(
        self,
        actor: Actor,
        action: str,
        object_type: str,
        object_id: int | None,
        reason_code: str,
    ) -> None:
        """Record a request refused before it reached the service function
        (a body that does not match the contract)."""
        self._record.rejected(actor, action, object_type, object_id, reason_code)

    def reject_link(self, actor: Actor, item_id: int, reason_code: str) -> None:
        """Record a link request refused before it reached ``link_item``."""
        action = self.link_action(item_id)
        self._record.rejected(actor, action, SUPPLIER_ITEM, item_id, reason_code)

    def link_item(self, actor: Actor, item_id: int, material_id: int) -> LinkResult:
        """Link an item to a material or relink it to another one.

        The same material again changes nothing and writes no record.
        """
        action = self.link_action(item_id)
        try:
            with self._db.transaction() as conn:
                item = repositories.get_supplier_item(conn, item_id)
                if item is None:
                    raise NotFound()
                material = repositories.get_material(conn, material_id)
                if material is None:
                    raise ValidationFailed(
                        [
                            FieldError(
                                "material_id",
                                "reference_not_found",
                                REFERENCE_NOT_FOUND,
                            )
                        ]
                    )
                if item.material_id == material.id:
                    return LinkResult(item, material, created=False)
                self._check_link(conn, item, material)
                repositories.set_item_material(conn, item.id, material.id)
                # REQ-F-045, REQ-F-046, REQ-F-047: no feed base until "з'явився".
                updates.reset_item_feed(conn, item.id)
                linked = repositories.get_supplier_item(conn, item.id)
                material = repositories.get_material(conn, material.id)
        except NotFound:
            raise
        except ServiceError as exc:
            self._record.rejected(actor, action, SUPPLIER_ITEM, item_id, exc.code)
            raise
        self._record.success(actor, action, SUPPLIER_ITEM, item_id)
        return LinkResult(linked, material, created=item.material_id is None)

    @staticmethod
    def _check_link(
        conn: sqlite3.Connection, item: SupplierItemRow, material: MaterialRow
    ) -> None:
        if not material.active:
            raise Conflict(
                "material_inactive",
                f"Матеріал «{material.name}» деактивовано. Спершу активуйте його.",
            )
        if normalize_unit(item.unit) != normalize_unit(material.unit):
            raise Conflict(
                "link_units_differ",
                f"Одиниця позиції «{item.unit}» не збігається з одиницею матеріалу "
                f"«{material.unit}».",
            )
        other = repositories.item_of_supplier_linked_to(
            conn, material.id, item.supplier.id
        )
        if other is not None and other.id != item.id:
            raise Conflict(
                "material_supplier_already_linked",
                f"До матеріалу вже прив'язано позицію {other.sku} цього постачальника.",
            )

    def unlink_item(self, actor: Actor, item_id: int) -> int:
        """Remove the link; return the material it was linked to.

        An item without a link is «not found» (contract, operation 17).
        """
        with self._db.transaction() as conn:
            item = repositories.get_supplier_item(conn, item_id)
            if item is None or item.material_id is None:
                raise NotFound()
            repositories.set_item_material(conn, item.id, None)
            updates.reset_item_feed(conn, item.id)
        self._record.success(actor, "link_remove", SUPPLIER_ITEM, item_id)
        return item.material_id
