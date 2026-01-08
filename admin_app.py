import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
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

# --- FILTRY ---
col1, col2 = st.columns(2)
with col1:
    time_range = st.selectbox("Zakres czasu:", ["Dziś", "Ostatnie 7 dni", "Cała historia"])
with col2:
    # Pobieramy listę operatorów z kodu (można też z bazy, ale tak szybciej)
    OPERATORS = ["Wszyscy", "Emilia", "Oliwia", "Iwona", "Marlena", "Magda", "Sylwia", "Ewelina", "Klaudia"]
    selected_operator = st.selectbox("Operator:", OPERATORS)

# --- LOGIKA POBIERANIA DANYCH ---
def get_dates_in_range(range_type):
    dates = []
    today = datetime.now()
    if range_type == "Dziś":
        dates.append(today.strftime("%Y-%m-%d"))
    elif range_type == "Ostatnie 7 dni":
        for i in range(7):
            date = today - timedelta(days=i)
            dates.append(date.strftime("%Y-%m-%d"))
    elif range_type == "Cała historia":
        # Pobieramy kolekcje (dni) z bazy - to uproszczenie, pobieramy ostatnie 30 dni dla wydajności
        # W prawdziwej "całej historii" trzeba by iterować inaczej
        for i in range(30):
            date = today - timedelta(days=i)
            dates.append(date.strftime("%Y-%m-%d"))
    return dates

dates_to_fetch = get_dates_in_range(time_range)

# --- AGREGACJA DANYCH ---
total_sessions = 0
operator_stats = {} # {operator: sessions}
transitions_stats = {} # {transition: count}

with st.spinner("Pobieranie danych..."):
    for date_str in dates_to_fetch:
        try:
            operators_ref = db.collection("stats").document(date_str).collection("operators").stream()
            
            for doc in operators_ref:
                op_name = doc.id
                data = doc.to_dict()
                
                # Filtr operatora
                if selected_operator != "Wszyscy" and op_name != selected_operator:
                    continue
                
                # Zliczanie sesji
                sessions = data.get("sessions_completed", 0)
                total_sessions += sessions
                operator_stats[op_name] = operator_stats.get(op_name, 0) + sessions
                
                # Zliczanie przejść PZ
                if "pz_transitions" in data:
                    for trans, count in data["pz_transitions"].items():
                        clean_trans = trans.replace("_to_", " → ")
                        transitions_stats[clean_trans] = transitions_stats.get(clean_trans, 0) + count
                        
        except Exception:
            pass # Ignorujemy dni bez danych

# --- WYŚWIETLANIE WYNIKÓW ---

st.markdown("---")
st.metric("Łączna liczba sesji", total_sessions)

# 1. Wykres sesji (tylko jeśli wybrano "Wszyscy")
if selected_operator == "Wszyscy" and operator_stats:
    st.subheader("Ranking Operatorów")
    df_ops = pd.DataFrame(list(operator_stats.items()), columns=['Operator', 'Sesje']).sort_values(by='Sesje', ascending=False)
    st.bar_chart(df_ops.set_index('Operator'))
    st.dataframe(df_ops, use_container_width=True)

# 2. Statystyki przejść PZ
st.subheader("Analiza Przejść PZ (Postęp Spraw)")
if transitions_stats:
    df_trans = pd.DataFrame(list(transitions_stats.items()), columns=['Przejście', 'Liczba']).sort_values(by='Liczba', ascending=False)
    st.dataframe(df_trans, use_container_width=True)
    st.bar_chart(df_trans.set_index('Przejście'))
else:
    st.info("Brak danych o przejściach PZ dla wybranych kryteriów.")
