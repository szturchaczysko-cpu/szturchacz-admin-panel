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
# 🔑 ZAKŁADKI
# ==========================================
tab_stats, tab_config, tab_keys = st.tabs(["📊 Statystyki i Diamenty", "⚙️ Konfiguracja Operatorów", "🔑 Stan Kluczy"])

# --- LISTA OPERATORÓW ---
OPERATORS = ["Emilia", "Oliwia", "Iwona", "Marlena", "Magda", "Sylwia", "Ewelina", "Klaudia", "Marta", "EwelinaG", "Andrzej", "Romana", "Kasia", "Klaudia"]

# --- LISTA PROJEKTÓW GCP (z secrets) ---
try:
    GCP_PROJECTS = st.secrets.get("GCP_PROJECT_IDS", [])
    if isinstance(GCP_PROJECTS, str):
        GCP_PROJECTS = [GCP_PROJECTS]
    GCP_PROJECTS = list(GCP_PROJECTS)
except:
    GCP_PROJECTS = []

# --- LISTA URL-i PROMPTÓW (zdefiniowana tutaj, łatwa do edycji) ---
PROMPT_URLS = {
    "Prompt Stabilny (prompt4623)": "https://raw.githubusercontent.com/szturchaczysko-cpu/szturchacz/refs/heads/main/prompt4623.txt",
    # Dodaj tutaj kolejne prompty gdy będą gotowe, np.:
    # "Prompt Testowy V2": "https://raw.githubusercontent.com/szturchaczysko-cpu/szturchacz/refs/heads/main/prompt_v2.txt",
}

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
        days = 1 if r == "Dziś" else (7 if r == "Ostatnie 7 dni" else 30)
        dates_list = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    elif date_mode == "Kalendarz":
        dates_list = [st.date_input("Wybierz dzień:", today).strftime("%Y-%m-%d")]
    else:
        with st.spinner("Pobieranie historii dat..."):
            all_stats_refs = db.collection("stats").list_documents()
            dates_list = [doc.id for doc in all_stats_refs]

    num_days = len(dates_list) if len(dates_list) > 0 else 1

    # --- POBIERANIE I AGREGACJA ---
    total_sessions = 0
    total_diamonds = 0
    op_summary = {} 
    all_transitions = {}
    hourly_sum = {f"{h:02d}": 0 for h in range(24)}

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
                
                # 2. Rozkład czasu (Godziny)
                session_times = data.get("session_times", [])
                for t in session_times:
                    hour = t.split(":")[0]
                    if hour in hourly_sum:
                        hourly_sum[hour] += 1
                
                # 3. Przejścia i Diamenty
                t_map = data.get("pz_transitions", {})
                if isinstance(t_map, dict):
                    for k, v in t_map.items():
                        display_name = k.replace("_to_", " ➡ ")
                        all_transitions[display_name] = all_transitions.get(display_name, 0) + v
                        if k.endswith("_to_PZ6"):
                            op_summary[name]['d'] += v
                            total_diamonds += v
                # Obsługa płaskich kluczy (backup)
                for key, val in data.items():
                    if key.startswith("pz_transitions."):
                        trans_name = key.split("pz_transitions.")[1]
                        display_name = trans_name.replace("_to_", " ➡ ")
                        count = val if isinstance(val, (int, float)) else 0
                        all_transitions[display_name] = all_transitions.get(display_name, 0) + count
                        if trans_name.endswith("_to_PZ6"):
                            op_summary[name]['d'] += count
                            total_diamonds += count
        progress_bar.empty()

    # --- WYŚWIETLANIE METRYK ---
    st.markdown("---")
    m1, m2, m3 = st.columns(3)
    m1.metric("Suma sesji (okres)", total_sessions)
    m2.metric("Średnia sesji / dzień", round(total_sessions / num_days, 2))
    m3.metric("Suma Diamentów 💎", total_diamonds)

    # --- WYKRES ŚREDNIEJ GODZINOWEJ ---
    st.subheader(f"🕐 Średnia wydajność godzinowa (na podstawie {num_days} dni)")
    if total_sessions > 0:
        hourly_avg = {hour: total / num_days for hour, total in hourly_sum.items()}
        df_hourly = pd.DataFrame(list(hourly_avg.items()), columns=['Godzina', 'Średnia liczba sesji'])
        st.area_chart(df_hourly.set_index("Godzina"))
    else:
        st.info("Brak danych czasowych dla wybranego okresu.")

    st.markdown("---")
    c_left, c_right = st.columns(2)

    with c_left:
        st.subheader("🏆 Ranking Operatorów")
        if op_summary:
            ranking_data = [{"Operator": k, "Suma Sesji": v['s'], "Średnia/Dzień": round(v['s']/num_days, 2), "Diamenty 💎": v['d']} for k, v in op_summary.items()]
            df_ranking = pd.DataFrame(ranking_data).sort_values(by="Diamenty 💎", ascending=False)
            st.dataframe(df_ranking, use_container_width=True, hide_index=True)
            st.bar_chart(df_ranking.set_index("Operator")["Średnia/Dzień"])
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
    
    global_ref = db.collection("admin_config").document("global_settings")
    global_cfg = global_ref.get().to_dict() or {"show_diamonds": True}
    toggle_diamonds = st.toggle("Pokazuj diamenty operatorom w Szturchaczu", value=global_cfg.get("show_diamonds", True))
    if toggle_diamonds != global_cfg.get("show_diamonds"):
        global_ref.set({"show_diamonds": toggle_diamonds}, merge=True)
        st.rerun()

    st.markdown("---")

    # --- DOZWOLONE MODELE AI (checkboxy) ---
    st.subheader("🤖 Dozwolone modele AI")
    st.caption("Zaznacz które modele mają być dostępne dla operatorów w Koordynatorze i Wieżowcu.")
    
    ALL_MODELS = {
        "gemini-2.5-pro": "Gemini 2.5 Pro",
        "gemini-3-pro-preview": "Gemini 3 Pro (Preview)",
        "gemini-3.1-pro-preview": "Gemini 3.1 Pro (Preview)",
    }
    
    current_allowed = global_cfg.get("allowed_models", ["gemini-2.5-pro", "gemini-3-pro-preview"])
    if isinstance(current_allowed, str):
        current_allowed = [current_allowed]
    
    new_allowed = []
    cols_m = st.columns(len(ALL_MODELS))
    for i, (model_id, model_label) in enumerate(ALL_MODELS.items()):
        with cols_m[i]:
            checked = st.checkbox(model_label, value=(model_id in current_allowed), key=f"model_cb_{model_id}")
            if checked:
                new_allowed.append(model_id)
    
    if not new_allowed:
        st.warning("⚠️ Musisz zaznaczyć przynajmniej jeden model!")
        new_allowed = ["gemini-2.5-pro"]
    
    if sorted(new_allowed) != sorted(current_allowed):
        if st.button("💾 Zapisz modele", key="save_models"):
            global_ref.set({"allowed_models": new_allowed}, merge=True)
            st.success(f"✅ Zapisano dozwolone modele: {', '.join([ALL_MODELS[m] for m in new_allowed])}")
            st.rerun()
        st.info(f"🔄 Zmiana: {', '.join([ALL_MODELS[m] for m in new_allowed])} — kliknij Zapisz")
    else:
        st.success(f"Aktywne: {', '.join([ALL_MODELS[m] for m in current_allowed])}")

    st.markdown("---")

    # --- CONTEXT CACHING (Vertex AI) ---
    st.subheader("⚡ Context Caching (Vertex AI)")
    st.caption("Cache'uje prompt systemowy — oszczędza tokeny i przyspiesza odpowiedzi. "
               "Cache żyje 60 min i jest współdzielony w ramach projektu GCP.")
    
    caching_enabled = global_cfg.get("context_caching_enabled", False)
    toggle_caching = st.toggle("Włącz Context Caching", value=caching_enabled)
    if toggle_caching != caching_enabled:
        global_ref.set({"context_caching_enabled": toggle_caching}, merge=True)
        if toggle_caching:
            st.success("✅ Context Caching WŁĄCZONY — operatorzy zaczną korzystać po odświeżeniu strony.")
        else:
            st.info("Context Caching WYŁĄCZONY.")
        st.rerun()

    st.markdown("---")
    
    # --- ZARZĄDZANIE LISTĄ PROMPTÓW ---
    st.subheader("📝 Zarządzanie URL-ami Promptów")
    st.caption("Poniżej widzisz zdefiniowane prompty. Aby dodać nowy, edytuj słownik PROMPT_URLS w kodzie admin_app.py lub dodaj przez formularz poniżej.")
    
    # Pobierz custom prompts z bazy (oprócz hardcoded)
    custom_prompts_ref = db.collection("admin_config").document("custom_prompts")
    custom_prompts_data = custom_prompts_ref.get().to_dict() or {}
    custom_prompt_urls = custom_prompts_data.get("urls", {})
    
    # Połącz hardcoded + custom
    ALL_PROMPT_URLS = {**PROMPT_URLS, **custom_prompt_urls}
    
    with st.expander("➕ Dodaj nowy URL promptu"):
        new_prompt_name = st.text_input("Nazwa promptu (np. 'Prompt Testowy V2'):")
        new_prompt_url = st.text_input("URL raw z GitHuba:")
        if st.button("Dodaj prompt"):
            if new_prompt_name and new_prompt_url:
                custom_prompt_urls[new_prompt_name] = new_prompt_url
                custom_prompts_ref.set({"urls": custom_prompt_urls}, merge=True)
                st.success(f"Dodano: {new_prompt_name}")
                st.rerun()
            else:
                st.error("Wypełnij oba pola!")
    
    # Pokaż listę wszystkich promptów
    if ALL_PROMPT_URLS:
        st.write("**Dostępne prompty:**")
        for name, url in ALL_PROMPT_URLS.items():
            st.caption(f"• **{name}** → `{url[:80]}...`" if len(url) > 80 else f"• **{name}** → `{url}`")

    st.markdown("---")
    
    # --- EDYCJA OPERATORA ---
    sel_op = st.selectbox("Wybierz operatora do edycji:", OPERATORS, key="op_cfg_sel")
    cfg_ref = db.collection("operator_configs").document(sel_op)
    cfg = cfg_ref.get().to_dict() or {}

    with st.form(key=f"form_v7_{sel_op}"):
        col_a, col_b = st.columns(2)
        with col_a:
            new_pwd = st.text_input("Hasło logowania:", value=cfg.get("password", ""))
            
            # --- PRZYPISANIE PROJEKTU GCP (NA SZTYWNO) ---
            if not GCP_PROJECTS:
                st.error("⚠️ Brak GCP_PROJECT_IDS w secrets Admina!")
                key_options = ["1 - Brak projektów w konfiguracji"]
            else:
                key_options = []
                for i, p_id in enumerate(GCP_PROJECTS):
                    key_options.append(f"{i+1} - {p_id}")
            
            # Aktualnie przypisany projekt
            current_key_val = int(cfg.get("assigned_key_index", 1))
            # Upewnij się że indeks jest w zakresie
            if current_key_val < 1 or current_key_val > len(key_options):
                current_key_val = 1
            current_idx = current_key_val - 1
            
            selected_key_str = st.selectbox(
                "🔑 Przypisany projekt Vertex AI:", 
                key_options, 
                index=current_idx,
                help="Projekt jest przypisany na sztywno. Operator zawsze korzysta z tego projektu."
            )
            key_choice = int(selected_key_str.split(" - ")[0])
            
            # Pokaż co jest aktualnie
            if GCP_PROJECTS and current_key_val >= 1:
                proj_name = GCP_PROJECTS[current_key_val - 1] if current_key_val - 1 < len(GCP_PROJECTS) else "?"
                st.info(f"Aktualnie: **{proj_name}** (Klucz {current_key_val})")

            # --- PRZYPISANIE PROMPTU (NA SZTYWNO) ---
            prompt_names = list(ALL_PROMPT_URLS.keys())
            if not prompt_names:
                prompt_names = ["Brak promptów"]
            
            current_prompt_url = cfg.get("prompt_url", "")
            # Znajdź aktualny prompt po URL
            current_prompt_idx = 0
            for i, name in enumerate(prompt_names):
                if ALL_PROMPT_URLS.get(name) == current_prompt_url:
                    current_prompt_idx = i
                    break
            
            selected_prompt_name = st.selectbox(
                "📄 Przypisany prompt:",
                prompt_names,
                index=current_prompt_idx,
                help="Prompt jest przypisany na sztywno. Operator korzysta z tego promptu."
            )
            selected_prompt_url = ALL_PROMPT_URLS.get(selected_prompt_name, "")
            
            # --- ROLA ---
            roles = ["Operatorzy_DE", "Operatorzy_FR", "Operatorzy_UK/PL"]
            cur_role = cfg.get("role", "Operatorzy_DE")
            role_sel = st.selectbox("Rola:", roles, index=roles.index(cur_role) if cur_role in roles else 0)
        
        with col_b:
            new_msg = st.text_area("Wiadomość dla operatora:", value=cfg.get("admin_message", ""), height=150)
            st.write(f"Status odczytu: {'✅ Odczytano' if cfg.get('message_read', False) else '🔴 Nieodczytano'}")
            
            st.markdown("---")
            st.write("**Podgląd konfiguracji:**")
            st.json({
                "operator": sel_op,
                "projekt_gcp": GCP_PROJECTS[key_choice - 1] if GCP_PROJECTS and key_choice >= 1 and key_choice <= len(GCP_PROJECTS) else "?",
                "prompt": selected_prompt_name,
                "rola": cur_role,
            })
        
        if st.form_submit_button("💾 Zapisz ustawienia"):
            msg_changed = new_msg != cfg.get("admin_message", "")
            cfg_ref.set({
                "password": new_pwd,
                "assigned_key_index": key_choice,
                "prompt_url": selected_prompt_url,
                "prompt_name": selected_prompt_name,
                "role": role_sel,
                "admin_message": new_msg,
                "message_read": False if msg_changed else cfg.get("message_read", False),
                "updated_at": firestore.SERVER_TIMESTAMP
            }, merge=True)
            st.success(f"✅ Zapisano konfigurację dla {sel_op}!")
            st.rerun()

