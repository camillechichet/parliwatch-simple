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
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

TERMINAL_SORTS = {
    "adopté",
    "rejeté",
    "tombé",
    "retiré",
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
    help="Exemple : 2633"
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
    return text or None


def is_terminal_sort(value: Optional[str]) -> bool:
    normalized = normalize_sort(value)
    return normalized in TERMINAL_SORTS


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def extract_json_url_from_html(html: str) -> Optional[str]:
    match = re.search(
        r"https://www\.assemblee-nationale\.fr/dyn/opendata/[^\"']+\.json",
        html
    )
    if match:
        return match.group(0)
    return None


def build_amendment_page_url(text_number: str, amend_number: int) -> str:
    return f"https://www.assemblee-nationale.fr/dyn/{LEGISLATURE}/amendements/{text_number}/{ORGANE}/{amend_number}"


@st.cache_data(ttl=120, show_spinner=False)
def fetch_amendment_record(text_number: str, amend_number: int) -> Optional[dict]:
    page_url = build_amendment_page_url(text_number, amend_number)

    try:
        page_response = session_get(page_url)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        raise
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

            # Plusieurs structures existent selon les flux ; on reste prudent.
            sort_value = (
                amendement.get("sort")
                or amendement.get("sortEnSeance")
                or amendement.get("sortEnCommission")
            )

            date_sort = (
                amendement.get("dateSort")
                or amendement.get("date_sort")
            )

            identification = amendement.get("identification", {})
            numero_long = identification.get("numeroLong") or identification.get("numero")

            if numero_long:
                record["numero"] = str(numero_long)

            record["sort"] = sort_value
            record["date_sort"] = date_sort
            record["etat_source"] = "json_opendata"

        except Exception:
            # On garde au moins la page HTML.
            pass

    return record


@st.cache_data(ttl=120, show_spinner=False)
def load_text_amendments(text_number: str, max_scan: int = 400, stop_after_missing: int = 30) -> pd.DataFrame:
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

    df["sort_normalized"] = df["sort"].apply(normalize_sort)
    df["terminal"] = df["sort_normalized"].apply(is_terminal_sort)
    df["date_sort_dt"] = df["date_sort"].apply(parse_iso_datetime)

    return df.sort_values(by="numero", key=lambda s: pd.to_numeric(s, errors="coerce"))


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

if df.empty:
    st.error("Impossible de charger les amendements pour ce texte.")
    st.info("Vérifiez que le numéro saisi correspond bien au texte examiné, par exemple 2633.")
else:
    st.success(f"{metrics['total']} amendements détectés pour le texte n° {texte_numero}.")

col1, col2 = st.columns(2)

with col1:
    st.markdown("## Amendements restants")
    st.markdown("# —" if metrics["remaining"] is None else f"# {metrics['remaining']}")

with col2:
    st.markdown("## Rythme de la séance")
    st.markdown("### —" if metrics["pace_hour"] is None else f"# {metrics['pace_hour']} / heure")

col3, col4, col5 = st.columns(3)

with col3:
    st.metric("Moyenne 15 min", "—" if metrics["pace_15"] is None else f"{metrics['pace_15']} / h")

with col4:
    st.metric("Moyenne 30 min", "—" if metrics["pace_30"] is None else f"{metrics['pace_30']} / h")

with col5:
    st.metric("Source", metrics["source"])

st.caption(f"Dernière mise à jour : {metrics['last_update']}")

with st.expander("Aperçu des données"):
    st.write(f"Texte examiné : {texte_numero}")
    if not df.empty:
        preview = df[["numero", "sort", "date_sort", "etat_source", "page_url"]].copy()
        st.dataframe(preview.head(50), use_container_width=True)

st.markdown("---")
st.caption(
    "TODO : cette version scanne les amendements par numéros successifs. "
    "C’est simple et utile immédiatement, mais on pourra ensuite remplacer ce mécanisme "
    "par une collecte plus directe depuis les listes publiques si nécessaire."
)import streamlit as st
import pandas as pd
import requests
from io import StringIO
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Suivi séance", layout="wide")

LEGISLATURE = "17"

st.title("Suivi de séance parlementaire")
st.caption("MVP simple : amendements restants + rythme de séance")

st.sidebar.header("Paramètres")

dossier_id = st.sidebar.text_input(
    "ID du dossier législatif",
    value="48701",
    help="Exemple : 48701"
)

st.sidebar.markdown(
    "Cette version utilise les données publiques de l’Assemblée nationale."
)


def build_candidate_urls(dossier_id: str) -> list[str]:
    base = (
        f"https://data.assemblee-nationale.fr/static/openData/repository/"
        f"{LEGISLATURE}/dossiers_legislatifs_opendata/{dossier_id}"
    )
    return [
        f"{base}/libre_office.csv",
        f"{base}/excel.csv",
    ]


def fetch_text(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def parse_csv_text(text: str) -> pd.DataFrame:
    stripped = text.lstrip().lower()

    if stripped.startswith("<!doctype html") or stripped.startswith("<html"):
        raise ValueError("La réponse reçue est une page HTML et non un CSV.")

    attempts = [
        {"sep": ";", "engine": "python", "dtype": str},
        {"sep": ",", "engine": "python", "dtype": str},
        {"sep": None, "engine": "python", "dtype": str},
    ]

    last_error = None

    for options in attempts:
        try:
            df = pd.read_csv(StringIO(text), **options)
            if df.shape[1] > 1:
                df.columns = [str(c).strip() for c in df.columns]
                return df
        except Exception as e:
            last_error = e

    if last_error:
        raise last_error

    raise ValueError("Impossible d’interpréter le contenu comme un CSV exploitable.")


def load_amendments_csv(dossier_id: str):
    errors = []

    for url in build_candidate_urls(dossier_id):
        try:
            text = fetch_text(url)
            df = parse_csv_text(text)
            return df, url
        except Exception as e:
            errors.append(f"{url} -> {e}")

    st.error("Impossible de charger les données du dossier.")
    for err in errors:
        st.caption(err)

    return pd.DataFrame(), None


def find_column(df: pd.DataFrame, candidates: list[str]):
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for cand in candidates:
        key = cand.strip().lower()
        if key in lower_map:
            return lower_map[key]
    return None


def normalize_status(value) -> str:
    if pd.isna(value):
        return "en_attente"

    v = str(value).strip().lower()

    if v == "":
        return "en_attente"

    if any(x in v for x in [
        "adopt",
        "rejet",
        "tomb",
        "retir",
        "non soutenu",
        "irrecevable"
    ]):
        return "traite"

    return "en_attente"


def compute_metrics(df: pd.DataFrame):
    if df.empty:
        return {
            "remaining": None,
            "pace_15": None,
            "pace_30": None,
            "pace_hour": None,
            "last_update": None,
            "source": "Assemblée nationale"
        }

    sort_col = find_column(df, [
        "sort", "Sort", "sort final", "sortFinal", "sort de l'amendement"
    ])

    date_col = find_column(df, [
        "dateSort", "date_sort", "DateSort", "date sort", "date du sort"
    ])

    if not sort_col:
        st.warning("Colonne 'sort' non trouvée. Le calcul des restants est approximatif.")
        remaining = len(df)
    else:
        df["__status__"] = df[sort_col].apply(normalize_status)
        remaining = int((df["__status__"] == "en_attente").sum())

    treated_df = pd.DataFrame()

    if sort_col:
        treated_df = df[df[sort_col].notna()].copy()
        if sort_col in treated_df.columns:
            treated_df = treated_df[treated_df[sort_col].astype(str).str.strip() != ""].copy()

    if date_col and not treated_df.empty:
        treated_df["__date__"] = pd.to_datetime(
            treated_df[date_col],
            errors="coerce",
            utc=True
        )
        treated_df = treated_df[treated_df["__date__"].notna()].copy()
    else:
        treated_df["__date__"] = pd.NaT

    now = datetime.now(timezone.utc)

    def pace_over(minutes: int):
        if treated_df.empty or treated_df["__date__"].isna().all():
            return None
        cutoff = now - timedelta(minutes=minutes)
        count = int((treated_df["__date__"] >= cutoff).sum())
        return round(count * (60 / minutes), 1)

    pace_15 = pace_over(15)
    pace_30 = pace_over(30)

    if pace_30 is not None:
        pace_hour = pace_30
    elif pace_15 is not None:
        pace_hour = pace_15
    else:
        pace_hour = None

    last_update = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    return {
        "remaining": remaining,
        "pace_15": pace_15,
        "pace_30": pace_30,
        "pace_hour": pace_hour,
        "last_update": last_update,
        "source": "Assemblée nationale"
    }


df, loaded_url = load_amendments_csv(dossier_id)
metrics = compute_metrics(df)

col1, col2 = st.columns(2)

with col1:
    st.markdown("## Amendements restants")
    if metrics["remaining"] is None:
        st.markdown("### —")
    else:
        st.markdown(f"# {metrics['remaining']}")

with col2:
    st.markdown("## Rythme de la séance")
    if metrics["pace_hour"] is None:
        st.markdown("### —")
    else:
        st.markdown(f"# {metrics['pace_hour']} / heure")

col3, col4, col5 = st.columns(3)

with col3:
    st.metric(
        "Moyenne 15 min",
        "—" if metrics["pace_15"] is None else f"{metrics['pace_15']} / h"
    )

with col4:
    st.metric(
        "Moyenne 30 min",
        "—" if metrics["pace_30"] is None else f"{metrics['pace_30']} / h"
    )

with col5:
    st.metric("Source", metrics["source"])

st.caption(f"Dernière mise à jour : {metrics['last_update']}")

with st.expander("Aperçu des données"):
    st.write(f"Dossier : {dossier_id}")
    st.write(f"URL chargée : {loaded_url}")
    st.dataframe(df.head(20), use_container_width=True)
