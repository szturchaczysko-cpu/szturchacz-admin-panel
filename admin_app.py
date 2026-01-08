import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import json
import firebase_admin
from firebase_admin import credentials, firestore
import pytz

# --- 0. KONFIGURACJA ---
st.set_page_config(page_title="Panel Admina - Statystyki", layout="wide", page_icon="📊")

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
# 📊 LOGIKA I INTERFEJS
# ==========================================
st.title("📊 Panel Statystyk Operatorów")

# --- FILTRY ---
col1, col2, col3 = st.columns(3)
with col1:
    time_range = st.selectbox("Zakres czasu:", ["Dziś", "Ostatnie 7 dni", "Ostatnie 30 dni (Global)"])
with col2:
    # Zaktualizowana lista o Martę
    OPERATORS = ["Wszyscy", "Emilia", "Oliwia", "Iwona", "Marlena", "Magda", "Sylwia", "Ewelina", "Klaudia", "Marta"]
    selected_operator = st.selectbox("Operator:", OPERATORS)
with col3:
    st.write("") 
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
total_diamonds_sum = 0
operator_stats = {} # {operator: liczba_sesji}
operator_diamonds = {} # {operator: liczba_diamentów}
transitions_stats = {} # {przejscie: liczba}

progress_bar = st.progress(0)

for i, date_str in enumerate(dates_list):
    progress_bar.progress((i + 1) / len(dates_list))
    
    try:
        docs = db.collection("stats").document(date_str).collection("operators").stream()
        
        for doc in docs:
            op_name = doc.id
            data = doc.to_dict()
            
            if selected_operator != "Wszyscy" and op_name != selected_operator:
                continue
            
            # 1. Sumowanie sesji
            sessions = data.get("sessions_completed", 0)
            total_sessions_sum += sessions
            operator_stats[op_name] = operator_stats.get(op_name, 0) + sessions
            
            # 2. Sumowanie przejść PZ i Diamentów (do PZ6)
            # Sprawdzamy Opcję A (mapa)
            transitions_map = data.get("pz_transitions", {})
            if isinstance(transitions_map, dict):
                for key, count in transitions_map.items():
                    # Zliczanie ogólne przejść
                    clean_key = key.replace("_to_", " ➡ ")
                    transitions_stats[clean_key] = transitions_stats.get(clean_key, 0) + count
                    
                    # Zliczanie DIAMENTÓW (wszystko co kończy się na PZ6)
                    if key.endswith("_to_PZ6"):
                        operator_diamonds[op_name] = operator_diamonds.get(op_name, 0) + count
                        total_diamonds_sum += count
            
            # Sprawdzamy Opcję B (płaskie klucze z kropką)
            for key, val in data.items():
                if key.startswith("pz_transitions."):
                    trans_name = key.split("pz_transitions.")[1]
                    count = val if isinstance(val, (int, float)) else 0
                    
                    clean_key = trans_name.replace("_to_", " ➡ ")
                    transitions_stats[clean_key] = transitions_stats.get(clean_key, 0) + count
                    
                    if trans_name.endswith("_to_PZ6"):
                        operator_diamonds[op_name] = operator_diamonds.get(op_name, 0) + count
                        total_diamonds_sum += count
                
    except Exception:
        pass

progress_bar.empty()

# --- PREZENTACJA DANYCH ---

st.markdown("---")
m1, m2 = st.columns(2)
m1.metric(label=f"Łączna liczba sesji ({time_range})", value=total_sessions_sum)
m2.metric(label=f"Łączna liczba Diamentów 💎 (PZ6)", value=total_diamonds_sum)

st.markdown("---")
col_charts1, col_charts2 = st.columns(2)

with col_charts1:
    st.subheader("🏆 Aktywność i Diamenty")
    
    # Tworzymy tabelę zbiorczą dla operatorów
    combined_data = []
    for op in OPERATORS:
        if op == "Wszyscy": continue
        sesje = operator_stats.get(op, 0)
        diamenty = operator_diamonds.get(op, 0)
        if sesje > 0 or diamenty > 0:
            combined_data.append({"Operator": op, "Sesje": sesje, "Diamenty 💎": diamenty})
    
    if combined_data:
        df_combined = pd.DataFrame(combined_data).sort_values(by='Diamenty 💎', ascending=False)
        st.dataframe(df_combined, use_container_width=True, hide_index=True)
        
        if selected_operator == "Wszyscy":
            st.bar_chart(df_combined.set_index('Operator')['Diamenty 💎'])
    else:
        st.info("Brak danych o aktywności.")

with col_charts2:
    st.subheader("📈 Postęp Spraw (Przejścia PZ)")
    if transitions_stats:
        df_trans = pd.DataFrame(list(transitions_stats.items()), columns=['Przejście', 'Liczba'])
        df_trans = df_trans.sort_values(by='Liczba', ascending=False)
        
        st.dataframe(df_trans, use_container_width=True, hide_index=True)
        st.bar_chart(df_trans.set_index('Przejście'))
    else:
        st.info("Brak zarejestrowanych przejść PZ w wybranym okresie.")

with st.expander("🔍 Podgląd surowych danych (Debug)"):
    st.write(f"Analizowane daty: {dates_list}")
    st.write("Słownik diamentów:", operator_diamonds)
    st.write("Słownik przejść:", transitions_stats)
