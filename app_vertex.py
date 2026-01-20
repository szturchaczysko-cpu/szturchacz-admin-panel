import streamlit as st
import vertexai
from vertexai.generative_models import GenerativeModel, ChatSession, Content, Part
import google.auth
from google.oauth2 import service_account
from datetime import datetime, timedelta
import locale, time, json, re, pytz, hashlib, random
import firebase_admin
from firebase_admin import credentials, firestore
from streamlit_cookies_manager import EncryptedCookieManager

# --- 0. KONFIGURACJA ŚRODOWISKA ---
try: locale.setlocale(locale.LC_TIME, "pl_PL.UTF-8")
except: pass

# --- 1. POŁĄCZENIA (Zaciągnięte z Routera app.py) ---
db = globals().get('db')
cookies = globals().get('cookies')

# Inicjalizacja Vertex AI
if 'vertex_init' not in st.session_state:
    try:
        creds_info = json.loads(st.secrets["FIREBASE_CREDS"])
        creds = service_account.Credentials.from_service_account_info(creds_info)
        vertexai.init(
            project=st.secrets["GCP_PROJECT_ID"],
            location=st.secrets["GCP_LOCATION"],
            credentials=creds
        )
        st.session_state.vertex_init = True
    except Exception as e:
        st.error(f"Błąd inicjalizacji Vertex AI: {e}")
        st.stop()

# --- FUNKCJE STATYSTYK ---
def parse_pz(text):
    if not text: return None
    match = re.search(r'COP#\s*PZ\s*:\s*(PZ\d+)', text, re.IGNORECASE)
    if match: return match.group(1).upper()
    return None

def log_stats(op_name, start_pz, end_pz):
    tz_pl = pytz.timezone('Europe/Warsaw')
    now_pl = datetime.now(tz_pl)
    today = now_pl.strftime("%Y-%m-%d")
    time_str = now_pl.strftime("%H:%M")
    doc_ref = db.collection("stats").document(today).collection("operators").document(op_name)
    upd = {
        "sessions_completed": firestore.Increment(1),
        "session_times": firestore.ArrayUnion([time_str])
    }
    if start_pz and end_pz:
        upd[f"pz_transitions.{start_pz}_to_{end_pz}"] = firestore.Increment(1)
        if end_pz == "PZ6":
            db.collection("global_stats").document("totals").collection("operators").document(op_name).set({"total_diamonds": firestore.Increment(1)}, merge=True)
    doc_ref.set(upd, merge=True)

# ==========================================
# 🔑 CONFIG I DIAMENTY
# ==========================================
op_name = st.session_state.operator
cfg_ref = db.collection("operator_configs").document(op_name)
cfg = cfg_ref.get().to_dict() or {}

global_cfg = db.collection("admin_config").document("global_settings").get().to_dict() or {}
show_diamonds_globally = global_cfg.get("show_diamonds", True)

tz_pl = pytz.timezone('Europe/Warsaw')
today_s = datetime.now(tz_pl).strftime("%Y-%m-%d")
today_data = db.collection("stats").document(today_s).collection("operators").document(op_name).get().to_dict() or {}
today_diamonds = sum(v for k, v in today_data.get("pz_transitions", {}).items() if k.endswith("_to_PZ6"))
global_data = db.collection("global_stats").document("totals").collection("operators").document(op_name).get().to_dict() or {}
all_time_diamonds = global_data.get("total_diamonds", 0)

# --- MAPA MODELI VERTEX AI (OSTATECZNE NAZWY) ---
MODEL_MAP = {
    "Gemini 1.5 Pro (Zalecany)": "gemini-2.5-pro",
    "Gemini 1.5 Flash (Szybki)": "gemini-1.5-flash",
    "Gemini 2.0 Flash Exp": "gemini-2.0-flash-exp"
}

if "messages" not in st.session_state: st.session_state.messages = []
if "chat_started" not in st.session_state: st.session_state.chat_started = False
if "current_start_pz" not in st.session_state: st.session_state.current_start_pz = None

