import streamlit as st

st.set_page_config(page_title="Eliasse Tracker", layout="wide")

st.title("Eliasse Tracker")
st.caption("Prototype simple de suivi d’un amendement dans Eliasse")

st.sidebar.header("Paramètres")

eliasse_url = st.sidebar.text_input(
    "URL Eliasse",
    value="https://eliasse.assemblee-nationale.fr/eliasse/index.html",
)

target_amendment = st.sidebar.text_input(
    "Amendement à suivre",
    value="18",
)

minutes_per_amendment = st.sidebar.number_input(
    "Minutes par amendement",
    min_value=1.0,
    max_value=10.0,
    value=2.0,
    step=0.5,
)

st.markdown("## État de séance")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Amendement en cours", "—")

with col2:
    st.metric("Sort visible", "—")

with col3:
    st.metric("Dernière mise à jour", "—")

st.markdown("---")
st.markdown("## Amendement suivi")

c1, c2, c3 = st.columns(3)

with c1:
    st.metric("Amendement suivi", target_amendment if target_amendment else "—")

with c2:
    st.metric("Amendements avant passage", "—")

with c3:
    st.metric("Estimation standard", "—")

st.markdown("---")
st.markdown("## Dérouleur visible")
st.info("Le connecteur Eliasse n’est pas encore branché. Étape suivante : lecture réelle d’Eliasse.")

st.caption(f"URL Eliasse : {eliasse_url}")
