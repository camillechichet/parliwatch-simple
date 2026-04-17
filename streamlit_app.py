import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="Suivi séance", layout="wide")

LEGISLATURE = "17"
ORGANE = "AN"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

TERMINAL_SORTS = {
    "adopté",
    "adopte",
    "rejeté",
    "rejete",
    "tombé",
    "tombe",
    "retiré",
    "retire",
    "non soutenu",
    "irrecevable",
    "irrecevable 40",
}

st.title("Suivi de séance parlementaire")
st.caption("MVP simple : amendements restants + rythme de séance")

st.sidebar.header("Paramètres")

texte_numero = st.sidebar.text_input(
    "Numéro du texte examiné",
    value="2633",
    help="Exemple : 2633",
)

amendement_suivi = st.sidebar.text_input(
    "Numéro d’amendement à suivre",
    value="18",
    help="Exemple : 18",
)

minutes_par_amendement_standard = st.sidebar.number_input(
    "Base standard (minutes par amendement)",
    min_value=1.0,
    max_value=20.0,
    value=2.0,
    step=0.5,
)

st.sidebar.markdown(
    "Cette version utilise les pages publiques et l’open data de l’Assemblée nationale."
)


def session_get(url: str) -> requests.Response:
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response


def normalize_sort(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text if text else None


def is_terminal_sort(value: Optional[str]) -> bool:
    normalized = normalize_sort(value)
    return normalized in TERMINAL_SORTS


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def extract_json_url_from_html(html: str) -> Optional[str]:
    match = re.search(
        r"https://www\.assemblee-nationale\.fr/dyn/opendata/[^\"']+\.json",
        html,
    )
    if match:
        return match.group(0)
    return None


def build_amendment_page_url(text_number: str, amend_number: int) -> str:
    return (
        f"https://www.assemblee-nationale.fr/dyn/"
        f"{LEGISLATURE}/amendements/{text_number}/{ORGANE}/{amend_number}"
    )


def safe_int(value: str) -> Optional[int]:
    try:
        return int(str(value).strip())
    except Exception:
        return None


@st.cache_data(ttl=120, show_spinner=False)
def fetch_amendment_record(text_number: str, amend_number: int) -> Optional[dict]:
    page_url = build_amendment_page_url(text_number, amend_number)

    try:
        page_response = session_get(page_url)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        return None
    except Exception:
        return None

    html = page_response.text

    if "Amendement n°" not in html and "Sous-amendement n°" not in html:
        return None

    json_url = extract_json_url_from_html(html)

    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title else f"Amendement n° {amend_number}"

    record = {
        "numero": str(amend_number),
        "numero_int": amend_number,
        "page_url": page_url,
        "json_url": json_url,
        "titre": title,
        "sort": None,
        "date_sort": None,
        "etat_source": "page_html",
    }

    if json_url:
        try:
            json_response = session_get(json_url)
            payload = json_response.json()

            amendement = payload.get("amendement", payload)

            sort_value = (
                amendement.get("sort")
                or amendement.get("sortEnSeance")
                or amendement.get("sortEnCommission")
            )

            date_sort = amendement.get("dateSort") or amendement.get("date_sort")

            identification = amendement.get("identification", {})
            numero_long = identification.get("numeroLong") or identification.get("numero")

            if numero_long:
                record["numero"] = str(numero_long)
                record["numero_int"] = safe_int(numero_long)

            record["sort"] = sort_value
            record["date_sort"] = date_sort
            record["etat_source"] = "json_opendata"

        except Exception:
            pass

    return record


@st.cache_data(ttl=120, show_spinner=False)
def load_text_amendments(
    text_number: str,
    max_scan: int = 120,
    stop_after_missing: int = 12,
) -> pd.DataFrame:
    records = []
    missing_streak = 0

    for amend_number in range(1, max_scan + 1):
        record = fetch_amendment_record(text_number, amend_number)

        if record is None:
            missing_streak += 1
            if missing_streak >= stop_after_missing:
                break
            continue

        missing_streak = 0
        records.append(record)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    if "numero_int" not in df.columns:
        df["numero_int"] = df["numero"].apply(safe_int)

    df["sort_normalized"] = df["sort"].apply(normalize_sort)
    df["terminal"] = df["sort_normalized"].apply(is_terminal_sort)
    df["date_sort_dt"] = df["date_sort"].apply(parse_iso_datetime)

    df = df.sort_values(
        by="numero_int",
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)

    return df


def compute_pace(df: pd.DataFrame, minutes: int) -> Optional[float]:
    if df.empty:
        return None

    treated = df[df["terminal"]].copy()
    treated = treated[treated["date_sort_dt"].notna()].copy()

    if treated.empty:
        return None

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=minutes)

    count = int((treated["date_sort_dt"] >= cutoff).sum())
    return round(count * (60 / minutes), 1)


def format_duration(minutes: Optional[float]) -> str:
    if minutes is None:
        return "—"

    total_minutes = int(round(minutes))

    if total_minutes < 60:
        return f"{total_minutes} min"

    hours = total_minutes // 60
    mins = total_minutes % 60
    return f"{hours} h {mins:02d}"


def format_eta_time(minutes_from_now: Optional[float]) -> str:
    if minutes_from_now is None:
        return "—"

    eta = datetime.now() + timedelta(minutes=minutes_from_now)
    return eta.strftime("%Hh%M")