# --- SIDEBAR ---
with st.sidebar:
    st.title(f"👤 {op_name}")
    st.success(f"🚀 VERTEX AI: {st.secrets['GCP_LOCATION']}")
    
    if show_diamonds_globally:
        st.markdown(f"### 💎 Zamówieni kurierzy\n**Dziś:** {today_diamonds} | **Łącznie:** {all_time_diamonds}")
        st.markdown("---")

    admin_msg = cfg.get("admin_message", "")
    if admin_msg and not cfg.get("message_read", False):
        st.error(f"📢 **WIADOMOŚĆ:**\n\n{admin_msg}")
        if st.button("✅ Odczytałem"):
            cfg_ref.update({"message_read": True})
            st.rerun()
    else:
        if admin_msg:
            with st.expander("📩 Poprzednia wiadomość"): st.write(admin_msg)

    st.markdown("---")
    st.radio("Wybierz model AI:", list(MODEL_MAP.keys()), key="selected_model_label")
    active_model_id = MODEL_MAP[st.session_state.selected_model_label]
    
    st.caption(f"🧠 Model ID: `{active_model_id}`")
    st.markdown("---")
    
    TRYBY_DICT = {"Standard": "od_szturchacza", "WA": "WA", "MAIL": "MAIL", "FORUM": "FORUM"}
    st.selectbox("Tryb Startowy:", list(TRYBY_DICT.keys()), key="tryb_label")
    wybrany_tryb_kod = TRYBY_DICT[st.session_state.tryb_label]
    
    if st.button("🚀 Nowa sprawa / Reset", type="primary"):
        st.session_state.messages = []
        st.session_state.chat_started = True
        st.session_state.current_start_pz = None
        st.rerun()

    if st.button("🚪 Wyloguj"):
        st.session_state.clear()
        cookies.clear()
        cookies.save()
        st.rerun()

# --- GŁÓWNY INTERFEJS ---
st.title(f"🤖 Szturchacz (Vertex AI)")

if not st.session_state.chat_started:
    st.info("👈 Skonfiguruj panel i kliknij 'Nowa sprawa / Reset'.")
else:
    SYSTEM_PROMPT = st.secrets["SYSTEM_PROMPT_V21"]
    
    # Parametry V21
    parametry_startowe = f"\ndomyslny_operator={op_name}\ndomyslna_data={datetime.now(tz_pl).strftime('%d.%m')}\nGrupa_Operatorska={cfg.get('role', 'Operatorzy_DE')}\ndomyslny_tryb={wybrany_tryb_kod}\nnotag=NIE\nanalizbior=NIE"
    FULL_PROMPT = SYSTEM_PROMPT + parametry_startowe

    # Inicjalizacja modelu
    model = GenerativeModel(active_model_id, system_instruction=FULL_PROMPT)

    def get_vertex_history():
        vertex_history = []
        for m in st.session_state.messages[:-1]:
            role = "user" if m["role"] == "user" else "model"
            vertex_history.append(Content(role=role, parts=[Part.from_text(m["content"])]))
        return vertex_history

    if len(st.session_state.messages) == 0:
        st.subheader(f"📥 Pierwszy wsad ({op_name})")
        wsad_input = st.text_area("Wklej dane tutaj:", height=350)
        if st.button("🚀 Rozpocznij analizę", type="primary"):
            if wsad_input:
                st.session_state.current_start_pz = parse_pz(wsad_input) or "PZ_START"
                st.session_state.messages.append({"role": "user", "content": wsad_input})
                with st.spinner("Analiza przez Vertex AI..."):
                    try:
                        response = model.generate_content(wsad_input, generation_config={"temperature": 0.0})
                        st.session_state.messages.append({"role": "model", "content": response.text})
                        log_stats(op_name, st.session_state.current_start_pz, parse_pz(response.text) or "PZ_END")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Błąd Vertex AI: {e}")
            else: st.error("Wsad jest pusty!")
    else:
        st.subheader(f"💬 Rozmowa: {op_name}")
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])
        
        if prompt := st.chat_input("Odpowiedz AI..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("model"):
                with st.spinner("Analizuję..."):
                    try:
                        history = get_vertex_history()
                        chat = model.start_chat(history=history)
                        response = chat.send_message(prompt, generation_config={"temperature": 0.0})
                        st.markdown(response.text)
                        st.session_state.messages.append({"role": "model", "content": response.text})
                        if 'cop#' in response.text.lower() and 'c#' in response.text.lower():
                            log_stats(op_name, st.session_state.current_start_pz, parse_pz(response.text) or "PZ_END")
                    except Exception as e:
                        st.error(f"Błąd: {e}")
