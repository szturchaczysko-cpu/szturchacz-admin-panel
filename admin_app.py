import streamlit as st
import pandas as pd
from datetime import datetime
import json
import firebase_admin
from firebase_admin import credentials, firestore

# --- 0. KONFIGURACJA ---
st.set_page_config(page_title="Panel Admina", layout="wide")

# --- INICJALIZACJA BAZY DANYCH ---
try:
    if not firebase_admin._apps:
        creds_dict = json.loads(st.secrets["FIREBASE_CREDS"])
        creds = credentials.Certificate(creds_dict)
        firebase_admin.initialize_app(creds)
    db = firestore.client()
except Exception as e:
    st.error(f"Błąd połączenia z bazą danych: {e}")
    st.stop()

# ==========================================
# 🔒 BRAMKA BEZPIECZEŃSTWA
# ==========================================
def check_password():
    if st.session_state.get("password_correct"):
        return True
    st.header("🔒 Panel Admina - Logowanie")
    password_input = st.text_input("Podaj hasło dostępu:", type="password", key="admin_password_input")
    if st.button("Zaloguj"):
        # Używamy innego hasła niż dla Szturchacza, dla bezpieczeństwa
        if st.session_state.admin_password_input == st.secrets["ADMIN_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("😕 Błędne hasło")
    return False

if not check_password():
    st.stop()

# ==========================================
# 📊 PANEL STATYSTYK
# ==========================================
st.title("📊 Panel Statystyk Operatorów")

selected_date = st.date_input("Wybierz dzień do analizy", datetime.now())
date_str = selected_date.strftime("%Y-%m-%d")

st.header(f"Wyniki dla dnia: {date_str}")

try:
    # Pobieramy dane z Firestore dla wybranego dnia
    operators_ref = db.collection("stats").document(date_str).collection("operators").stream()
    
    stats_data = []
    all_transitions = {}

    # Przetwarzamy dane każdego operatora
    for operator_doc in operators_ref:
        operator_data = operator_doc.to_dict()
        operator_name = operator_doc.id
        
        stats_data.append({
            "Operator": operator_name,
            "Ukończone sesje": operator_data.get("sessions_completed", 0)
        })
        
        if "pz_transitions" in operator_data:
            for transition, count in operator_data["pz_transitions"].items():
                # Zmieniamy kropki na strzałki dla czytelności
                formatted_transition = transition.replace("_to_", " → ")
                all_transitions[formatted_transition] = all_transitions.get(formatted_transition, 0) + count

    if stats_data:
        # --- SEKCJA OGÓLNA ---
        st.subheader("Ogólna aktywność")
        df_general = pd.DataFrame(stats_data).sort_values(by="Ukończone sesje", ascending=False).reset_index(drop=True)
        total_sessions = int(df_general["Ukończone sesje"].sum())
        st.metric("Łączna liczba sesji w tym dniu", total_sessions)
        st.dataframe(df_general, use_container_width=True)
        
        # --- SEKCJA PRZEJŚĆ PZ ---
        st.subheader("Najczęstsze przejścia między etapami (PZ)")
        if all_transitions:
            df_transitions = pd.DataFrame(list(all_transitions.items()), columns=['Przejście', 'Liczba']).sort_values(by="Liczba", ascending=False).reset_index(drop=True)
            
            st.dataframe(df_transitions, use_container_width=True)
            
            st.write("Wykres najpopularniejszych przejść:")
            st.bar_chart(df_transitions.set_index('Przejście'))
        else:
            st.info("Brak zarejestrowanych przejść PZ dla tego dnia.")

    else:
        st.info("Brak danych dla wybranego dnia.")

except Exception as e:
    st.error(f"Nie udało się pobrać danych: {e}")
