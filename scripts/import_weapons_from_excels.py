import re
import sqlite3
from pathlib import Path

import pandas as pd


EXCEL_FILES = [
    Path(r"c:\Users\HGJJH\Documents\WP\Unified US & Israeli Weapons Database.xlsx"),
    Path(r"c:\Users\HGJJH\Documents\WP\Unified US & Israeli Weapons Database (Part 2 of 2) - English Version.xlsx"),
    Path(r"c:\Users\HGJJH\Documents\WP\جدول موحد لأسلحة الولايات المتحدة وإسرائيل (الجزء 1 من 2).xlsx"),
    Path(r"c:\Users\HGJJH\Documents\WP\جدول موحد لأسلحة الولايات المتحدة وإسرائيل (الجزء 2 من 2) - النسخة العربية.xlsx"),
]

DB_PATH = Path.home() / ".armorygis" / "armory.db"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "database" / "schema.sql"


def parse_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not m:
        return None
    return float(m.group(0))


def parse_speed(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == "nan":
        return None
    mach = re.search(r"mach\s*([0-9]+(?:\.[0-9]+)?)", text)
    if mach:
        return float(mach.group(1))
    mps = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*m/s", text)
    if mps:
        # Rough conversion around sea level.
        return round(float(mps.group(1)) / 343.0, 3)
    return parse_number(text)


def normalize_status(value):
    text = str(value or "").strip().lower()
    if "oper" in text:
        return "operational"
    if "develop" in text:
        return "development"
    if "test" in text:
        return "testing"
    if "retir" in text:
        return "retired"
    if "export" in text:
        return "export-only"
    return "operational"


def normalize_country(value):
    text = str(value or "").strip()
    low = text.lower()
    if low in {"usa", "u.s.", "u.s", "us", "united states", "united states of america", "usa/norway"}:
        return "United States", "US", "North America"
    if "israel" in low:
        return "Israel", "IL", "Middle East"
    # Import is scoped to the provided US/Israel source set.
    return None, None, None


def pick(row, keys):
    for key in keys:
        if key in row and pd.notna(row[key]):
            return row[key]
    return None


def ensure_schema(conn):
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()


def upsert_lookup(conn, table, name, extra=None):
    if not name:
        return None
    cur = conn.execute(f"SELECT id FROM {table} WHERE name = ?", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    if extra:
        cols = ", ".join(["name"] + list(extra.keys()))
        placeholders = ", ".join(["?"] * (1 + len(extra)))
        values = [name] + list(extra.values())
        cur = conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
            values,
        )
    else:
        cur = conn.execute(f"INSERT INTO {table} (name) VALUES (?)", (name,))
    return cur.lastrowid


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    ensure_schema(conn)

    inserted = 0
    updated = 0
    skipped = 0

    for file_path in EXCEL_FILES:
        if not file_path.exists():
            print(f"Skipping missing file: {file_path}")
            continue

        df = pd.read_excel(file_path)
        for _, row in df.iterrows():
            model = str(pick(row, ["Model"])).strip() if pd.notna(pick(row, ["Model"])) else ""
            weapon_name = str(pick(row, ["Weapon Name", "اسم السلاح"])).strip() if pd.notna(pick(row, ["Weapon Name", "اسم السلاح"])) else ""
            if not model or model.lower() == "nan":
                skipped += 1
                continue
            if not weapon_name or weapon_name.lower() == "nan":
                weapon_name = model

            country_name_raw = pick(row, ["Country", "الدولة"])
            country_name, iso_code, region = normalize_country(country_name_raw)
            if not country_name:
                skipped += 1
                continue

            category_name = str(pick(row, ["Weapon Category", "فئة السلاح"]) or "").strip()
            guidance_name = str(pick(row, ["Guidance System", "نظام التوجيه"]) or "").strip()
            propulsion_name = str(pick(row, ["Propulsion", "نوع الدفع"]) or "").strip()

            country_id = upsert_lookup(
                conn,
                "countries",
                country_name,
                {"iso_code": iso_code, "region": region},
            )
            category_id = upsert_lookup(conn, "categories", category_name or "Uncategorized")
            guidance_id = upsert_lookup(conn, "guidance_types", guidance_name) if guidance_name else None
            propulsion_id = upsert_lookup(conn, "propulsion_types", propulsion_name) if propulsion_name else None

            notes_parts = []
            for key in ["Variants", "Sources", "Targets", "المتغيرات/النسخ", "المصادر", "الأهداف"]:
                value = pick(row, [key])
                if value is not None and pd.notna(value):
                    v = str(value).strip()
                    if v and v.lower() != "nan":
                        notes_parts.append(f"{key}: {v}")
            notes = " | ".join(notes_parts) if notes_parts else None

            payload = {
                "model": model,
                "weapon_name": weapon_name,
                "category_id": category_id,
                "country_id": country_id,
                "length_m": parse_number(pick(row, ["Length", "الطول"])),
                "diameter_m": parse_number(pick(row, ["Diameter", "القطر"])),
                "weight_kg": parse_number(pick(row, ["Weight", "الوزن"])),
                "warhead_type": str(pick(row, ["Warhead Type", "نوع الرأس الحربي"]) or "").strip() or None,
                "warhead_weight_kg": parse_number(pick(row, ["Warhead Weight", "وزن الرأس الحربي"])),
                "range_km": parse_number(pick(row, ["Range", "المدى"])),
                "speed_mach": parse_speed(pick(row, ["Speed", "السرعة"])),
                "guidance_id": guidance_id,
                "propulsion_id": propulsion_id,
                "platform": str(pick(row, ["Platform", "المنصة/طريقة الإطلاق"]) or "").strip() or None,
                "status": normalize_status(pick(row, ["Status", "الحالة"])),
                "manufacturer": str(pick(row, ["Manufacturer", "الشركة المصنعة"]) or "").strip() or None,
                "intro_year": int(parse_number(pick(row, ["Introduction Year", "سنة الدخول"]))) if parse_number(pick(row, ["Introduction Year", "سنة الدخول"])) else None,
                "unit_cost_usd": parse_number(pick(row, ["Unit Cost", "تكلفة الوحدة"])),
                "notes": notes,
            }

            existing = conn.execute(
                "SELECT id FROM weapons WHERE model = ? AND country_id = ?",
                (model, country_id),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE weapons
                    SET weapon_name=?, category_id=?, length_m=?, diameter_m=?, weight_kg=?, warhead_type=?,
                        warhead_weight_kg=?, range_km=?, speed_mach=?, guidance_id=?, propulsion_id=?,
                        platform=?, status=?, manufacturer=?, intro_year=?, unit_cost_usd=?, notes=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (
                        payload["weapon_name"],
                        payload["category_id"],
                        payload["length_m"],
                        payload["diameter_m"],
                        payload["weight_kg"],
                        payload["warhead_type"],
                        payload["warhead_weight_kg"],
                        payload["range_km"],
                        payload["speed_mach"],
                        payload["guidance_id"],
                        payload["propulsion_id"],
                        payload["platform"],
                        payload["status"],
                        payload["manufacturer"],
                        payload["intro_year"],
                        payload["unit_cost_usd"],
                        payload["notes"],
                        existing[0],
                    ),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO weapons (
                        model, weapon_name, category_id, country_id, length_m, diameter_m, weight_kg,
                        warhead_type, warhead_weight_kg, range_km, speed_mach, guidance_id, propulsion_id,
                        platform, status, manufacturer, intro_year, unit_cost_usd, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload["model"],
                        payload["weapon_name"],
                        payload["category_id"],
                        payload["country_id"],
                        payload["length_m"],
                        payload["diameter_m"],
                        payload["weight_kg"],
                        payload["warhead_type"],
                        payload["warhead_weight_kg"],
                        payload["range_km"],
                        payload["speed_mach"],
                        payload["guidance_id"],
                        payload["propulsion_id"],
                        payload["platform"],
                        payload["status"],
                        payload["manufacturer"],
                        payload["intro_year"],
                        payload["unit_cost_usd"],
                        payload["notes"],
                    ),
                )
                inserted += 1

        conn.commit()
        print(f"Processed: {file_path.name}")

    total_weapons = conn.execute("SELECT COUNT(*) FROM weapons").fetchone()[0]
    total_countries = conn.execute("SELECT COUNT(*) FROM countries").fetchone()[0]
    total_categories = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    conn.commit()
    conn.close()

    print("Import complete")
    print(f"Inserted: {inserted}")
    print(f"Updated: {updated}")
    print(f"Skipped: {skipped}")
    print(f"Weapons in DB: {total_weapons}")
    print(f"Countries in DB: {total_countries}")
    print(f"Categories in DB: {total_categories}")
    print(f"DB path: {DB_PATH}")


if __name__ == "__main__":
    main()

