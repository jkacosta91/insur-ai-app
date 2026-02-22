from __future__ import annotations

from typing import Any, Dict

from backend.services.normalize_commercial import normalize_commercial_report
from backend.services.normalize_suppliers import normalize_supplier_report
from backend.services.normalize_universal import normalize_universal_structure


def normalize_document(full_text: str) -> Dict[str, Any]:
    """
    Document intelligence agent:
    1) Universal semantic interpretation (schema-driven).
    2) Route to specialized parsers only when evidence is strong.
    3) Keep generic real-estate structure when no specialized shape fits.
    """
    universal = normalize_universal_structure(full_text)
    u_type = universal.get("document_type")

    if u_type == "supplier_report":
        supplier = normalize_supplier_report(full_text)
        if supplier.get("document_type") == "supplier_report":
            supplier["interpretation"] = universal
            return supplier

    if u_type == "commercial_report":
        commercial = normalize_commercial_report(full_text)
        if commercial.get("document_type") == "commercial_report":
            commercial["interpretation"] = universal
            return commercial

    # Secondary fallback to specialized parsers if universal is uncertain.
    supplier = normalize_supplier_report(full_text)
    if supplier.get("document_type") == "supplier_report" and supplier.get("suppliers"):
        supplier["interpretation"] = universal
        return supplier

    commercial = normalize_commercial_report(full_text)
    if commercial.get("document_type") == "commercial_report":
        commercial["interpretation"] = universal
        return commercial

    # Keep supplier result if it at least extracted global indicators.
    if supplier.get("document_type") == "supplier_report" and supplier.get("global_indicators"):
        supplier["interpretation"] = universal
        return supplier

    if u_type not in ("unknown", ""):
        return {
            "document_type": "real_estate_generic",
            "confidence": universal.get("confidence", 0.0),
            "suppliers": [],
            "global_indicators": {},
            "interpretation": universal,
        }

    return {
        "document_type": "unknown",
        "confidence": 0.0,
        "suppliers": [],
        "global_indicators": {},
        "interpretation": universal,
    }
