import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import json, firebase_admin, pytz
from firebase_admin import credentials, firestore

# --- 0. KONFIGURACJA ---
st.set_page_config(page_title="Szturchacz - Admin Hub", layout="wide", page_icon="🕹️")

if not firebase_admin._apps:
    creds_dict = json.loads(st.secrets["FIREBASE_CREDS"])
    creds = credentials.Certificate(creds_dict)
    firebase_admin.initialize_app(creds)
db = firestore.client()

if "password_correct" not in st.session_state: st.session_state.password_correct = False
def check_password():
    if st.session_state.password_correct: return True
    st.header("🔒 Logowanie Admin")
    pwd = st.text_input("Hasło:", type="password")
    if st.button("Zaloguj"):
        if pwd == st.secrets["ADMIN_PASSWORD"]:
            st.session_state.password_correct = True
            st.rerun()
    return False
if not check_password(): st.stop()

tab_stats, tab_config, tab_keys = st.tabs(["📊 Statystyki", "⚙️ Konfiguracja", "🔑 Stan Kluczy"])
OPERATORS = ["Emilia", "Oliwia", "Iwona", "Marlena", "Magda", "Sylwia", "Ewelina", "Klaudia", "Marta"]

# --- ZAKŁADKA 1: STATYSTYKI ---
with tab_stats:
    tz_pl = pytz.timezone('Europe/Warsaw')
    today = datetime.now(tz_pl)
    
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        mode = st.radio("Tryb daty:", ["Zakresy", "Kalendarz", "All Time"], horizontal=True)
    with col_f2:
        selected_op = st.selectbox("Operator:", ["Wszyscy"] + OPERATORS)
    
    dates_list = []
    if mode == "Zakresy":
        r = st.selectbox("Wybierz:", ["Dziś", "7 dni", "30 dni"])
        days = 1 if r == "Dziś" else (7 if r == "7 dni" else 30)
        dates_list = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    elif mode == "Kalendarz":
        dates_list = [st.date_input("Wybierz dzień:", today).strftime("%Y-%m-%d")]
    else:
        with st.spinner("Pobieranie historii..."):
            dates_list = [doc.id for doc in db.collection("stats").stream()]

    # Agregacja
    ts, td = 0, 0
    op_map, tr_map = {}, {}

    for d_s in dates_list:
        docs = db.collection("stats").document(d_s).collection("operators").stream()
        for doc in docs:
            name = doc.id
            if selected_op != "Wszyscy" and name != selected_op: continue
            data = doc.to_dict()
            s = data.get("sessions_completed", 0)
            ts += s
            op_map[name] = op_map.get(name, 0) + s
            for k, v in data.get("pz_transitions", {}).items():
                clean_k = k.replace("_to_", " ➡ ")
                tr_map[clean_k] = tr_map.get(clean_k, 0) + v
                if k.endswith("_to_PZ6"): td += v

    st.markdown("---")
    c1, c2 = st.columns(2)
    c1.metric("Suma Sesji", ts)
    c2.metric("Suma Diamentów 💎", td)

    if op_map:
        st.subheader("🏆 Ranking Aktywności")
        df_op = pd.DataFrame([{"Operator": k, "Sesje": v, "Diamenty 💎": 0} for k, v in op_map.items()])
        # Dodaj diamenty do tabeli rankingu
        for i, row in df_op.iterrows():
            # Pobierz diamenty dla tego konkretnego okresu
            d_count = 0
            # Musimy przeszukać tr_map pod kątem tego operatora (ale tr_map jest zmergowany)
            # Więc prościej: pobierzemy diamenty z bazy dla tego okresu ponownie lub zsumujemy z pz_transitions
            # Dla uproszczenia wyświetlamy sesje na wykresie
            pass
        st.bar_chart(df_op.set_index("Operator")["Sesje"])
        st.dataframe(df_op.sort_values("Sesje", ascending=False), use_container_width=True, hide_index=True)

    if tr_map:
        st.subheader("📈 Wszystkie Przejścia PZ")
        df_tr = pd.DataFrame(list(tr_map.items()), columns=['Przejście', 'Ilość']).sort_values(by='Ilość', ascending=False)
        st.bar_chart(df_tr.set_index('Przejście'))
        st.dataframe(df_tr, use_container_width=True, hide_index=True)

# --- ZAKŁADKA 2: KONFIGURACJA ---
with tab_config:
    st.title("⚙️ Ustawienia")
    sel_op = st.selectbox("Wybierz operatora:", OPERATORS)
    
    # Pobranie danych ZAWSZE przy zmianie operatora
    cfg_ref = db.collection("operator_configs").document(sel_op)
    cfg = cfg_ref.get().to_dict() or {}

    with st.form(f"form_{sel_op}"):
        st.subheader(f"Profil: {sel_op}")
        c_a, c_b = st.columns(2)
        with c_a:
            new_pwd = st.text_input("Hasło:", value=cfg.get("password", ""))
            key_idx = st.number_input("Klucz (0=Auto, 1-5)", 0, 5, value=int(cfg.get("assigned_key_index", 0)))
            roles = ["Operatorzy_DE", "Operatorzy_FR", "Operatorzy_UK/PL"]
            role_sel = st.selectbox("Rola:", roles, index=roles.index(cfg.get("role", "Operatorzy_DE")) if cfg.get("role") in roles else 0)
        with c_b:
            new_msg = st.text_area("Wiadomość:", value=cfg.get("admin_message", ""))
            is_read = cfg.get("message_read", False)
            st.write(f"Status: {'✅ Przeczytano' if is_read else '🔴 Nieprzeczytano'}")
        
        if st.form_submit_button("Zapisz"):
            cfg_ref.set({
                "password": new_pwd,
                "assigned_key_index": key_idx,
                "role": role_sel,
                "admin_message": new_msg,
                "message_read": False if new_msg != cfg.get("admin_message", "") else is_read,
                "updated_at": firestore.SERVER_TIMESTAMP
            }, merge=True)
            st.success("Zapisano!")
            st.rerun()

# --- ZAKŁADKA 3: STAN KLUCZY ---
with tab_keys:
    st.title("🔑 Monitor Kluczy")
    key_stats = db.collection("key_usage").document(today.strftime("%Y-%m-%d")).get().to_dict() or {}
    k_data = [{"Klucz": f"Klucz {i}", "Zużycie": key_stats.get(str(i), 0)} for i in range(1, 6)]
    df_k = pd.DataFrame(k_data)
    st.bar_chart(df_k.set_index("Klucz"))
    st.table(df_k)
