from __future__ import annotations

from typing import Literal
from pydantic import BaseModel


class ReportRequest(BaseModel):
    report_type: Literal["pdf", "xlsx"]
