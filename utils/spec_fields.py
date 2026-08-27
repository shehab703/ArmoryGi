from __future__ import annotations

from typing import Dict, List, Tuple

SPEC_FIELDS: List[Tuple[str, str]] = [
    ("weapon_name", "Weapon name"),
    ("model", "Model / type"),
    ("category", "Category"),
    ("country", "Country"),
    ("status", "Status"),
    ("range_km", "Range (km)"),
    ("speed_mach", "Speed (Mach)"),
    ("length_m", "Length (m)"),
    ("diameter_m", "Diameter (m)"),
    ("weight_kg", "Weight (kg)"),
    ("warhead_type", "Warhead type"),
    ("warhead_weight_kg", "Warhead weight (kg)"),
    ("guidance", "Guidance"),
    ("propulsion", "Propulsion"),
    ("platform", "Platform"),
    ("manufacturer", "Manufacturer"),
    ("intro_year", "Introduction year"),
    ("unit_cost_usd", "Unit cost (USD)"),
    ("origin_lat", "Origin latitude"),
    ("origin_lon", "Origin longitude"),
    ("notes", "Notes"),
]

SPEC_FIELDS_AR: Dict[str, str] = {
    "weapon_name": "اسم السلاح",
    "model": "الطراز / النوع",
    "category": "الفئة",
    "country": "الدولة",
    "status": "الحالة",
    "range_km": "المدى (كم)",
    "speed_mach": "السرعة (ماخ)",
    "length_m": "الطول (م)",
    "diameter_m": "القطر (م)",
    "weight_kg": "الوزن (كغ)",
    "warhead_type": "نوع الرأس الحربي",
    "warhead_weight_kg": "وزن الرأس الحربي (كغ)",
    "guidance": "التوجيه",
    "propulsion": "الدفع",
    "platform": "المنصة",
    "manufacturer": "المصنع",
    "intro_year": "سنة الإدخال",
    "unit_cost_usd": "التكلفة (USD)",
    "origin_lat": "خط العرض",
    "origin_lon": "خط الطول",
    "notes": "ملاحظات",
}

SPEC_FIELDS_KEY = "report/spec_fields_visible"


def default_spec_keys() -> List[str]:
    return [k for k, _ in SPEC_FIELDS]


def resolve_spec_keys(settings, requested_keys: List[str] | None = None) -> List[str]:
    valid = {k for k, _ in SPEC_FIELDS}
    if requested_keys:
        picked = [k for k in requested_keys if k in valid]
        if picked:
            return picked
    if settings is not None:
        raw = settings.value(SPEC_FIELDS_KEY, "", str)
        if isinstance(raw, str) and raw.strip():
            parsed = [x.strip() for x in raw.split(",") if x.strip()]
            parsed = [k for k in parsed if k in valid]
            if parsed:
                return parsed
    return default_spec_keys()


def save_spec_keys(settings, keys: List[str]) -> None:
    if settings is None:
        return
    valid = {k for k, _ in SPEC_FIELDS}
    cleaned = [k for k in keys if k in valid]
    settings.setValue(SPEC_FIELDS_KEY, ",".join(cleaned))

