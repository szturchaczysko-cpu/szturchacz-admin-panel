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
    try:
        creds_dict = json.loads(st.secrets["FIREBASE_CREDS"])
        creds = credentials.Certificate(creds_dict)
        firebase_admin.initialize_app(creds)
    except Exception as e:
        st.error(f"Błąd połącznia z bazą: {e}")
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
tab_stats, tab_config, tab_keys = st.tabs(["📊 Statystyki i Diamenty", "⚙️ Konfiguracja", "🔑 Stan Kluczy"])
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
        if st.button("🔄 Odśwież dane", type="primary"): st.rerun()

    # --- USTALANIE LISTY DAT ---
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

    # --- POBIERANIE I AGREGACJA ---
    total_sessions = 0
    total_diamonds = 0
    op_summary = {} # {name: {'s': 0, 'd': 0}}
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
                if name not in op_summary: op_summary[name] = {'s': 0, 'd': 0}
                
                # 1. Sesje
                s_count = data.get("sessions_completed", 0)
                op_summary[name]['s'] += s_count
                total_sessions += s_count
                
                # 2. Przejścia i Diamenty (PANCERNY PARSER)
                # Sprawdzamy wszystkie pola w dokumencie
                for key, val in data.items():
                    trans_key = ""
                    count = 0
                    
                    # Wariant A: Zagnieżdżona mapa {"pz_transitions": {"A_to_B": 5}}
                    if key == "pz_transitions" and isinstance(val, dict):
                        for t_name, t_count in val.items():
                            trans_key = t_name
                            count = t_count
                            display_name = trans_key.replace("_to_", " ➡ ")
                            all_transitions[display_name] = all_transitions.get(display_name, 0) + count
                            if trans_key.endswith("_to_PZ6"):
                                op_summary[name]['d'] += count
                                total_diamonds += count
                                
                    # Wariant B: Płaskie pole {"pz_transitions.A_to_B": 5}
                    elif key.startswith("pz_transitions."):
                        trans_key = key.split("pz_transitions.")[1]
                        count = val if isinstance(val, (int, float)) else 0
                        display_name = trans_key.replace("_to_", " ➡ ")
                        all_transitions[display_name] = all_transitions.get(display_name, 0) + count
                        if trans_key.endswith("_to_PZ6"):
                            op_summary[name]['d'] += count
                            total_diamonds += count
        progress_bar.empty()

    # --- WYŚWIETLANIE ---
    st.markdown("---")
    m1, m2 = st.columns(2)
    m1.metric("Łączna liczba sesji", total_sessions)
    m2.metric("Łączna liczba Diamentów 💎", total_diamonds)

    st.markdown("---")
    c_left, c_right = st.columns(2)

    with c_left:
        st.subheader("🏆 Ranking Operatorów")
        if op_summary:
            ranking_data = [{"Operator": k, "Sesje": v['s'], "Diamenty 💎": v['d']} for k, v in op_summary.items()]
            df_ranking = pd.DataFrame(ranking_data).sort_values(by="Diamenty 💎", ascending=False)
            st.dataframe(df_ranking, use_container_width=True, hide_index=True)
            st.bar_chart(df_ranking.set_index("Operator")["Sesje"])
        else: st.info("Brak danych.")

    with c_right:
        st.subheader("📈 Przejścia PZ (Postęp)")
        if all_transitions:
            df_tr = pd.DataFrame(list(all_transitions.items()), columns=['Przejście', 'Ilość']).sort_values(by='Ilość', ascending=False)
            st.dataframe(df_tr, use_container_width=True, hide_index=True)
            st.bar_chart(df_tr.set_index("Przejście")["Ilość"])
        else: st.info("Brak danych.")

# ==========================================
# ⚙️ ZAKŁADKA 2: KONFIGURACJA
# ==========================================
with tab_config:
    st.title("⚙️ Zarządzanie Systemem")
    
    # Ustawienia Globalne
    global_ref = db.collection("admin_config").document("global_settings")
    global_cfg = global_ref.get().to_dict() or {"show_diamonds": True}
    toggle_diamonds = st.toggle("Pokazuj diamenty operatorom w Szturchaczu", value=global_cfg.get("show_diamonds", True))
    if toggle_diamonds != global_cfg.get("show_diamonds"):
        global_ref.set({"show_diamonds": toggle_diamonds}, merge=True)
        st.rerun()

    st.markdown("---")
    sel_op = st.selectbox("Wybierz operatora do edycji:", OPERATORS, key="op_cfg_sel")
    cfg_ref = db.collection("operator_configs").document(sel_op)
    cfg = cfg_ref.get().to_dict() or {}

    with st.form(key=f"form_v3_{sel_op}"):
        col_a, col_b = st.columns(2)
        with col_a:
            new_pwd = st.text_input("Hasło logowania:", value=cfg.get("password", ""))
            key_idx = st.number_input("Klucz API (0=Auto, 1-5=Stały)", 0, 5, value=int(cfg.get("assigned_key_index", 0)))
            app_files = ["app.py", "app2.py", "app_test.py"]
            cur_file = cfg.get("app_file", "app.py")
            new_app_file = st.selectbox("Plik aplikacji:", app_files, index=app_files.index(cur_file) if cur_file in app_files else 0)
            roles = ["Operatorzy_DE", "Operatorzy_FR", "Operatorzy_UK/PL"]
            cur_role = cfg.get("role", "Operatorzy_DE")
            role_sel = st.selectbox("Rola:", roles, index=roles.index(cur_role) if cur_role in roles else 0)
        with col_b:
            new_msg = st.text_area("Wiadomość dla operatora:", value=cfg.get("admin_message", ""), height=150)
            st.write(f"Status odczytu: {'✅ Odczytano' if cfg.get('message_read', False) else '🔴 Nieodczytano'}")
        
        if st.form_submit_button("💾 Zapisz ustawienia"):
            cfg_ref.set({
                "password": new_pwd, "assigned_key_index": key_idx, "role": role_sel,
                "admin_message": new_msg, "app_file": new_app_file,
                "message_read": False if new_msg != cfg.get("admin_message", "") else cfg.get("message_read", False),
                "updated_at": firestore.SERVER_TIMESTAMP
            }, merge=True)
            st.success("Zapisano!")
            st.rerun()

# ==========================================
# 🔑 ZAKŁADKA 3: STAN KLUCZY
# ==========================================
with tab_keys:
    st.title("🔑 Monitor Zużycia Kluczy")
    key_stats = db.collection("key_usage").document(today.strftime("%Y-%m-%d")).get().to_dict() or {}
    k_data = [{"Klucz": f"Klucz {i}", "Zużycie": key_stats.get(str(i), 0), "Limit": 250} for i in range(1, 6)]
    st.bar_chart(pd.DataFrame(k_data).set_index("Klucz")["Zużycie"])
    st.table(pd.DataFrame(k_data))
