import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Suivi séance", layout="wide")

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

CSV_URL = f"https://data.assemblee-nationale.fr/dossierLeg/liste-amendements?idDossier={dossier_id}"


def load_amendments_csv(url: str) -> pd.DataFrame:
    try:
        return pd.read_csv(url)
    except Exception as e:
        st.error(f"Impossible de charger les données : {e}")
        return pd.DataFrame()


def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower_map = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None


def normalize_status(value: str) -> str:
    if pd.isna(value):
        return "en_attente"
    v = str(value).strip().lower()
    if any(x in v for x in ["adopt", "rejet", "tomb", "retir", "non soutenu", "irrecevable"]):
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

    sort_col = find_column(df, ["sort", "Sort"])
    date_col = find_column(df, ["dateSort", "date_sort", "DateSort"])

    if not sort_col:
        st.warning("Colonne 'sort' non trouvée. Le calcul des restants est approximatif.")
        remaining = len(df)
    else:
        df["__status__"] = df[sort_col].apply(normalize_status)
        remaining = int((df["__status__"] == "en_attente").sum())

    treated_df = pd.DataFrame()
    if sort_col:
        treated_df = df[df[sort_col].notna()].copy()

    if date_col and not treated_df.empty:
        treated_df["__date__"] = pd.to_datetime(treated_df[date_col], errors="coerce", utc=True)
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


df = load_amendments_csv(CSV_URL)
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
    st.metric("Moyenne 15 min", "—" if metrics["pace_15"] is None else f"{metrics['pace_15']} / h")

with col4:
    st.metric("Moyenne 30 min", "—" if metrics["pace_30"] is None else f"{metrics['pace_30']} / h")

with col5:
    st.metric("Source", metrics["source"])

st.caption(f"Dernière mise à jour : {metrics['last_update']}")

with st.expander("Aperçu des données"):
    st.write(f"URL chargée : {CSV_URL}")
    st.dataframe(df.head(20), use_container_width=True)
