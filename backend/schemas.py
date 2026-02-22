from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class SupplierInput(BaseModel):
    supplier_name: str
    category: Optional[str] = None
    annual_volume_eur: Optional[int] = None
    orders: Optional[int] = None
    incidents: Optional[int] = None
    avg_delay_days: Optional[int] = None
    dependency_pct: Optional[int] = None
    estimated_margin_pct: Optional[int] = None


class ExtractionInput(BaseModel):
    full_text: str = ""
    page_count: Optional[int] = None
    char_count: Optional[int] = None
    token_count: Optional[int] = None
    has_tables: Optional[bool] = None
    extraction_engine: Optional[str] = None
    quality_status: Optional[str] = None
    usable_for_analysis: Optional[bool] = None
    min_chars_required: Optional[int] = None
    ocr_applied: Optional[bool] = None
    ocr_engine: Optional[str] = None
    ocr_pages: Optional[int] = None


class NormalizeRequest(BaseModel):
    document_id: Optional[str] = None
    full_text: Optional[str] = None
    extraction: Optional[ExtractionInput] = None
    suppliers: Optional[List[SupplierInput]] = None
    document_type: Optional[str] = None
    global_indicators: Optional[Dict[str, Any]] = None
    macro_pressure: Optional[float] = None
    demand_pressure: Optional[float] = None

    @model_validator(mode="after")
    def validate_source(self) -> "NormalizeRequest":
        if self.suppliers:
            return self

        has_full_text = bool(self.full_text and self.full_text.strip())
        has_extraction_text = bool(
            self.extraction and self.extraction.full_text and self.extraction.full_text.strip()
        )
        if not (has_full_text or has_extraction_text):
            raise ValueError(
                "Provide either suppliers[] or full_text/extraction.full_text"
            )
        return self


class ForecastRequest(NormalizeRequest):
    horizon_days: int = Field(default=90, ge=30, le=180)


class DecisionsRequest(BaseModel):
    normalized: Dict[str, Any] = Field(default_factory=dict)
    model_output: Dict[str, Any] = Field(default_factory=dict)
    behavior_output: Dict[str, Any] = Field(default_factory=dict)
    forecast_output: Dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
