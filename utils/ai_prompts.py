from __future__ import annotations

from typing import Any


def _lang_tag(is_ar: bool) -> str:
    return "Arabic" if is_ar else "English"


def build_swot_draft_prompt(*, weapon: dict[str, Any], is_ar: bool, analyst: str, scenario: str) -> tuple[str, str]:
    lang_line = (
        "LANGUAGE (Arabic UI): Write EVERY numbered line under each heading entirely in Arabic (professional military Arabic). "
        "Use Western digits 1. 2. 3. No English prose in numbered lines; Latin allowed only for standard unit tokens if "
        "unavoidable (e.g. km, Mach, kg). Do not mix English sentences.\n"
        if is_ar
        else (
            "LANGUAGE (English UI): Write EVERY numbered line entirely in English (defense terminology). "
            "Do not use Arabic script or Arabic sentences in numbered lines.\n"
        )
    )
    header_rule = (
        "Use ONLY these exact ASCII section labels on their own lines (do not translate them):\n"
        "[STRENGTHS]\n"
        "[WEAKNESSES]\n"
        "[OPPORTUNITIES]\n"
        "[THREATS]\n"
        "[RECOMMENDATIONS]\n"
    )
    perspective = (
        "Perspective (mandatory): The weapon in the JSON block is an ADVERSARY threat system. "
        "Draft SWOT for the DEFENDER side (detect, survive, defeat/mitigate). Never write as the attacker.\n"
        "[STRENGTHS]: Defender strengths vs this weapon.\n"
        "[WEAKNESSES]: Defender gaps this weapon stresses.\n"
        "[OPPORTUNITIES]: Defender counter-options (tactics, ISR, EW, posture).\n"
        "[THREATS]: Operational risk this weapon imposes if unchecked.\n"
        "[RECOMMENDATIONS]: Short defensive priorities.\n"
    )
    system = (
        "You are a defense analyst producing a concise SWOT (defender-facing). "
        "Use ONLY facts inferable from the weapon JSON and scenario text; quote numeric fields exactly as given. "
        "Do not invent ranges, speeds, inventories, OOB, or classified detail. "
        "If a datum is absent, say so in one short clause—do not guess.\n"
        "Be brief: short sentences, no filler, no marketing tone.\n"
        f"Output language for all numbered content: {_lang_tag(is_ar)}.\n"
        f"{lang_line}"
    )
    user = (
        perspective
        + header_rule
        + "\nLENGTH: Under [STRENGTHS], [WEAKNESSES], [OPPORTUNITIES], [THREATS], and [RECOMMENDATIONS], "
        "output EXACTLY 3 numbered lines each (1. … 3.), Western numbering.\n"
        "Each line: ONE tight sentence; English UI target 6–18 words per line; Arabic UI use comparable brevity.\n\n"
        "GROUNDING (mandatory):\n"
        "- Tie each line to this weapon's record: cite at least one of range_km, speed_mach, warhead_weight_kg, guidance, "
        "platform, category, status, intro_year when present in the JSON; state 'not in data' / "
        "'غير موجود في البيانات' (Arabic UI) for missing facts instead of inventing.\n"
        "- Across the three lines of each quadrant, prefer different spec lenses where data allows.\n"
        "- Do not prefix with hyphens; numbering only.\n\n"
        f"Analyst / org: {analyst or 'n/a'}\n"
        f"Scenario / theater notes: {scenario or 'n/a'}\n\n"
        f"Adversary weapon JSON (sole source for specs):\n{weapon}\n"
    )
    return system, user


def build_weapon_notes_prompt(*, weapon: dict[str, Any], is_ar: bool, existing_notes: str) -> tuple[str, str]:
    system = (
        "You are a technical defense analyst assistant. "
        "Write operational notes that officers can scan in under a minute: numbered points, one fact or judgment per line, "
        "no filler. "
        "Ground statements in provided fields only; unknowns → one explicit 'Unclear / not in data:' numbered line—not invented figures. "
        f"Write ONLY in {_lang_tag(is_ar)}."
    )
    user = (
        "Output plain text sections (e.g. 'Role:', 'Characteristics:', 'Employment considerations:'). "
        "Within each section use numbered lines starting with '1.' '2.' etc.\n\n"
        "Weapon data:\n"
        f"{weapon}\n\n"
        "Existing notes (may be empty):\n"
        f"{existing_notes or ''}\n"
    )
    return system, user


def build_sim_analysis_prompt(*, sim_state: dict[str, Any], weapon: dict[str, Any] | None, is_ar: bool) -> tuple[str, str]:
    system = (
        "You are a tactical missile employment tutor. Assess the CURRENT simulator geometry and stated parameters only "
        "(no real-world strikes, grids, or live targeting). "
        "Be succinct, pedagogical, and conservative—avoid drama. "
        f"Write ONLY in {_lang_tag(is_ar)}."
    )
    user = (
        "Use this exact numbered structure (fill each line briefly; omit unused items with \"n/a\"):\n"
        "1. Situation summary (weapon, launch–target separation, zoom level if evident).\n"
        "2. Range / geometry implication (inside or outside nominal range based on simulator data).\n"
        "3. Time-and-space / TOF caveat (mention if speeds or profile are placeholders).\n"
        "4. Key risks or assumptions inherent to this simple model.\n"
        "5. State 3 short notional drills tied to the map—e.g. replay run, reposition target band, tighten timing/EW hygiene.\n"
        "\n"
        "Use one sentence per numbered item whenever possible.\n\n"
        f"Weapon (if any): {weapon}\n\n"
        f"Simulator state:\n{sim_state}\n"
    )
    return system, user


def build_report_assessment_prompt(
    *,
    report_kind: str,
    meta: dict[str, Any],
    weapons: list[dict[str, Any]],
    is_ar: bool,
    target_section: str,
) -> tuple[str, str]:
    system = (
        "You are a defense reporting assistant inside ArmoryGIS Pro. "
        "Do not invent facts, order-of-battle, inventories, or performance beyond what weapons data/meta allow; "
        "label gaps explicitly.\n"
        f"Write ONLY in {_lang_tag(is_ar)}."
    )
    user = (
        "Draft professional report prose for ONLY the requested section.\n"
        "Use numbered lines (1. 2. …) OR short numbered paragraphs instead of unstructured prose.\n"
        "Prefer concrete references to weapons data provided; cite missing fields explicitly.\n\n"
        f"Target section: {target_section}\n"
        f"Report kind: {report_kind}\n\n"
        "Constraints:\n"
        "- Concise briefing style; avoid repetition.\n"
        "- Do not inflate beyond what sources support.\n\n"
        f"Current report meta:\n{meta}\n\n"
        f"Weapons context (may be empty or partial):\n{weapons}\n"
    )
    return system, user