# ==========================================
# 🔑 ZAKŁADKA 3: STAN KLUCZY
# ==========================================
with tab_keys:
    st.title("🔑 Monitor Zużycia Kluczy")
    today_str = today.strftime("%Y-%m-%d")
    key_stats = db.collection("key_usage").document(today_str).get().to_dict() or {}
    
    k_data = []
    for i in range(1, len(GCP_PROJECTS) + 1):
        usage = key_stats.get(str(i), 0)
        proj_name = GCP_PROJECTS[i-1] if i-1 < len(GCP_PROJECTS) else "Brak projektu"
        k_data.append({"Klucz": f"Klucz {i}", "Projekt": proj_name, "Zużycie": usage})
    
    if k_data:
        df_keys = pd.DataFrame(k_data)
        st.bar_chart(df_keys.set_index("Klucz")["Zużycie"])
        st.table(df_keys)
    else:
        st.warning("Brak projektów GCP w konfiguracji.")
    
    # --- PODGLĄD PRZYPISAŃ OPERATORÓW ---
    st.markdown("---")
    st.subheader("👥 Przypisania Operatorów")
    assignments = []
    for op in OPERATORS:
        op_cfg = db.collection("operator_configs").document(op).get().to_dict() or {}
        ki = int(op_cfg.get("assigned_key_index", 0))
        proj = GCP_PROJECTS[ki - 1] if GCP_PROJECTS and 1 <= ki <= len(GCP_PROJECTS) else "Nieprzypisany"
        prompt_name = op_cfg.get("prompt_name", "Brak")
        assignments.append({
            "Operator": op,
            "Klucz": ki,
            "Projekt GCP": proj,
            "Prompt": prompt_name,
            "Rola": op_cfg.get("role", "-")
        })
    df_assign = pd.DataFrame(assignments)
    st.dataframe(df_assign, use_container_width=True, hide_index=True)
