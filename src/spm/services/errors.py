"""Refusals of the services: codes and texts of the contract's error model.

The codes are the ``code`` values of ``spec/openapi.yaml``; the same codes go
into the action log as reason codes for the web interface too (REQ-NF-032).
"""

from __future__ import annotations

from dataclasses import dataclass

REQUIRED = "Поле обов'язкове."
INVALID_TYPE = "Значення має неправильний тип."
UNKNOWN_FIELD = "Невідоме поле."
READ_ONLY_FIELD = "Поле лише для читання."
MALFORMED_JSON = "Тіло запиту не є коректним JSON."
CATALOG_URL_INVALID = "Адреса каталогу має бути абсолютною адресою http або https."
PARSER_UNKNOWN = "Такого розбирача немає в списку наявних."
REFERENCE_NOT_FOUND = "Запису з таким ідентифікатором немає."
UPDATE_TIME_INVALID = "Час оновлення має формат ГГ:ХХ від 00:00 до 23:59."
THRESHOLD_OUT_OF_RANGE = "Поріг має бути від 0,1 до 50 % з кроком 0,1."
UNIT_LOCKED = "одиницю не можна змінити: є ціни або прив'язки"

VALIDATION_FAILED = "validation_failed"


@dataclass(frozen=True, slots=True)
class FieldError:
    field: str | None
    code: str
    detail: str


class ServiceError(Exception):
    code = "service_error"


class NotFound(ServiceError):
    code = "not_found"


class ValidationFailed(ServiceError):
    code = VALIDATION_FAILED

    def __init__(self, errors: list[FieldError]) -> None:
        super().__init__(errors)
        self.errors = errors


class Conflict(ServiceError):
    """A request that contradicts the state of the system (409)."""

    def __init__(self, code: str, detail: str, field: str | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.field = field

    @property
    def errors(self) -> list[FieldError]:
        if self.field is None:
            return []
        return [FieldError(self.field, self.code, self.detail)]
