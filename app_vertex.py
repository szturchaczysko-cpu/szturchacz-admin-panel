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

# Pobieranie listy projektów z Secrets
try:
    GCP_PROJECTS = st.secrets["GCP_PROJECT_IDS"]
    if isinstance(GCP_PROJECTS, str): GCP_PROJECTS = [GCP_PROJECTS]
except:
    st.error("🚨 Błąd: Brak listy GCP_PROJECT_IDS w secrets!")
    st.stop()

# ==========================================
# 🔑 CONFIG I TOŻSAMOŚĆ
# ==========================================
op_name = st.session_state.operator
cfg_ref = db.collection("operator_configs").document(op_name)
cfg = cfg_ref.get().to_dict() or {}

# Wybór projektu (Admin > Losowanie)
fixed_key_idx = cfg.get("assigned_key_index", 0)
if fixed_key_idx > 0:
    idx = min(fixed_key_idx - 1, len(GCP_PROJECTS) - 1)
    st.session_state.vertex_project_index = idx
    is_project_locked = True
else:
    is_project_locked = False
    if "vertex_project_index" not in st.session_state:
        st.session_state.vertex_project_index = random.randint(0, len(GCP_PROJECTS) - 1)

current_gcp_project = GCP_PROJECTS[st.session_state.vertex_project_index]

# Inicjalizacja Vertex AI
if 'vertex_init_done' not in st.session_state or st.session_state.get('last_project') != current_gcp_project:
    try:
        creds_info = json.loads(st.secrets["FIREBASE_CREDS"])
        creds = service_account.Credentials.from_service_account_info(creds_info)
        vertexai.init(
            project=current_gcp_project,
            location=st.secrets["GCP_LOCATION"],
            credentials=creds
        )
        st.session_state.vertex_init_done = True
        st.session_state.last_project = current_gcp_project
    except Exception as e:
        st.error(f"Błąd inicjalizacji Vertex AI ({current_gcp_project}): {e}")
        st.stop()

# --- FUNKCJE POMOCNICZE ---
def parse_pz(text):
    if not text: return None
    # Szuka PZ+cyfra (np. PZ0, PZ12, PZ=PZ5)
    match = re.search(r'(PZ\d+)', text, re.IGNORECASE)
    if match: return match.group(1).upper()
    return None

def log_stats(op_name, start_pz, end_pz, proj_idx):
    tz_pl = pytz.timezone('Europe/Warsaw')
    today = datetime.now(tz_pl).strftime("%Y-%m-%d")
    time_str = datetime.now(tz_pl).strftime("%H:%M")
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
    db.collection("key_usage").document(today).set({str(proj_idx + 1): firestore.Increment(1)}, merge=True)

# ==========================================
# 🚀 SIDEBAR
# ==========================================
global_cfg = db.collection("admin_config").document("global_settings").get().to_dict() or {}
show_diamonds = global_cfg.get("show_diamonds", True)

with st.sidebar:
    st.title(f"👤 {op_name}")
    st.success(f"🚀 SILNIK: VERTEX AI")
    
    if show_diamonds:
        tz_pl = pytz.timezone('Europe/Warsaw')
        today_s = datetime.now(tz_pl).strftime("%Y-%m-%d")
        today_data = db.collection("stats").document(today_s).collection("operators").document(op_name).get().to_dict() or {}
        today_diamonds = sum(v for k, v in today_data.get("pz_transitions", {}).items() if k.endswith("_to_PZ6"))
        global_data = db.collection("global_stats").document("totals").collection("operators").document(op_name).get().to_dict() or {}
        all_time_diamonds = global_data.get("total_diamonds", 0)
        st.markdown(f"### 💎 Zamówieni kurierzy\n**Dziś:** {today_diamonds} | **Łącznie:** {all_time_diamonds}")
        st.markdown("---")

    admin_msg = cfg.get("admin_message", "")
    if admin_msg and not cfg.get("message_read", False):
        st.error(f"📢 **WIADOMOŚĆ:**\n\n{admin_msg}")
        if st.button("✅ Odczytałem"):
            db.collection("operator_configs").document(op_name).update({"message_read": True})
            st.rerun()

    st.markdown("---")
    st.radio("Model AI:", ["gemini-2.5-pro", "gemini-3.0-pro-preview"], key="selected_model_label")
    active_model_id = st.session_state.selected_model_label
    
    # --- PARAMETRY V21 (notag domyślnie TAK) ---
    st.subheader("🧪 Funkcje Eksperymentalne")
    st.toggle("Tryb NOTAG (Tag-Koperta)", key="notag_val", value=True) # <-- USTAWIONE NA TRUE
    st.toggle("Tryb ANALIZBIOR (Wsad zbiorczy)", key="analizbior_val", value=False)
    
    st.caption(f"🧠 Model ID: `{active_model_id}`")
    if is_project_locked: st.info(f"🔒 Projekt stały: {st.session_state.vertex_project_index + 1}")
    else: st.caption(f"🔄 Projekt (LB): {st.session_state.vertex_project_index + 1}")

    st.markdown("---")
    TRYBY_DICT = {"Standard": "od_szturchacza", "WA": "WA", "MAIL": "MAIL", "FORUM": "FORUM"}
    st.selectbox("Tryb Startowy:", list(TRYBY_DICT.keys()), key="tryb_label")
    wybrany_tryb_kod = TRYBY_DICT[st.session_state.tryb_label]
    
    if st.button("🚀 Nowa sprawa / Reset", type="primary"):
        st.session_state.messages = []
        st.session_state.chat_started = False
        st.session_state.current_start_pz = None
        if not is_project_locked:
            st.session_state.vertex_project_index = random.randint(0, len(GCP_PROJECTS) - 1)
        st.rerun()

    if st.button("🚪 Wyloguj"):
        st.session_state.clear()
        cookies.clear()
        cookies.save()
        st.rerun()

