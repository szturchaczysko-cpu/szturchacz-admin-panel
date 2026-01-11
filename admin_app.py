import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import json
import firebase_admin
from firebase_admin import credentials, firestore
import pytz

# --- 0. KONFIGURACJA STRONY ---
st.set_page_config(page_title="Szturchacz - Admin Hub", layout="wide", page_icon="🕹️")

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
# 📑 ZAKŁADKI PANELU
# ==========================================
tab_stats, tab_config = st.tabs(["📊 Statystyki i Diamenty", "⚙️ Konfiguracja Operatorów"])

# Lista operatorów (zgodna z app.py)
OPERATORS = ["Wszyscy", "Emilia", "Oliwia", "Iwona", "Marlena", "Magda", "Sylwia", "Ewelina", "Klaudia", "Marta"]

# --- ZAKŁADKA 1: STATYSTYKI ---
with tab_stats:
    st.title("📊 Wyniki Pracy")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        time_range = st.selectbox("Zakres czasu:", ["Dziś", "Ostatnie 7 dni", "Ostatnie 30 dni (Global)"])
    with col2:
        selected_operator = st.selectbox("Filtruj operatora:", OPERATORS, key="stats_op_select")
    with col3:
        st.write("")
        if st.button("🔄 Odśwież statystyki", type="primary"):
            st.rerun()

    # Logika dat (Czas PL)
    tz_pl = pytz.timezone('Europe/Warsaw')
    today = datetime.now(tz_pl)
    dates_list = []
    if time_range == "Dziś": 
        dates_list.append(today.strftime("%Y-%m-%d"))
    elif time_range == "Ostatnie 7 dni":
        for i in range(7): dates_list.append((today - timedelta(days=i)).strftime("%Y-%m-%d"))
    else:
        for i in range(30): dates_list.append((today - timedelta(days=i)).strftime("%Y-%m-%d"))

    total_sessions_sum = 0
    total_diamonds_sum = 0
    operator_stats = {}
    operator_diamonds = {}
    transitions_stats = {}

    # Pobieranie danych
    for date_str in dates_list:
        try:
            docs = db.collection("stats").document(date_str).collection("operators").stream()
            for doc in docs:
                op_name = doc.id
                if selected_operator != "Wszyscy" and op_name != selected_operator: continue
                
                data = doc.to_dict()
                
                # Sesje
                sessions = data.get("sessions_completed", 0)
                total_sessions_sum += sessions
                operator_stats[op_name] = operator_stats.get(op_name, 0) + sessions
                
                # Przejścia i Diamenty (PZ6)
                trans_map = data.get("pz_transitions", {})
                if isinstance(trans_map, dict):
                    for key, count in trans_map.items():
                        clean_key = key.replace("_to_", " ➡ ")
                        transitions_stats[clean_key] = transitions_stats.get(clean_key, 0) + count
                        if key.endswith("_to_PZ6"):
                            operator_diamonds[op_name] = operator_diamonds.get(op_name, 0) + count
                            total_diamonds_sum += count
                
                # Obsługa płaskich kluczy (backup)
                for key, val in data.items():
                    if key.startswith("pz_transitions."):
                        trans_name = key.split("pz_transitions.")[1]
                        clean_key = trans_name.replace("_to_", " ➡ ")
                        count = val if isinstance(val, (int, float)) else 0
                        transitions_stats[clean_key] = transitions_stats.get(clean_key, 0) + count
                        if trans_name.endswith("_to_PZ6"):
                            operator_diamonds[op_name] = operator_diamonds.get(op_name, 0) + count
                            total_diamonds_sum += count
        except: pass

    st.markdown("---")
    m1, m2 = st.columns(2)
    m1.metric("Łączna liczba sesji", total_sessions_sum)
    m2.metric("Łączna liczba Diamentów 💎 (PZ6)", total_diamonds_sum)

    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.subheader("🏆 Ranking Aktywności")
        ranking_list = []
        for op in OPERATORS:
            if op == "Wszyscy": continue
            s = operator_stats.get(op, 0)
            d = operator_diamonds.get(op, 0)
            if s > 0 or d > 0:
                ranking_list.append({"Operator": op, "Sesje": s, "Diamenty 💎": d})
        
        if ranking_list:
            df_ranking = pd.DataFrame(ranking_list).sort_values(by='Diamenty 💎', ascending=False)
            # Używamy st.table zamiast st.dataframe jeśli błąd importu modułu nadal występuje
            st.dataframe(df_ranking, use_container_width=True, hide_index=True)
        else:
            st.info("Brak danych dla tego okresu.")

    with col_c2:
        st.subheader("📈 Przejścia PZ (Postęp)")
        if transitions_stats:
            df_trans = pd.DataFrame(list(transitions_stats.items()), columns=['Przejście', 'Liczba']).sort_values(by='Liczba', ascending=False)
            st.dataframe(df_trans, use_container_width=True, hide_index=True)
        else:
            st.info("Brak zarejestrowanych przejść.")

# --- ZAKŁADKA 2: KONFIGURACJA ---
with tab_config:
    st.title("⚙️ Zarządzanie Operatorami")
    
    selected_op_to_config = st.selectbox("Wybierz operatora do edycji:", OPERATORS[1:]) 
    
    # Pobierz aktualny config z bazy
    op_cfg_ref = db.collection("operator_configs").document(selected_op_to_config)
    current_cfg = op_cfg_ref.get().to_dict() or {}

    with st.form(f"config_form_{selected_op_to_config}"):
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Parametry Techniczne")
            # PRZYWRÓCONE POLE KLUCZA
            key_choice = st.number_input("Przypisany klucz API (0 = Rotator, 1-5 = Stały)", 
                                         min_value=0, max_value=5, 
                                         value=int(current_cfg.get("assigned_key_index", 0)))
            
            roles = ["Operatorzy_DE", "Operatorzy_FR", "Operatorzy_UK/PL"]
            current_role = current_cfg.get("role", "Operatorzy_DE")
            role_choice = st.selectbox("Rola w prompcie:", roles, 
                                       index=roles.index(current_role) if current_role in roles else 0)
        
        with c2:
            st.subheader("Komunikacja")
            admin_msg = st.text_area("Wiadomość dla operatora (widoczna w Szturchaczu):", 
                                     value=current_cfg.get("admin_message", ""), 
                                     height=150)
        
        if st.form_submit_button("💾 Zapisz i wyślij konfigurację"):
            op_cfg_ref.set({
                "assigned_key_index": key_choice,
                "role": role_choice,
                "admin_message": admin_msg,
                "updated_at": firestore.SERVER_TIMESTAMP
            }, merge=True)
            st.success(f"✅ Konfiguracja dla {selected_op_to_config} została zapisana!")
            st.rerun()

# Debugger surowych danych
with st.expander("🔍 Debugger bazy danych"):
    st.write("Analizowane daty:", dates_list)
    st.write("Surowy słownik przejść:", transitions_stats)
