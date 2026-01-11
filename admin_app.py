import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import json
import firebase_admin
from firebase_admin import credentials, firestore
import pytz

# --- 0. KONFIGURACJA ---
st.set_page_config(page_title="Szturchacz - Admin Hub", layout="wide", page_icon="📊")

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
tab_stats, tab_config, tab_keys = st.tabs(["📊 Statystyki i Diamenty", "⚙️ Konfiguracja Operatorów", "🔑 Stan Kluczy"])

OPERATORS = ["Wszyscy", "Emilia", "Oliwia", "Iwona", "Marlena", "Magda", "Sylwia", "Ewelina", "Klaudia", "Marta"]

# ==========================================
# 📊 ZAKŁADKA 1: STATYSTYKI
# ==========================================
with tab_stats:
    st.title("📊 Wyniki Pracy")
    
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        date_mode = st.radio("Wybór daty:", ["Zakresy", "Kalendarz", "All Time"], horizontal=True)
    with col_f2:
        selected_operator = st.selectbox("Filtruj operatora:", OPERATORS, key="stats_op_select")
    with col_f3:
        st.write("")
        if st.button("🔄 Odśwież dane", type="primary"):
            st.rerun()

    # --- USTALANIE DAT (CZAS PL) ---
    tz_pl = pytz.timezone('Europe/Warsaw')
    today = datetime.now(tz_pl)
    dates_list = []

    if date_mode == "Zakresy":
        time_range = st.selectbox("Zakres:", ["Dziś", "Ostatnie 7 dni", "Ostatnie 30 dni"])
        if time_range == "Dziś": 
            dates_list = [today.strftime("%Y-%m-%d")]
        elif time_range == "Ostatnie 7 dni":
            dates_list = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        else:
            dates_list = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)]
    
    elif date_mode == "Kalendarz":
        picked_date = st.date_input("Wybierz konkretny dzień:", today)
        dates_list = [picked_date.strftime("%Y-%m-%d")]
    
    else: # All Time
        with st.spinner("Pobieranie listy dat z historii..."):
            all_docs = db.collection("stats").stream()
            dates_list = [doc.id for doc in all_docs]

    # --- POBIERANIE DANYCH ---
    total_sessions_sum = 0
    total_diamonds_sum = 0
    operator_stats = {} 
    operator_diamonds = {} 
    transitions_stats = {} 

    if dates_list:
        progress_bar = st.progress(0)
        for i, date_str in enumerate(dates_list):
            progress_bar.progress((i + 1) / len(dates_list))
            try:
                docs = db.collection("stats").document(date_str).collection("operators").stream()
                for doc in docs:
                    op_name = doc.id
                    if selected_operator != "Wszyscy" and op_name != selected_operator:
                        continue
                    
                    data = doc.to_dict()
                    sessions = data.get("sessions_completed", 0)
                    total_sessions_sum += sessions
                    operator_stats[op_name] = operator_stats.get(op_name, 0) + sessions
                    
                    transitions_map = data.get("pz_transitions", {})
                    for key, count in transitions_map.items():
                        clean_key = key.replace("_to_", " ➡ ")
                        transitions_stats[clean_key] = transitions_stats.get(clean_key, 0) + count
                        if key.endswith("_to_PZ6"):
                            operator_diamonds[op_name] = operator_diamonds.get(op_name, 0) + count
                            total_diamonds_sum += count
            except: pass
        progress_bar.empty()

    # --- WYŚWIETLANIE ---
    st.markdown("---")
    m1, m2 = st.columns(2)
    m1.metric(label="Łączna liczba sesji", value=total_sessions_sum)
    m2.metric(label="Łączna liczba Diamentów 💎 (PZ6)", value=total_diamonds_sum)

    st.markdown("---")
    col_charts1, col_charts2 = st.columns(2)

    with col_charts1:
        st.subheader("🏆 Aktywność i Diamenty")
        combined_data = []
        for op in OPERATORS:
            if op == "Wszyscy": continue
            s = operator_stats.get(op, 0)
            d = operator_diamonds.get(op, 0)
            if s > 0 or d > 0:
                combined_data.append({"Operator": op, "Sesje": s, "Diamenty 💎": d})
        
        if combined_data:
            df_combined = pd.DataFrame(combined_data).sort_values(by='Diamenty 💎', ascending=False)
            st.dataframe(df_combined, use_container_width=True, hide_index=True)
            st.bar_chart(df_combined.set_index('Operator')['Sesje'])
        else:
            st.info("Brak danych.")

    with col_charts2:
        st.subheader("📈 Przejścia PZ (Postęp)")
        if transitions_stats:
            df_trans = pd.DataFrame(list(transitions_stats.items()), columns=['Przejście', 'Liczba']).sort_values(by='Liczba', ascending=False)
            st.dataframe(df_trans, use_container_width=True, hide_index=True)
            st.bar_chart(df_trans.set_index('Przejście'))
        else:
            st.info("Brak danych.")

