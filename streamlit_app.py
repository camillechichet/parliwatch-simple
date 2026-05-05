import json
import re
from datetime import datetime
from typing import Any, Optional

import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="Suivi amendement", layout="wide")

LEGISLATURE = "17"
ORGANE = "AN"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

st.title("Suivi de séance parlementaire")
st.caption("Version fiabilisée : statut réel d’un amendement, sans estimation artificielle")

st.sidebar.header("Paramètres")

texte_numero = st.sidebar.text_input(
    "Numéro du texte examiné",
    value="2633",
    help="Exemple : 2633",
)

amendement_numero = st.sidebar.text_input(
    "Numéro d’amendement",
    value="17",
    help="Exemple : 17",
)

st.sidebar.markdown(
    "Cette version affiche uniquement des informations fiabilisées à partir des pages publiques."
)


def session_get(url: str) -> requests.Response:
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response


def build_amendment_page_url(text_number: str, amendment_number: str) -> str:
    return (
        f"https://www.assemblee-nationale.fr/dyn/"
        f"{LEGISLATURE}/amendements/{text_number}/{ORGANE}/{amendment_number}"
    )


def extract_json_url_from_html(html: str) -> Optional[str]:
    patterns = [
        r'https://www\.assemblee-nationale\.fr/dyn/opendata/[^"\']+\.json',
        r'https://www\.assemblee-nationale\.fr/dyn/opendata/[^\s<]+\.json',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(0)
    return None


def normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def parse_date(value: Any) -> Optional[str]:
    raw = normalize_text(value)
    if not raw:
        return None

    # on garde une logique prudente : si le format est déjà lisible, on l'affiche
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return raw


def find_sort_in_payload(amendement: dict) -> Optional[str]:
    candidates = [
        amendement.get("sort"),
        amendement.get("sortEnSeance"),
        amendement.get("sortEnCommission"),
    ]
    for value in candidates:
        if normalize_text(value):
            return normalize_text(value)
    return None


def find_date_in_payload(amendement: dict) -> Optional[str]:
    candidates = [
        amendement.get("dateSort"),
        amendement.get("date_sort"),
        amendement.get("dateMiseEnLigne"),
    ]
    for value in candidates:
        if normalize_text(value):
            return parse_date(value)
    return None


def flatten_amendement_payload(payload: dict) -> dict:
    amendement = payload.get("amendement", payload)

    identification = amendement.get("identification", {}) if isinstance(amendement, dict) else {}
    auteurs = amendement.get("auteurs", {}) if isinstance(amendement, dict) else {}
    dispositif = amendement.get("dispositif", {}) if isinstance(amendement, dict) else {}
    corps = amendement.get("corps", {}) if isinstance(amendement, dict) else {}

    numero = (
        identification.get("numeroLong")
        or identification.get("numero")
        or amendement.get("numero")
    )

    return {
        "numero": normalize_text(numero),
        "sort": find_sort_in_payload(amendement),
        "date_sort": find_date_in_payload(amendement),
        "expose": normalize_text(
            dispositif.get("exposeSommaire")
            or corps.get("exposeSommaire")
            or amendement.get("exposeSommaire")
        ),
        "auteurs": normalize_text(
            auteurs.get("auteur")
            or auteurs.get("auteurs")
            or amendement.get("auteurs")
        ),
        "payload_brut": amendement,
    }


@st.cache_data(ttl=120, show_spinner=False)
def fetch_amendment_data(text_number: str, amendment_number: str) -> dict:
    page_url = build_amendment_page_url(text_number, amendment_number)

    result = {
        "found": False,
        "page_url": page_url,
        "json_url": None,
        "titre_page": None,
        "numero": amendment_number,
        "sort": None,
        "date_sort": None,
        "auteurs": None,
        "expose": None,
        "source": None,
        "message": None,
    }

    try:
        response = session_get(page_url)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            result["message"] = "Amendement introuvable pour ce texte."
            return result
        result["message"] = f"Erreur HTTP : {e}"
        return result
    except Exception as e:
        result["message"] = f"Erreur de chargement : {e}"
        return result

    html = response.text

    if "Amendement n°" not in html and "Sous-amendement n°" not in html:
        result["message"] = "La page ne semble pas correspondre à un amendement exploitable."
        return result

    result["found"] = True
    result["source"] = "page publique Assemblée"

    soup = BeautifulSoup(html, "lxml")
    if soup.title:
        result["titre_page"] = soup.title.get_text(" ", strip=True)

    json_url = extract_json_url_from_html(html)
    result["json_url"] = json_url

    if not json_url:
        result["message"] = "Amendement trouvé, mais lien JSON non détecté."
        return result

    try:
        json_response = session_get(json_url)
        payload = json_response.json()
        flat = flatten_amendement_payload(payload)

        if flat["numero"]:
            result["numero"] = flat["numero"]
        result["sort"] = flat["sort"]
        result["date_sort"] = flat["date_sort"]
        result["auteurs"] = flat["auteurs"]
        result["expose"] = flat["expose"]
        result["source"] = "page publique + JSON open data"
        return result

    except json.JSONDecodeError:
        result["message"] = "Le JSON détecté n’a pas pu être lu."
        return result
    except Exception as e:
        result["message"] = f"Amendement trouvé, mais JSON non exploitable : {e}"
        return result


def compute_status_label(data: dict) -> str:
    sort_value = normalize_text(data.get("sort"))
    if sort_value:
        return sort_value
    if data.get("found"):
        return "Pas de sort officiel détecté à ce stade"
    return "Introuvable"


with st.spinner("Chargement de l’amendement..."):
    amendment = fetch_amendment_data(texte_numero.strip(), amendement_numero.strip())

status_label = compute_status_label(amendment)

top1, top2, top3 = st.columns(3)

with top1:
    st.metric("Texte", texte_numero or "—")

with top2:
    st.metric("Amendement", amendment.get("numero") or amendement_numero or "—")

with top3:
    st.metric("Statut", status_label)

st.markdown("---")

if not amendment["found"]:
    st.error(amendment.get("message") or "Amendement introuvable.")
else:
    if amendment.get("sort"):
        st.success("Amendement trouvé avec sort officiel.")
    else:
        st.info("Amendement trouvé, mais aucun sort officiel détecté à ce stade.")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("### Informations fiables")
        st.write(f"**Statut / sort** : {amendment.get('sort') or 'Non détecté'}")
        st.write(f"**Date de traitement** : {amendment.get('date_sort') or 'Non détectée'}")
        st.write(f"**Source** : {amendment.get('source') or 'Non précisée'}")

    with c2:
        st.markdown("### Liens")
        st.write(f"**Page amendement** : {amendment.get('page_url')}")
        st.write(f"**JSON open data** : {amendment.get('json_url') or 'Non détecté'}")

    st.markdown("### Cadre d’usage")
    st.warning(
        "Cette version n’affiche volontairement ni nombre d’amendements restants, "
        "ni heure estimée de passage, tant que l’ordre de discussion en séance "
        "n’est pas fiabilisé par une source exploitable."
    )

    if amendment.get("auteurs"):
        st.markdown("### Auteurs")
        st.write(amendment["auteurs"])

    if amendment.get("expose"):
        st.markdown("### Exposé sommaire")
        st.write(amendment["expose"])

if amendment.get("message"):
    st.caption(amendment["message"])

st.markdown("---")
st.caption(
    "Version V2 fiable : seules les données certaines sont affichées. "
    "Les estimations de passage seront réintroduites dans un second temps, "
    "uniquement si la source d’ordre en séance est fiabilisée."
)
