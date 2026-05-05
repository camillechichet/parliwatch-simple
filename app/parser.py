import re
from datetime import datetime, timedelta


def extract_amendment_numbers(text: str) -> list[str]:
    if not text:
        return []
    matches = re.findall(r"\b\d+\b", text)
    return matches


def compute_tracking(current_list: list[str], target: str, minutes_per_amendment: float) -> dict:
    target = str(target).strip()

    if not target:
        return {
            "found": False,
            "remaining_before": None,
            "eta_minutes": None,
            "eta_time": None,
        }

    cleaned = [str(x).strip() for x in current_list if str(x).strip()]

    if target not in cleaned:
        return {
            "found": False,
            "remaining_before": None,
            "eta_minutes": None,
            "eta_time": None,
        }

    remaining_before = cleaned.index(target)
    eta_minutes = remaining_before * minutes_per_amendment
    eta_time = (datetime.now() + timedelta(minutes=eta_minutes)).strftime("%H:%M")

    return {
        "found": True,
        "remaining_before": remaining_before,
        "eta_minutes": eta_minutes,
        "eta_time": eta_time,
    }
