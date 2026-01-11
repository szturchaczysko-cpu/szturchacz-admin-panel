# --- SEKCJA: KONFIGURACJA OPERATORÓW ---
st.markdown("---")
st.header("🎮 Centrum Sterowania Operatorami")

OPERATORS_LIST = ["Emilia", "Oliwia", "Iwona", "Marlena", "Magda", "Sylwia", "Ewelina", "Klaudia", "Marta"]
ROLES_LIST = ["Operatorzy_DE", "Operatorzy_FR", "Operatorzy_UK/PL"]

selected_op_to_config = st.selectbox("Wybierz operatora do konfiguracji:", OPERATORS_LIST)

# Pobierz aktualną konfigurację z bazy
op_cfg_ref = db.collection("operator_configs").document(selected_op_to_config)
current_cfg = op_cfg_ref.get().to_dict() or {}

with st.form(f"config_form_{selected_op_to_config}"):
    col1, col2 = st.columns(2)
    
    with col1:
        # Wybór klucza: 0 oznacza brak przypisania (stare zasady), 1-5 to konkretne klucze
        key_choice = st.number_input(
            "Przypisany klucz API (0 = Rotator, 1-5 = Stały klucz)", 
            min_value=0, max_value=5, 
            value=current_cfg.get("assigned_key_index", 0)
        )
    
    with col2:
        role_choice = st.selectbox(
            "Przypisana rola:", 
            ROLES_LIST, 
            index=ROLES_LIST.index(current_cfg.get("role", "Operatorzy_DE")) if current_cfg.get("role") in ROLES_LIST else 0
        )
    
    admin_msg = st.text_area("Wiadomość do operatora (widoczna w jego panelu bocznym):", value=current_cfg.get("admin_message", ""))
    
    if st.form_submit_button("Zapisz ustawienia dla: " + selected_op_to_config):
        op_cfg_ref.set({
            "assigned_key_index": key_choice,
            "role": role_choice,
            "admin_message": admin_msg,
            "updated_at": firestore.SERVER_TIMESTAMP
        }, merge=True)
        st.success(f"Ustawienia dla {selected_op_to_config} zostały zaktualizowane!")
