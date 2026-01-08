import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import json
import firebase_admin
from firebase_admin import credentials, firestore
import pytz

# --- 0. KONFIGURACJA ---
st.set_page_config(page_title="Panel Admina", layout="wide")

# --- INICJALIZACJA BAZY DANYCH ---
try:
    if not firebase_admin._apps:
        # Pobieramy te same kredencjały co w Szturchaczu
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
# 📊 LOGIKA I INTERFEJS
# ==========================================
st.title("📊 Panel Statystyk Operatorów")

# --- FILTRY ---
col1, col2, col3 = st.columns(3)
with col1:
    time_range = st.selectbox("Zakres czasu:", ["Dziś", "Ostatnie 7 dni", "Ostatnie 30 dni (Global)"])
with col2:
    OPERATORS = ["Wszyscy", "Emilia", "Oliwia", "Iwona", "Marlena", "Magda", "Sylwia", "Ewelina", "Klaudia"]
    selected_operator = st.selectbox("Operator:", OPERATORS)
with col3:
    st.write("") # Odstęp
    if st.button("🔄 Odśwież dane", type="primary"):
        st.rerun()

# --- USTALANIE DAT (CZAS PL) ---
def get_dates_to_fetch(range_option):
    tz_pl = pytz.timezone('Europe/Warsaw')
    today = datetime.now(tz_pl)
    dates = []
    
    if range_option == "Dziś":
        dates.append(today.strftime("%Y-%m-%d"))
    elif range_option == "Ostatnie 7 dni":
        for i in range(7):
            d = today - timedelta(days=i)
            dates.append(d.strftime("%Y-%m-%d"))
    elif range_option == "Ostatnie 30 dni (Global)":
        for i in range(30):
            d = today - timedelta(days=i)
            dates.append(d.strftime("%Y-%m-%d"))
            
    return dates

dates_list = get_dates_to_fetch(time_range)

# --- POBIERANIE DANYCH Z BAZY ---
total_sessions_sum = 0
operator_stats = {} # {operator: liczba_sesji}
transitions_stats = {} # {przejscie: liczba}

# Pasek postępu (dla dłuższego zakresu dat)
progress_bar = st.progress(0)
status_text = st.empty()

for i, date_str in enumerate(dates_list):
    progress_bar.progress((i + 1) / len(dates_list))
    
    try:
        # Pobieramy kolekcję operatorów dla danego dnia
        docs = db.collection("stats").document(date_str).collection("operators").stream()
        
        for doc in docs:
            op_name = doc.id
            data = doc.to_dict()
            
            # FILTR OPERATORA
            if selected_operator != "Wszyscy" and op_name != selected_operator:
                continue
            
            # 1. Sumowanie sesji
            sessions = data.get("sessions_completed", 0)
            total_sessions_sum += sessions
            
            # Dodajemy do rankingu operatorów
            operator_stats[op_name] = operator_stats.get(op_name, 0) + sessions
            
            # 2. Sumowanie przejść PZ
            # Struktura w bazie: { "pz_transitions": { "PZ_START_to_PZ0": 1 } }
            transitions_map = data.get("pz_transitions", {})
            for key, count in transitions_map.items():
                # Zamiana klucza "PZ_START_to_PZ0" na ładny tekst
                clean_key = key.replace("_to_", " ➡ ")
                transitions_stats[clean_key] = transitions_stats.get(clean_key, 0) + count
                
    except Exception:
        # Ignorujemy dni, w których nie ma jeszcze bazy (np. przyszłość)
        pass

status_text.empty()
progress_bar.empty()

# --- PREZENTACJA DANYCH ---

st.markdown("---")

# METRYKA GŁÓWNA
st.metric(label=f"Łączna liczba zamkniętych sesji ({time_range})", value=total_sessions_sum)

col_charts1, col_charts2 = st.columns(2)

# WYKRES 1: RANKING OPERATORÓW (Tylko jeśli wybrano "Wszyscy")
with col_charts1:
    st.subheader("🏆 Aktywność Operatorów")
    if operator_stats:
        df_ops = pd.DataFrame(list(operator_stats.items()), columns=['Operator', 'Sesje'])
        df_ops = df_ops.sort_values(by='Sesje', ascending=False)
        st.dataframe(df_ops, use_container_width=True, hide_index=True)
    else:
        st.info("Brak danych o sesjach.")

# WYKRES 2: PRZEJŚCIA PZ
with col_charts2:
    st.subheader("📈 Postęp Spraw (Przejścia PZ)")
    if transitions_stats:
        df_trans = pd.DataFrame(list(transitions_stats.items()), columns=['Przejście', 'Liczba'])
        df_trans = df_trans.sort_values(by='Liczba', ascending=False)
        
        # Wykres słupkowy
        st.bar_chart(df_trans.set_index('Przejście'))
        
        # Tabela pod wykresem
        st.dataframe(df_trans, use_container_width=True, hide_index=True)
    else:
        st.info("Brak zarejestrowanych przejść PZ w wybranym okresie.")

# Debugger surowych danych (opcjonalnie dla admina)
with st.expander("🔍 Podgląd surowych danych (Debug)"):
    st.write("Sprawdzane daty:", dates_list)
    st.write("Znalezione przejścia:", transitions_stats)
