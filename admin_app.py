import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import json
import firebase_admin
from firebase_admin import credentials, firestore
import pytz

# --- 0. KONFIGURACJA ---
st.set_page_config(page_title="Szturchacz - Admin Hub", layout="wide", page_icon="📊")

# --- INICJALIZACJA BAZY ---
if not firebase_admin._apps:
    creds_dict = json.loads(st.secrets["FIREBASE_CREDS"])
    creds = credentials.Certificate(creds_dict)
    firebase_admin.initialize_app(creds)
db = firestore.client()

# --- BRAMKA HASŁA ---
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

def check_password():
    if st.session_state.password_correct: return True
    st.header("🔒 Logowanie Admin")
    pwd = st.text_input("Hasło:", type="password")
    if st.button("Zaloguj"):
        if pwd == st.secrets["ADMIN_PASSWORD"]:
            st.session_state.password_correct = True
            st.rerun()
        else:
            st.error("Błędne hasło")
    return False

if not check_password(): st.stop()

# ==========================================
# 📑 ZAKŁADKI
# ==========================================
tab_stats, tab_config, tab_keys = st.tabs(["📊 Statystyki i Diamenty", "⚙️ Konfiguracja Operatorów", "🔑 Stan Kluczy"])

OPERATORS = ["Emilia", "Oliwia", "Iwona", "Marlena", "Magda", "Sylwia", "Ewelina", "Klaudia", "Marta"]

# ==========================================
# 📊 ZAKŁADKA 1: STATYSTYKI
# ==========================================
with tab_stats:
    tz_pl = pytz.timezone('Europe/Warsaw')
    today = datetime.now(tz_pl)
    
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        date_mode = st.radio("Wybór daty:", ["Zakresy", "Kalendarz", "All Time"], horizontal=True)
    with col_f2:
        selected_op = st.selectbox("Filtruj operatora:", ["Wszyscy"] + OPERATORS)
    with col_f3:
        st.write("")
        if st.button("🔄 Odśwież dane", type="primary"):
            st.rerun()

    # --- USTALANIE DAT ---
    dates_list = []
    if date_mode == "Zakresy":
        r = st.selectbox("Wybierz zakres:", ["Dziś", "Ostatnie 7 dni", "Ostatnie 30 dni"])
        days = 1 if r == "Dziś" else (7 if r == "7 dni" else 30)
        dates_list = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    elif date_mode == "Kalendarz":
        dates_list = [st.date_input("Wybierz dzień:", today).strftime("%Y-%m-%d")]
    else:
        with st.spinner("Pobieranie historii dat..."):
            all_stats_refs = db.collection("stats").list_documents()
            dates_list = [doc.id for doc in all_stats_refs]

    # --- POBIERANIE DANYCH ---
    total_sessions = 0
    total_diamonds = 0
    op_stats_map = {} # {name: {'s': 0, 'd': 0}}
    all_transitions = {}

    if dates_list:
        progress_bar = st.progress(0)
        for i, d_s in enumerate(dates_list):
            progress_bar.progress((i + 1) / len(dates_list))
            docs = db.collection("stats").document(d_s).collection("operators").stream()
            for doc in docs:
                name = doc.id
                if selected_op != "Wszyscy" and name != selected_op: continue
                
                data = doc.to_dict()
                s_count = data.get("sessions_completed", 0)
                
                if name not in op_stats_map: op_stats_map[name] = {'s': 0, 'd': 0}
                op_stats_map[name]['s'] += s_count
                total_sessions += s_count
                
                t_map = data.get("pz_transitions", {})
                if isinstance(t_map, dict):
                    for k, v in t_map.items():
                        clean_k = k.replace("_to_", " ➡ ")
                        all_transitions[clean_k] = all_transitions.get(clean_k, 0) + v
                        if k.endswith("_to_PZ6"):
                            op_stats_map[name]['d'] += v
                            total_diamonds += v
        progress_bar.empty()

    # --- WYŚWIETLANIE ---
    st.markdown("---")
    m1, m2 = st.columns(2)
    m1.metric("Łączna liczba sesji", total_sessions)
    m2.metric("Łączna liczba Diamentów 💎 (PZ6)", total_diamonds)

    st.markdown("---")
    c_left, c_right = st.columns(2)

    with c_left:
        st.subheader("🏆 Ranking Aktywności")
        if op_stats_map:
            ranking_data = [{"Operator": k, "Sesje": v['s'], "Diamenty 💎": v['d']} for k, v in op_stats_map.items()]
            df_ranking = pd.DataFrame(ranking_data).sort_values(by="Diamenty 💎", ascending=False)
            st.dataframe(df_ranking, use_container_width=True, hide_index=True)
            st.bar_chart(df_ranking.set_index("Operator")["Sesje"])
        else:
            st.info("Brak danych.")

    with c_right:
        st.subheader("📈 Przejścia PZ (Postęp)")
        if all_transitions:
            df_tr = pd.DataFrame(list(all_transitions.items()), columns=['Przejście', 'Ilość']).sort_values(by='Ilość', ascending=False)
            st.dataframe(df_tr, use_container_width=True, hide_index=True)
            st.bar_chart(df_tr.set_index("Przejście")["Ilość"])
        else:
            st.info("Brak danych.")

