#!/usr/bin/env python3
"""
AI Intelligence Layer for ArmoryGIS Pro
Provides smart weapon recommendations, competitive analysis,
and intelligent behavior correction.
"""
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class SmartWeaponAnalyzer:
    """Intelligent weapon analysis with pattern matching and recommendation engine."""

    STRATEGY_PROFILES = {
        "defensive": {"priority": ["range_km", "guidance", "speed_mach"], "min_range_km": 50},
        "offensive": {"priority": ["speed_mach", "warhead_weight_kg", "range_km"], "min_speed_mach": 2.0},
        "tactical": {"priority": ["length_m", "weight_kg", "platform"], "max_weight_kg": 500},
        "strategic": {"priority": ["range_km", "warhead_weight_kg", "status"], "min_range_km": 300},
    }

    @classmethod
    def recommend_profile(cls, weapon: Dict[str, Any]) -> str:
        ranges = weapon.get("range_km", 0)
        speed = weapon.get("speed_mach", 0)
        weight = weapon.get("warhead_weight_kg", 0)
        if not ranges:
            return "tactical"
        if float(ranges) >= 300:
            return "strategic"
        if float(ranges) >= 50 and float(speed or 0) >= 2.5:
            return "defensive"
        if float(speed or 0) >= 2.0 and float(weight or 0) >= 200:
            return "offensive"
        return "tactical"

    @classmethod
    def get_recommendations(cls, weapon: Dict[str, Any]) -> List[str]:
        profile = cls.recommend_profile(weapon)
        recommendations = []
        name = weapon.get("weapon_name", "Unknown")
        if profile == "defensive":
            recommendations.append(f"{name} هو مناسب للمهام الدفاعية بمدى {weapon.get('range_km', '?')} كم.")
        elif profile == "offensive":
            recommendations.append(f"{name} يتميز بقدرة هجومية عالية مع سرعة {weapon.get('speed_mach', '?')} ماخ.")
        elif profile == "strategic":
            recommendations.append(f"{name} سلاح استراتيجي بمدى طويل يصل إلى {weapon.get('range_km', '?')} كم.")
        else:
            recommendations.append(f"{name} مناسب للمهام التكتيكية المرنة.")
        recommendations.append("يُنصح بمقارنته مع أسلحة من نفس الفئة للحصول على تحليل تنافسي كامل.")
        return recommendations


class CompetitiveIntelligenceEngine:
    """Analyzes weapon competitiveness relative to database peers."""

    @classmethod
    def competitive_score(cls, weapon: Dict[str, Any], peers: List[Dict[str, Any]]) -> float:
        if not peers:
            return 0.0
        score = 0.0
        w_range = float(weapon.get("range_km", 0) or 0)
        w_speed = float(weapon.get("speed_mach", 0) or 0)
        w_weight = float(weapon.get("warhead_weight_kg", 0) or 0)
        ranges = [float(p.get("range_km", 0) or 0) for p in peers if p.get("range_km")]
        if w_range > 0 and ranges:
            score += (w_range / max(ranges)) * 0.4
        if w_speed > 0 and peers:
            speeds = [float(p.get("speed_mach", 0) or 0) for p in peers if p.get("speed_mach")]
            if speeds:
                score += (w_speed / max(speeds)) * 0.35
        if w_weight > 0 and peers:
            weights = [float(p.get("warhead_weight_kg", 0) or 0) for p in peers if p.get("warhead_weight_kg")]
            if weights:
                score += (w_weight / max(weights)) * 0.25
        return round(min(1.0, score), 3)

    @classmethod
    def compare_weapons(cls, weapon: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "current_name": weapon.get("weapon_name"),
            "compare_name": target.get("weapon_name"),
            "range_diff_km": round(float(weapon.get("range_km", 0) or 0) - float(target.get("range_km", 0) or 0), 2),
            "speed_diff_mach": round(float(weapon.get("speed_mach", 0) or 0) - float(target.get("speed_mach", 0) or 0), 2),
            "weight_diff_kg": round(float(weapon.get("warhead_weight_kg", 0) or 0) - float(target.get("warhead_weight_kg", 0) or 0), 2),
            "advantage": "current" if float(weapon.get("range_km", 0) or 0) >= float(target.get("range_km", 0) or 0) else "compare",
            "analysis_text": "",
        }
        if result["advantage"] == "current":
            result["analysis_text"] = f"{weapon.get('weapon_name')} يتفوق في المدى على {target.get('weapon_name')} بفارق {abs(result['range_diff_km'])} كم."
        else:
            result["analysis_text"] = f"{target.get('weapon_name')} يتفوق في المدى على {weapon.get('weapon_name')} بفارق {abs(result['range_diff_km'])} كم."
        return result