def compute_tracking_metrics(
    df: pd.DataFrame,
    target_number: str,
    current_pace_per_hour: Optional[float],
    standard_minutes_per_amendment: float,
) -> dict:
    if df.empty:
        return {
            "found": False,
            "target_is_terminal": False,
            "remaining_before": None,
            "standard_eta_minutes": None,
            "realtime_eta_minutes": None,
            "realtime_eta_clock": None,
        }

    target_int = safe_int(target_number)
    if target_int is None:
        return {
            "found": False,
            "target_is_terminal": False,
            "remaining_before": None,
            "standard_eta_minutes": None,
            "realtime_eta_minutes": None,
            "realtime_eta_clock": None,
        }

    pending = df[~df["terminal"]].copy()
    pending = pending[pending["numero_int"].notna()].copy()
    pending = pending.sort_values("numero_int").reset_index(drop=True)

    target_rows = pending[pending["numero_int"] == target_int]
    if target_rows.empty:
        all_rows = df[df["numero_int"] == target_int]
        target_is_terminal = not all_rows.empty and bool(all_rows.iloc[0]["terminal"])
        return {
            "found": False,
            "target_is_terminal": target_is_terminal,
            "remaining_before": None,
            "standard_eta_minutes": None,
            "realtime_eta_minutes": None,
            "realtime_eta_clock": None,
        }

    target_position = target_rows.index[0]
    remaining_before = int(target_position)

    standard_eta_minutes = remaining_before * standard_minutes_per_amendment

    realtime_eta_minutes = None
    realtime_eta_clock = None

    if current_pace_per_hour is not None and current_pace_per_hour > 0:
        minutes_per_amendment = 60 / current_pace_per_hour
        realtime_eta_minutes = remaining_before * minutes_per_amendment
        realtime_eta_clock = format_eta_time(realtime_eta_minutes)

    return {
        "found": True,
        "target_is_terminal": False,
        "remaining_before": remaining_before,
        "standard_eta_minutes": standard_eta_minutes,
        "realtime_eta_minutes": realtime_eta_minutes,
        "realtime_eta_clock": realtime_eta_clock,
    }


def compute_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "remaining": None,
            "pace_15": None,
            "pace_30": None,
            "pace_hour": None,
            "last_update": None,
            "source": "Assemblée nationale",
            "total": 0,
        }

    total = len(df)
    remaining = int((~df["terminal"]).sum())

    pace_15 = compute_pace(df, 15)
    pace_30 = compute_pace(df, 30)

    if pace_30 is not None:
        pace_hour = pace_30
    elif pace_15 is not None:
        pace_hour = pace_15
    else:
        pace_hour = None

    return {
        "remaining": remaining,
        "pace_15": pace_15,
        "pace_30": pace_30,
        "pace_hour": pace_hour,
        "last_update": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "source": "Assemblée nationale",
        "total": total,
    }


with st.spinner("Chargement des amendements du texte..."):
    df = load_text_amendments(texte_numero.strip())

metrics = compute_metrics(df)

tracking = compute_tracking_metrics(
    df=df,
    target_number=amendement_suivi.strip(),
    current_pace_per_hour=metrics["pace_hour"],
    standard_minutes_per_amendment=float(minutes_par_amendement_standard),
)

if df.empty:
    st.error("Impossible de charger les amendements pour ce texte.")
    st.info("Vérifiez que le numéro saisi correspond bien au texte examiné, par exemple 2633.")
else:
    st.success(f"{metrics['total']} amendements détectés pour le texte n° {texte_numero}.")

col1, col2 = st.columns(2)

with col1:
    st.markdown("## Amendements restants")
    if metrics["remaining"] is None:
        st.markdown("# —")
    else:
        st.markdown(f"# {metrics['remaining']}")

with col2:
    st.markdown("## Rythme de la séance")
    if metrics["pace_hour"] is None:
        st.markdown("# —")
    else:
        st.markdown(f"# {metrics['pace_hour']} / heure")

col3, col4, col5 = st.columns(3)

with col3:
    st.metric(
        "Moyenne 15 min",
        "—" if metrics["pace_15"] is None else f"{metrics['pace_15']} / h",
    )

with col4:
    st.metric(
        "Moyenne 30 min",
        "—" if metrics["pace_30"] is None else f"{metrics['pace_30']} / h",
    )

with col5:
    st.metric("Source", metrics["source"])

st.caption(f"Dernière mise à jour : {metrics['last_update']}")

st.markdown("---")
st.markdown(f"## Amendement suivi : {amendement_suivi or '—'}")

if tracking["target_is_terminal"]:
    st.warning("Cet amendement semble déjà traité.")
elif not tracking["found"]:
    st.info("Amendement non trouvé parmi les amendements encore en attente dans le périmètre chargé.")
else:
    t1, t2, t3, t4 = st.columns(4)

    with t1:
        st.metric("Amendements avant passage", tracking["remaining_before"])

    with t2:
        st.metric(
            "Estimation standard",
            format_duration(tracking["standard_eta_minutes"]),
        )

    with t3:
        st.metric(
            "Estimation rythme réel",
            format_duration(tracking["realtime_eta_minutes"]),
        )

    with t4:
        st.metric(
            "Heure estimée de passage",
            tracking["realtime_eta_clock"] or "—",
        )

    if tracking["remaining_before"] is not None and tracking["remaining_before"] <= 5:
        st.warning("L’amendement suivi approche.")
    elif tracking["remaining_before"] is not None and tracking["remaining_before"] <= 10:
        st.info("L’amendement suivi entre dans une zone de vigilance.")

st.markdown("---")

with st.expander("Aperçu des données"):
    st.write(f"Texte examiné : {texte_numero}")
    if not df.empty:
        preview = df[["numero", "sort", "date_sort", "terminal", "page_url"]].copy()
        st.dataframe(preview.head(50), use_container_width=True)

st.caption(
    "Version MVP. Les estimations sont indicatives et évoluent selon le rythme réel de la séance."
)