# ==========================================
# ⚙️ ZAKŁADKA 2: KONFIGURACJA
# ==========================================
with tab_config:
    st.title("⚙️ Zarządzanie Operatorami")
    
    # Wybór operatora do edycji
    sel_op = st.selectbox("Wybierz operatora do edycji:", OPERATORS[1:], key="sel_op_config")
    
    # Pobranie aktualnych danych z bazy (żeby formularz nie był pusty)
    cfg_ref = db.collection("operator_configs").document(sel_op)
    cfg = cfg_ref.get().to_dict() or {}

    # Status odczytu wiadomości
    is_read = cfg.get("message_read", False)
    st.write(f"Status ostatniej wiadomości: {'✅ Odczytano' if is_read else '🔴 Nieodczytano'}")

    with st.form(f"form_{sel_op}"):
        c1, c2 = st.columns(2)
        with c1:
            new_pwd = st.text_input("Hasło logowania (unikalne):", value=cfg.get("password", ""))
            key_choice = st.number_input("Klucz API (0=Auto, 1-5=Stały)", 0, 5, value=int(cfg.get("assigned_key_index", 0)))
            roles = ["Operatorzy_DE", "Operatorzy_FR", "Operatorzy_UK/PL"]
            cur_role = cfg.get("role", "Operatorzy_DE")
            role_choice = st.selectbox("Rola:", roles, index=roles.index(cur_role) if cur_role in roles else 0)
        with c2:
            new_msg = st.text_area("Wiadomość dla operatora:", value=cfg.get("admin_message", ""))
        
        if st.form_submit_button("💾 Zapisz konfigurację"):
            # Jeśli wiadomość się zmieniła, resetujemy status odczytu
            msg_changed = new_msg != cfg.get("admin_message", "")
            
            cfg_ref.set({
                "password": new_pwd,
                "assigned_key_index": key_choice,
                "role": role_choice,
                "admin_message": new_msg,
                "message_read": False if msg_changed else is_read,
                "updated_at": firestore.SERVER_TIMESTAMP
            }, merge=True)
            st.success("Zapisano pomyślnie!")
            st.rerun()

# ==========================================
# 🔑 ZAKŁADKA 3: STAN KLUCZY
# ==========================================
with tab_keys:
    st.title("🔑 Monitor Zużycia Kluczy")
    st.write("Liczba zapytań wykonanych dzisiaj (Limit: 250 / klucz)")
    
    today_str = today.strftime("%Y-%m-%d")
    key_stats = db.collection("key_usage").document(today_str).get().to_dict() or {}
    
    k_data = []
    for i in range(1, 6):
        usage = key_stats.get(str(i), 0)
        k_data.append({"Klucz": f"Klucz {i}", "Zużycie": usage, "Limit": 250})
    
    df_keys = pd.DataFrame(k_data)
    st.bar_chart(df_keys.set_index("Klucz")["Zużycie"])
    st.table(df_keys)

with st.expander("🔍 Debugger bazy"):
    st.write("Analizowane daty:", dates_list)
