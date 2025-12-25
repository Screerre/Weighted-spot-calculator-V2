import streamlit as st
import requests
import json
import os
import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd
import matplotlib.pyplot as plt

st.set_page_config(page_title="Spot Calculator ISIN", layout="wide")

# ------------------ Configuration OpenFIGI ------------------
API_KEY = "TON_API_KEY_OPENFIGI"
CACHE_FILE = "cache_figi.json"

if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f:
        cache_figi = json.load(f)
else:
    cache_figi = {}

def save_cache_figi():
    with open(CACHE_FILE, "w") as f:
        json.dump(cache_figi, f, indent=2)

def get_figi_data_from_isin(isin):
    """Récupère les données d’un produit via OpenFIGI à partir de l’ISIN"""
    isin_clean = isin.strip().upper()
    if isin_clean in cache_figi:
        return cache_figi[isin_clean]

    headers = {
        "Content-Type": "application/json",
        "X-OPENFIGI-APIKEY": API_KEY
    }
    data = [{"idType": "ID_ISIN", "idValue": isin_clean}]
    
    try:
        response = requests.post("https://api.openfigi.com/v3/mapping", headers=headers, json=data, timeout=10)
        results = response.json()
        if results and results[0].get("data"):
            product_data = results[0]["data"][0]
            cache_figi[isin_clean] = product_data
            save_cache_figi()
            return product_data
    except Exception as e:
        st.error(f"Erreur OpenFIGI : {e}")
    
    return None

# ------------------ Fonctions utilitaires ------------------
def get_price_on_date(ticker, date_str):
    """Retourne le prix Close le plus proche de date_str (format JJ/MM/AAAA)"""
    try:
        date = datetime.strptime(date_str.strip(), "%d/%m/%Y")
    except Exception:
        return None
    start = date - timedelta(days=4)
    end = date + timedelta(days=4)
    try:
        data = yf.download(ticker.upper(), start=start, end=end, progress=False)
    except Exception:
        return None
    if data is None or data.empty:
        return None
    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)
    data["diff"] = abs(data.index - date)
    closest = data.sort_values("diff").iloc[0]
    return float(closest["Close"])

# ------------------ Interface Streamlit ------------------
st.title("Spot Calculator pour Produits Structurés / Fonds via ISIN")

nb_sj = st.number_input("Nombre de sous-jacents", min_value=1, max_value=10, value=2)

mode_calcul_global = st.selectbox(
    "Mode de calcul du spot",
    ["Moyenne simple", "Cours le plus haut (max)", "Cours le plus bas (min)"]
)

sous_jacents = {}

for i in range(nb_sj):
    st.markdown(f"---\n**Sous-jacent {i+1}**")
    isin_input = st.text_input(f"ISIN du sous-jacent #{i+1}", key=f"isin{i}")
    dates = st.text_area(f"Dates de constatation (JJ/MM/AAAA, une par ligne)", key=f"dates{i}", height=120)
    ponderation = st.number_input(f"Pondération (0 = équi-pondérée)", min_value=0.0, max_value=10.0, value=0.0, step=0.01, key=f"pond{i}")

    if isin_input:
        figi_data = get_figi_data_from_isin(isin_input)
        if not figi_data:
            st.error(f"Impossible de récupérer les données pour l'ISIN {isin_input}")
            continue
        
        ticker = figi_data.get("ticker") or figi_data.get("securityType")  # fallback si pas de ticker
        dates_list = [d.strip() for d in dates.split("\n") if d.strip()]
        if dates_list:
            sous_jacents[isin_input] = {
                "ticker": ticker,
                "dates": dates_list,
                "pond": ponderation,
                "figi_data": figi_data
            }
        else:
            st.warning(f"Dates manquantes pour ISIN {isin_input}, sous-jacent ignoré.")

# ------------------ Calcul des spots ------------------
if st.button("Calculer le spot"):
    if not sous_jacents:
        st.error("Aucun sous-jacent valide pour le calcul.")
    else:
        resultats = []
        spots_total, pond_total = 0.0, 0.0
        progress = st.progress(0, text="Récupération des données...")

        for idx, (isin_key, info) in enumerate(sous_jacents.items(), 1):
            valeurs = [get_price_on_date(info["ticker"], d) for d in info["dates"]]
            valeurs_clean = [v for v in valeurs if v is not None]

            if not valeurs_clean:
                spot = None
            else:
                if mode_calcul_global == "Moyenne simple":
                    spot = sum(valeurs_clean)/len(valeurs_clean)
                elif mode_calcul_global == "Cours le plus haut (max)":
                    spot = max(valeurs_clean)
                elif mode_calcul_global == "Cours le plus bas (min)":
                    spot = min(valeurs_clean)
                else:
                    spot = sum(valeurs_clean)/len(valeurs_clean)

            pond = info["pond"] if info["pond"] > 0 else 1.0
            if spot is not None:
                spots_total += spot * pond
                pond_total += pond

            resultats.append({
                "ISIN": isin_key,
                "Ticker/Security": info["ticker"],
                "Dates": ", ".join(info["dates"]),
                "Valeurs": ", ".join([str(v) if v is not None else "N/A" for v in valeurs]),
                "Spot": round(spot,6) if spot else "N/A",
                "Pondération": pond
            })
            progress.progress(int(idx/len(sous_jacents)*100))
        
        progress.empty()
        df = pd.DataFrame(resultats)
        st.subheader("Résultats individuels par sous-jacent")
        st.dataframe(df)

        if pond_total > 0:
            spot_global = spots_total/pond_total
            st.subheader("Spot global pondéré")
            st.metric("Spot global", f"{spot_global:.6f}")
            st.info(f"Mode de calcul : {mode_calcul_global}")

            # Graphique
            try:
                fig, ax = plt.subplots(figsize=(10,4))
                df_plot = df[df["Spot"] != "N/A"].set_index("ISIN")
                ax.bar(df_plot.index, df_plot["Spot"].astype(float))
                ax.set_ylabel("Spot")
                ax.set_title("Spot par sous-jacent")
                st.pyplot(fig)
            except Exception:
                st.warning("Impossible de générer le graphique.")

            # Export Excel
            with pd.ExcelWriter("spots_export.xlsx", engine="openpyxl") as out:
                df.to_excel(out, index=False, sheet_name="Spots")
            with open("spots_export.xlsx", "rb") as f:
                st.download_button(
                    label="Télécharger Excel",
                    data=f,
                    file_name="spots.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        else:
            st.error("Impossible de calculer le spot global : pas de prix valides.")