import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import json
import firebase_admin
from firebase_admin import credentials, firestore
import pytz

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
    mode = st.radio("Tryb:", ["Zakresy", "Konkretny dzień", "All Time"], horizontal=True)
    tz_pl = pytz.timezone('Europe/Warsaw')
    today = datetime.now(tz_pl)
    dates_list = []

    if mode == "Zakresy":
        r = st.selectbox("Zakres:", ["Dziś", "7 dni", "30 dni"])
        days = 1 if r == "Dziś" else (7 if r == "7 dni" else 30)
        dates_list = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    elif mode == "Konkretny dzień":
        dates_list = [st.date_input("Data:").strftime("%Y-%m-%d")]
    else:
        dates_list = [doc.id for doc in db.collection("stats").stream()]

    sel_op = st.selectbox("Operator:", ["Wszyscy"] + OPERATORS)
    
    ts, td = 0, 0
    op_map, tr_map = {}, {}

    for d_s in dates_list:
        docs = db.collection("stats").document(d_s).collection("operators").stream()
        for doc in docs:
            name = doc.id
            if sel_op != "Wszyscy" and name != sel_op: continue
            data = doc.to_dict()
            s = data.get("sessions_completed", 0)
            ts += s
            op_map[name] = op_map.get(name, 0) + s
            for k, v in data.get("pz_transitions", {}).items():
                tr_map[k] = tr_map.get(k, 0) + v
                if k.endswith("_to_PZ6"): td += v

    c1, c2 = st.columns(2)
    c1.metric("Suma Sesji", ts)
    c2.metric("Suma Diamentów 💎", td)
    
    if op_map:
        st.bar_chart(pd.DataFrame(list(op_map.items()), columns=['Op', 'S']).set_index('Op'))

# --- ZAKŁADKA 2: KONFIGURACJA ---
with tab_config:
    st.title("⚙️ Ustawienia i Hasła")
    sel_op = st.selectbox("Wybierz operatora:", OPERATORS)
    cfg_ref = db.collection("operator_configs").document(sel_op)
    cfg = cfg_ref.get().to_dict() or {}

    with st.form("op_cfg"):
        col_a, col_b = st.columns(2)
        with col_a:
            new_pwd = st.text_input("Hasło logowania operatora:", value=cfg.get("password", ""))
            key_idx = st.number_input("Klucz API (0=Auto, 1-5=Stały)", 0, 5, value=int(cfg.get("assigned_key_index", 0)))
            role_sel = st.selectbox("Rola:", ["Operatorzy_DE", "Operatorzy_FR", "Operatorzy_UK/PL"], 
                                    index=["Operatorzy_DE", "Operatorzy_FR", "Operatorzy_UK/PL"].index(cfg.get("role", "Operatorzy_DE")))
        with col_b:
            new_msg = st.text_area("Wiadomość do operatora:", value=cfg.get("admin_message", ""))
        
        if st.form_submit_button("Zapisz"):
            cfg_ref.set({
                "password": new_pwd,
                "assigned_key_index": key_idx,
                "role": role_sel,
                "admin_message": new_msg,
                "message_read": False if new_msg != cfg.get("admin_message", "") else cfg.get("message_read", False),
                "updated_at": firestore.SERVER_TIMESTAMP
            }, merge=True)
            st.success("Zapisano!")

# --- ZAKŁADKA 3: STAN KLUCZY ---
with tab_keys:
    st.title("🔑 Monitor Kluczy")
    key_stats = db.collection("key_usage").document(today.strftime("%Y-%m-%d")).get().to_dict() or {}
    k_data = [{"Klucz": f"Klucz {i}", "Zużycie": key_stats.get(str(i), 0)} for i in range(1, 6)]
    st.table(pd.DataFrame(k_data))
    st.bar_chart(pd.DataFrame(k_data).set_index("Klucz"))