# ==========================================
# ⚙️ ZAKŁADKA 2: KONFIGURACJA
# ==========================================
with tab_config:
    st.title("⚙️ Zarządzanie Operatorami")
    sel_op = st.selectbox("Wybierz operatora do edycji:", OPERATORS, key="op_selector")
    
    cfg_ref = db.collection("operator_configs").document(sel_op)
    cfg = cfg_ref.get().to_dict() or {}

    is_read = cfg.get("message_read", False)
    st.write(f"Status wiadomości: {'✅ Odczytano' if is_read else '🔴 Oczekuje'}")

    with st.form(key=f"form_{sel_op}"):
        col_a, col_b = st.columns(2)
        with col_a:
            new_pwd = st.text_input("Hasło logowania:", value=cfg.get("password", ""))
            key_idx = st.number_input("Klucz API (0=Auto, 1-5=Stały)", 0, 5, value=int(cfg.get("assigned_key_index", 0)))
            roles = ["Operatorzy_DE", "Operatorzy_FR", "Operatorzy_UK/PL"]
            cur_role = cfg.get("role", "Operatorzy_DE")
            role_idx = roles.index(cur_role) if cur_role in roles else 0
            role_sel = st.selectbox("Rola:", roles, index=role_idx)
        with col_b:
            new_msg = st.text_area("Wiadomość dla operatora:", value=cfg.get("admin_message", ""), height=150)
        
        if st.form_submit_button("💾 Zapisz ustawienia"):
            msg_changed = new_msg != cfg.get("admin_message", "")
            cfg_ref.set({
                "password": new_pwd,
                "assigned_key_index": key_choice if 'key_choice' in locals() else key_idx,
                "role": role_sel,
                "admin_message": new_msg,
                "message_read": False if msg_changed else is_read,
                "updated_at": firestore.SERVER_TIMESTAMP
            }, merge=True)
            st.success(f"Zapisano zmiany dla {sel_op}!")
            st.rerun()

# ==========================================
# 🔑 ZAKŁADKA 3: STAN KLUCZY
# ==========================================
with tab_keys:
    st.title("🔑 Monitor Zużycia Kluczy")
    today_str = today.strftime("%Y-%m-%d")
    key_stats = db.collection("key_usage").document(today_str).get().to_dict() or {}
    k_data = [{"Klucz": f"Klucz {i}", "Zużycie": key_stats.get(str(i), 0), "Limit": 250} for i in range(1, 6)]
    df_keys = pd.DataFrame(k_data)
    st.bar_chart(df_keys.set_index("Klucz")["Zużycie"])
    st.table(df_keys)
