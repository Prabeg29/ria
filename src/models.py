import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------
# Utilities
# ---------------------------
def default_uuid() -> uuid.UUID:
    return uuid.uuid4()


def table_name_from_class(cls_name: str) -> str:
    """
    Convert CamelCase → snake_case and append 's'
    Example: Resume → resumes
    """
    return re.sub(r"(?<!^)(?=[A-Z])", "_", cls_name).lower() + "s"


# ---------------------------
# Mixins
# ---------------------------
@dataclass
class TimestampMixin:
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class SoftDeleteMixin:
    deleted_at: datetime | None = None


# ---------------------------
# Base Model
# ---------------------------
@dataclass
class BaseModel(TimestampMixin):
    id: uuid.UUID = field(default_factory=default_uuid)

    @classmethod
    def table_name(cls) -> str:
        return table_name_from_class(cls.__name__)


# ---------------------------
# Resume
# ---------------------------
@dataclass
class Resume(BaseModel, SoftDeleteMixin):
    filename: str = ""
    raw_text: str | None = None
    parsed_data: dict[str, Any] = field(default_factory=dict)
    s3_url: str | None = None