# --- GŁÓWNY INTERFEJS ---
st.title(f"🤖 Szturchacz (Vertex)")

if "chat_started" not in st.session_state: st.session_state.chat_started = False


# --- FUNKCJA POBIERANIA PROMPTU Z GITHUB ---
@st.cache_data(ttl=3600)  # Cache na 1 godzinę
def get_remote_prompt(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except Exception as e:
        st.error(f"Błąd pobierania promptu z GitHub: {e}")
        return ""

# TWÓJ LINK RAW Z GITHUBA (Wklej tutaj swój link):
PROMPT_URL = "https://raw.githubusercontent.com/szturchaczysko-cpu/szturchacz/refs/heads/main/prompt4622.txt"


if not st.session_state.chat_started:
    st.info("👈 Skonfiguruj panel i kliknij 'Nowa sprawa / Reset'.")
else:
    # !!! POBIERANIE PROMPTU V21 !!!
 # !!! POBIERANIE PROMPTU Z GITHUB ZAMIAST SECRETS !!!
    SYSTEM_PROMPT = get_remote_prompt(PROMPT_URL)
    
    if not SYSTEM_PROMPT:
        st.error("Nie udało się załadować promptu. Aplikacja wstrzymana.")
        st.stop()
    tz_pl = pytz.timezone('Europe/Warsaw')
    now = datetime.now(tz_pl)
    
    # Konwersja przełączników na TAK/NIE dla prompta
    p_notag = "TAK" if st.session_state.notag_val else "NIE"
    p_analizbior = "TAK" if st.session_state.analizbior_val else "NIE"
    
    parametry_startowe = f"""
# PARAMETRY STARTOWE
domyslny_operator={op_name}
domyslna_data={now.strftime('%d.%m')}
Grupa_Operatorska={cfg.get('role', 'Operatorzy_DE')}
domyslny_tryb={wybrany_tryb_kod}
notag={p_notag}
analizbior={p_analizbior}
"""
    FULL_PROMPT = SYSTEM_PROMPT + parametry_startowe

    def get_vertex_history():
        vh = []
        for m in st.session_state.messages[:-1]:
            role = "user" if m["role"] == "user" else "model"
            vh.append(Content(role=role, parts=[Part.from_text(m["content"])]))
        return vh

    # Wyświetlanie historii
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])

    # Logika odpowiedzi AI
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        with st.chat_message("model"):
            with st.spinner("Analiza przez Vertex AI..."):
                max_attempts = 3
                success = False
                for attempt in range(max_attempts):
                    try:
                        model = GenerativeModel(active_model_id, system_instruction=FULL_PROMPT)
                        history = get_vertex_history()
                        chat = model.start_chat(history=history)
                        response = chat.send_message(st.session_state.messages[-1]["content"], generation_config={"temperature": 0.0})
                        
                        st.markdown(response.text)
                        st.session_state.messages.append({"role": "model", "content": response.text})
                        
                        # Logowanie statystyk (obsługa notag=TAK)
                        if (';pz=' in response.text.lower() or 'cop#' in response.text.lower()) and 'c#' in response.text.lower():
                            log_stats(op_name, st.session_state.current_start_pz, parse_pz(response.text) or "PZ_END", st.session_state.vertex_project_index)
                        
                        success = True
                        break
                    except Exception as e:
                        if "429" in str(e) or "Quota" in str(e):
                            st.toast(f"⏳ Limit minuty. Próba {attempt+1}/{max_attempts}...")
                            time.sleep(5)
                        else:
                            st.error(f"Błąd Vertex AI: {e}")
                            break
                if not success: st.error("❌ Nie udało się uzyskać odpowiedzi.")

    if prompt := st.chat_input("Odpowiedz AI..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.rerun()

if not st.session_state.chat_started:
    st.subheader(f"📥 Pierwszy wsad ({op_name})")
    if wybrany_tryb_kod != "od_szturchacza":
        st.warning(f"💡 Tryb {st.session_state.tryb_label}: Wklej Tabelkę + Kopertę + Rolkę.")
        st.code(f"ROLKA_START_{wybrany_tryb_kod}")
    wsad_input = st.text_area("Wklej dane tutaj:", height=350)
    if st.button("🚀 Rozpocznij analizę", type="primary"):
        if wsad_input:
            st.session_state.current_start_pz = parse_pz(wsad_input) or "PZ_START"
            st.session_state.messages = [{"role": "user", "content": wsad_input}]
            st.session_state.chat_started = True
            st.rerun()
        else: st.error("Wsad jest pusty!")
