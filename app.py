import streamlit as st
from sqlalchemy import text
import bcrypt
from zoneinfo import ZoneInfo
from streamlit_cookies_controller import CookieController
import time
from datetime import datetime, timezone
import requests

# --- KONFIGURACJA API FOOTBALL-DATA ---
API_KEY = st.secrets["API_KEY"]

# --- KONFIGURACJA BAZY ---
DB_URL = st.secrets["DB_URL"]
conn = st.connection("postgresql", type="sql", url=DB_URL, pool_pre_ping=True)

# --- INICJALIZACJA CIASTECZEK ---
controller = CookieController()

# --- FUNKCJE POMOCNICZE (SZYFROWANIE) ---
def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password, hashed_password):
    return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))

# --- SILNIK AUTOMATYCZNEJ SYNCHRONIZACJI W TLE ---
@st.cache_data(ttl=60)
def synchronizuj_wyniki_i_punkty():
    if not API_KEY or API_KEY == "WKLEJ_TUTAJ_SWOJ_KLUCZ_Z_FOOTBALL_DATA":
        return 
        
    url = "https://api.football-data.org/v4/competitions/WC/matches"
    headers = {"X-Auth-Token": API_KEY.strip()}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            fixtures = response.json().get("matches", [])
            with conn.session as s:
                for f in fixtures:
                    ext_id = f["id"]
                    status = f["status"]
                    
                    h_score = f.get("score", {}).get("fullTime", {}).get("home")
                    a_score = f.get("score", {}).get("fullTime", {}).get("away")
                    
                    s.execute(text('''
                        UPDATE mecze 
                        SET status = :status, wynik_home = :h_score, wynik_away = :a_score
                        WHERE external_match_id = :ext_id
                    '''), {"status": status, "h_score": h_score, "a_score": a_score, "ext_id": ext_id})
                
                s.execute(text('''
                    UPDATE typy t
                    SET punkty = 
                        CASE 
                            WHEN t.typ_home = m.wynik_home AND t.typ_away = m.wynik_away THEN 5
                            WHEN m.wynik_home = m.wynik_away AND t.typ_home = t.typ_away THEN 3
                            WHEN (m.wynik_home > m.wynik_away AND t.typ_home > t.typ_away) OR (m.wynik_home < m.wynik_away AND t.typ_home < t.typ_away) THEN 1
                            ELSE 0
                        END
                    FROM mecze m
                    WHERE t.mecz_id = m.id AND m.wynik_home IS NOT NULL AND m.wynik_away IS NOT NULL;
                '''))
                s.commit()
    except Exception:
        pass 

synchronizuj_wyniki_i_punkty()

# --- MECHANIZM AUTO-WYLOGOWANIA (BRAK AKTYWNOŚCI) ---
LIMIT_NIEAKTYWNOSCI = 30 * 60  
obecny_czas = time.time()

c_login = controller.get("login")
c_user_id = controller.get("user_id")
c_ostatnia_aktywnosc = controller.get("ostatnia_aktywnosc")

if 'zalogowany' not in st.session_state:
    st.session_state.zalogowany = False
    st.session_state.login = ""
    st.session_state.user_id = None

if c_login and c_user_id:
    if c_ostatnia_aktywnosc:
        if obecny_czas - float(c_ostatnia_aktywnosc) > LIMIT_NIEAKTYWNOSCI:
            controller.remove("login")
            controller.remove("user_id")
            controller.remove("ostatnia_aktywnosc")
            st.session_state.zalogowany = False
            st.session_state.login = ""
            st.session_state.user_id = None
            st.warning("Twoja sesja wygasła z powodu braku aktywności. Zaloguj się ponownie.")
            time.sleep(2)
            st.rerun()
        else:
            if obecny_czas - float(c_ostatnia_aktywnosc) > 60:
                controller.set("ostatnia_aktywnosc", str(obecny_czas))
            st.session_state.zalogowany = True
            st.session_state.login = c_login
            st.session_state.user_id = int(c_user_id)
    else:
        controller.set("ostatnia_aktywnosc", str(obecny_czas))
        st.session_state.zalogowany = True
        st.session_state.login = c_login
        st.session_state.user_id = int(c_user_id)
else:
    st.session_state.zalogowany = False
    st.session_state.login = ""
    st.session_state.user_id = None

# --- WIDOK NIEZALOGOWANEGO UŻYTKOWNIKA ---
if not st.session_state.zalogowany:
    st.title("Typer Mundial 🏆")
    
    tab_logowanie, tab_rejestracja = st.tabs(["Zaloguj się", "Zarejestruj się"])
    
    with tab_logowanie:
        st.subheader("Logowanie")
        log_login = st.text_input("Login", key="log_login")
        log_haslo = st.text_input("Hasło", type="password", key="log_haslo")
        
        if st.button("Zaloguj"):
            with conn.session as s:
                result = s.execute(text("SELECT id, haslo_hash FROM uzytkownicy WHERE login = :login"), {"login": log_login}).fetchone()
                
                if result and verify_password(log_haslo, result[1]):
                    controller.set("login", log_login)
                    controller.set("user_id", str(result[0]))
                    controller.set("ostatnia_aktywnosc", str(obecny_czas))
                    time.sleep(0.5) 
                    st.session_state.zalogowany = True
                    st.session_state.login = log_login
                    st.session_state.user_id = result[0]
                    st.rerun()
                else:
                    st.error("Nieprawidłowy login lub hasło.")
                    
    with tab_rejestracja:
        st.subheader("Nowe konto")
        rej_login = st.text_input("Wybierz login", key="rej_login")
        rej_haslo = st.text_input("Hasło", type="password", key="rej_haslo")
        rej_haslo2 = st.text_input("Powtórz hasło", type="password", key="rej_haslo2")
        
        if st.button("Zarejestruj się"):
            if rej_haslo != rej_haslo2:
                st.error("Hasła nie są identyczne!")
            elif len(rej_login) < 3:
                st.error("Login musi mieć minimum 3 znaki.")
            else:
                with conn.session as s:
                    exists = s.execute(text("SELECT id FROM uzytkownicy WHERE login = :login"), {"login": rej_login}).fetchone()
                    if exists:
                        st.error("Użytkownik o takim loginie już istnieje.")
                    else:
                        hashed = hash_password(rej_haslo)
                        s.execute(text("INSERT INTO uzytkownicy (login, haslo_hash) VALUES (:login, :haslo)"), {"login": rej_login, "haslo": hashed})
                        s.commit()
                        st.success("Konto założone! Możesz się teraz zalogować w zakładce obok.")

# --- WIDOK ZALOGOWANEGO UŻYTKOWNIKA (GŁÓWNA APLIKACJA) ---
else:
    st.title(f"Witaj, {st.session_state.login}! 👋")
    
    if st.button("Wyloguj"):
        controller.remove("login")
        controller.remove("user_id")
        controller.remove("ostatnia_aktywnosc")
        time.sleep(0.5)
        st.session_state.zalogowany = False
        st.session_state.login = ""
        st.session_state.user_id = None
        st.rerun()

    with st.expander("⚙️ Ustawienia konta (Zmiana hasła)"):
        obecne_haslo = st.text_input("Obecne hasło", type="password", key="zmiana_obecne")
        nowe_haslo = st.text_input("Nowe hasło", type="password", key="zmiana_nowe")
        nowe_haslo2 = st.text_input("Powtórz nowe hasło", type="password", key="zmiana_nowe2")
        
        if st.button("Zmień moje hasło"):
            if nowe_haslo != nowe_haslo2:
                st.error("Nowe hasła nie są identyczne!")
            elif len(nowe_haslo) < 3:
                st.error("Nowe hasło musi mieć minimum 3 znaki.")
            else:
                with conn.session as s:
                    result = s.execute(
                        text("SELECT haslo_hash FROM uzytkownicy WHERE id = :uid"), 
                        {"uid": st.session_state.user_id}
                    ).fetchone()
                    
                    if result and verify_password(obecne_haslo, result[0]):
                        nowy_hash = hash_password(nowe_haslo)
                        s.execute(
                            text("UPDATE uzytkownicy SET haslo_hash = :nowy_hash WHERE id = :uid"),
                            {"nowy_hash": nowy_hash, "uid": st.session_state.user_id}
                        )
                        s.commit()
                        st.success("Twoje hasło zostało zmienione!")
                    else:
                        st.error("Obecne hasło jest nieprawidłowe.")

   # --- UKRYTY PANEL ADMINISTRATORA ---
    if st.session_state.login == "maniekfhuj":
        st.divider()
        st.subheader("🛠️ Panel Administratora")
        
        # 1. Zarządzanie użytkownikami (Usuwanie kont)
        with st.expander("👤 Zarządzanie użytkownikami"):
            with conn.session as s:
                users = s.execute(text("SELECT id, login FROM uzytkownicy WHERE login != 'maniekfhuj'")).fetchall()
                lista_userow_del = {u[1]: u[0] for u in users}
            
            if lista_userow_del:
                wybrany_user_del = st.selectbox("Wybierz użytkownika do usunięcia", list(lista_userow_del.keys()))
                if st.button("❌ USUŃ UŻYTKOWNIKA", type="primary"):
                    with conn.session as s:
                        s.execute(text("DELETE FROM uzytkownicy WHERE id = :uid"), {"uid": lista_userow_del[wybrany_user_del]})
                        s.commit()
                    st.success(f"Użytkownik {wybrany_user_del} został trwale usunięty!")
                    time.sleep(1.5)
                    st.rerun()
            else:
                st.info("Brak innych użytkowników w systemie.")

        # 2. Reset hasła znajomemu
        with st.expander("🔑 Resetuj hasło znajomemu"):
            with conn.session as s:
                users = s.execute(text("SELECT login FROM uzytkownicy WHERE login != 'maniekfhuj'")).fetchall()
                lista_userow = [u[0] for u in users]
                
            if lista_userow:
                wybrany_user = st.selectbox("Wybierz użytkownika", lista_userow, key="reset_user")
                nowe_haslo = st.text_input("Podaj nowe, tymczasowe hasło (np. 12345)", type="password")
                
                if st.button("Zmień hasło", type="primary", key="btn_zmiana_hasla"):
                    if len(nowe_haslo) >= 3:
                        hashed = hash_password(nowe_haslo)
                        with conn.session as s:
                            s.execute(
                                text("UPDATE uzytkownicy SET haslo_hash = :hash WHERE login = :login"),
                                {"hash": hashed, "login": wybrany_user}
                            )
                            s.commit()
                        st.success(f"Zmieniono hasło dla {wybrany_user}! Możesz mu je teraz przekazać.")
                    else:
                        st.error("Hasło musi mieć minimum 3 znaki.")
            else:
                st.info("Brak innych użytkowników w systemie.")
        
        # 3. Synchronizacja API
        with st.expander("⚽ Opcje Administratora (Synchronizacja)"):
            st.warning("Użyj tego przycisku tylko, jeśli chcesz pobrać listę meczów od zera. Wyniki meczów odświeżają się same w tle.")
            if st.button("Pobierz / Napraw mecze Mundialu", type="primary", key="btn_pobierz_mecze"):
                url = "https://api.football-data.org/v4/competitions/WC/matches"
                headers = {"X-Auth-Token": API_KEY.strip()}
                with st.spinner("Pobieranie danych z Football-Data.org..."):
                    try:
                        response = requests.get(url, headers=headers)
                        data = response.json()
                        if response.status_code == 200 and "matches" in data:
                            fixtures = data["matches"]
                            with conn.session as s:
                                for f in fixtures:
                                    ext_id = f["id"]
                                    data_meczu = f["utcDate"] 
                                    status_meczu = f["status"]
                                    home_team = f["homeTeam"]["name"] if f.get("homeTeam") and f["homeTeam"].get("name") else "TBD"
                                    away_team = f["awayTeam"]["name"] if f.get("awayTeam") and f["awayTeam"].get("name") else "TBD"
                                    
                                    s.execute(text('''
                                        INSERT INTO mecze (druzyna_home, druzyna_away, data_rozpoczecia, status, external_match_id)
                                        VALUES (:home, :away, :data, :status, :ext_id)
                                        ON CONFLICT (external_match_id) DO UPDATE 
                                        SET data_rozpoczecia = :data, status = :status, 
                                            druzyna_home = :home, druzyna_away = :away;
                                    '''), {"home": home_team, "away": away_team, "data": data_meczu, "status": status_meczu, "ext_id": ext_id})
                                s.commit()
                            st.success(f"Sukces! Zsynchronizowano {len(fixtures)} meczów Mundialu.")
                            time.sleep(1.5)
                            st.rerun()
                        else:
                            st.error(f"Błąd API: {data.get('message', 'Nieznany błąd')}")
                    except Exception as e:
                        st.error(f"Połączenie nie powiodło się: {e}")

        # 4. Ręczne testy aplikacji
        with st.expander("📝 Ręczne dodawanie i edycja meczów (Do testów)"):
            st.markdown("### Krok 1: Dodaj sztuczny mecz")
            col_h, col_a = st.columns(2)
            with col_h:
                nowy_home = st.text_input("Gospodarz (np. Polska)")
            with col_a:
                nowy_away = st.text_input("Gość (np. Brazylia)")
            
            col_d, col_t = st.columns(2)
            with col_d:
                nowa_data = st.date_input("Data meczu")
            with col_t:
                nowy_czas = st.time_input("Godzina rozpoczęcia (polski czas)")
                
            if st.button("➕ Dodaj ten mecz do bazy", type="primary", key="btn_dodaj_mecz"):
                if nowy_home and nowy_away:
                    dt_local = datetime.combine(nowa_data, nowy_czas).replace(tzinfo=ZoneInfo("Europe/Warsaw"))
                    dt_utc = dt_local.astimezone(timezone.utc)
                    fake_id = int(time.time()) # Mniejsze fałszywe ID, żeby baza to przyjęła bez błędu
                    
                    with conn.session as s:
                        s.execute(text('''
                            INSERT INTO mecze (druzyna_home, druzyna_away, data_rozpoczecia, status, external_match_id)
                            VALUES (:home, :away, :data, 'SCHEDULED', :ext_id)
                        '''), {"home": nowy_home, "away": nowy_away, "data": dt_utc, "ext_id": fake_id})
                        s.commit()
                    st.success("Sztuczny mecz dodany! Możesz go teraz obstawić.")
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error("Wpisz nazwy obu drużyn!")

            st.divider()
            st.markdown("### Krok 2: Wpisz wynik i przydziel punkty")
            with conn.session as s:
                mecze_do_edycji = s.execute(text("SELECT id, druzyna_home, druzyna_away FROM mecze ORDER BY data_rozpoczecia ASC")).fetchall()
                opcje_meczow = {m[0]: f"{m[1]} vs {m[2]}" for m in mecze_do_edycji}
                
            if opcje_meczow:
                wybrany_mecz = st.selectbox("Wybierz mecz do wprowadzenia wyniku", options=list(opcje_meczow.keys()), format_func=lambda x: opcje_meczow[x])
                
                col_wh, col_wa = st.columns(2)
                with col_wh:
                    wynik_h = st.number_input("Gole - Gospodarz", min_value=0, step=1, key="edycja_h")
                with col_wa:
                    wynik_a = st.number_input("Gole - Gość", min_value=0, step=1, key="edycja_a")
                    
                if st.button("💾 Zapisz wynik i rozdaj punkty", type="primary", key="btn_zapisz_wynik"):
                    with conn.session as s:
                        s.execute(text('''
                            UPDATE mecze 
                            SET status = 'FINISHED', wynik_home = :h, wynik_away = :a
                            WHERE id = :mid
                        '''), {"h": wynik_h, "a": wynik_a, "mid": wybrany_mecz})
                        
                        s.execute(text('''
                            UPDATE typy t
                            SET punkty = 
                                CASE 
                                    WHEN t.typ_home = m.wynik_home AND t.typ_away = m.wynik_away THEN 5
                                    WHEN m.wynik_home = m.wynik_away AND t.typ_home = t.typ_away THEN 3
                                    WHEN (m.wynik_home > m.wynik_away AND t.typ_home > t.typ_away) OR (m.wynik_home < m.wynik_away AND t.typ_home < t.typ_away) THEN 1
                                    ELSE 0
                                END
                            FROM mecze m
                            WHERE t.mecz_id = m.id AND m.wynik_home IS NOT NULL AND m.wynik_away IS NOT NULL;
                        '''))
                        s.commit()
                    st.success("Gotowe! Wynik zaktualizowany, a punkty trafiły do Tabeli Liderów.")
                    time.sleep(1.5)
                    st.rerun()

    # --- TABELA RANKINGOWA ---
    st.divider()
    st.header("🏆 Tabela Liderów")
    with conn.session as s:
        # Sumujemy punkty dla każdego gracza, ALE wykluczamy konto maniekfhuj z rankingów
        ranking = s.execute(text('''
            SELECT u.login, SUM(COALESCE(t.punkty, 0)) as total_pkt
            FROM uzytkownicy u
            LEFT JOIN typy t ON u.id = t.uzytkownik_id
            WHERE u.login != 'maniekfhuj'
            GROUP BY u.login
            ORDER BY total_pkt DESC, u.login ASC
        ''')).fetchall()
        
        if ranking:
            ranking_data = [{"Miejsce": i+1, "Gracz": r[0], "Suma Punktów": r[1]} for i, r in enumerate(ranking)]
            st.dataframe(ranking_data, hide_index=True, width="stretch")
        else:
            st.info("Brak graczy do wyświetlenia.")

    # --- WIDOK GŁÓWNY (LISTA MECZÓW I TYPOWANIE) ---
    st.divider()
    st.subheader("📅 Nadchodzące mecze do typowania")
    
    with conn.session as s:
        typy_usera = s.execute(
            text("SELECT mecz_id, typ_home, typ_away FROM typy WHERE uzytkownik_id = :uid"), 
            {"uid": st.session_state.user_id}
        ).fetchall()
        slownik_typow = {t[0]: (t[1], t[2]) for t in typy_usera}

        wszystkie_typy = s.execute(text('''
            SELECT t.mecz_id, u.login, t.typ_home, t.typ_away, t.punkty 
            FROM typy t 
            JOIN uzytkownicy u ON t.uzytkownik_id = u.id
            ORDER BY t.punkty DESC, u.login ASC
        ''')).fetchall()
        
        slownik_wszystkich_typow = {}
        for mid, login, th, ta, pkt in wszystkie_typy:
            if mid not in slownik_wszystkich_typow:
                slownik_wszystkich_typow[mid] = []
            slownik_wszystkich_typow[mid].append((login, th, ta, pkt))

        mecze = s.execute(text('''
            SELECT id, druzyna_home, druzyna_away, data_rozpoczecia, status, wynik_home, wynik_away 
            FROM mecze 
            ORDER BY data_rozpoczecia ASC
        ''')).fetchall()
        
        if not mecze:
            st.info("Brak meczów w bazie.")
        else:
            for mecz in mecze:
                mecz_id, home, away, data_utc, status, wynik_h, wynik_a = mecz
                
                data_pl = data_utc.astimezone(ZoneInfo("Europe/Warsaw"))
                czas_format = data_pl.strftime("%d.%m.%Y, godz. %H:%M")
                obecny_czas_utc = datetime.now(timezone.utc)
                
                mozna_typowac = False
                status_pl = status
                
                if status == "TIMED" or status == "SCHEDULED": 
                    if obecny_czas_utc < data_utc:
                        status_pl = "Zaplanowany"
                        mozna_typowac = True
                    else:
                        status_pl = "Rozpoczęty (Zakłady w toku)"
                        mozna_typowac = False
                elif status == "FINISHED": status_pl = "Zakończony"
                elif status == "IN_PLAY": status_pl = "W trakcie"
                elif status == "PAUSED": status_pl = "Przerwa"
                
                wynik_wyswietl = f"&nbsp;&nbsp;{wynik_h} : {wynik_a}&nbsp;&nbsp;" if wynik_h is not None else "&nbsp;&nbsp;⚔️&nbsp;&nbsp;"
                st.markdown(f"#### {home} {wynik_wyswietl} {away}")
                st.caption(f"🕒 **{czas_format}** | Status: {status_pl}")
                
                obecny_typ = slownik_typow.get(mecz_id)
                
                if mozna_typowac:
                    col1, col2, col3, col4 = st.columns([1.5, 0.5, 1.5, 2])
                    wartosc_home = obecny_typ[0] if obecny_typ else 0
                    wartosc_away = obecny_typ[1] if obecny_typ else 0
                    
                    with col1:
                        typ_h = st.number_input("H", min_value=0, max_value=20, step=1, value=wartosc_home, key=f"h_{mecz_id}", label_visibility="collapsed")
                    with col2:
                        st.markdown("<h3 style='text-align: center; margin-top: -10px;'>:</h3>", unsafe_allow_html=True)
                    with col3:
                        typ_a = st.number_input("A", min_value=0, max_value=20, step=1, value=wartosc_away, key=f"a_{mecz_id}", label_visibility="collapsed")
                    with col4:
                        etykieta_przycisku = "Zaktualizuj typ" if obecny_typ else "Zapisz typ"
                        if st.button(etykieta_przycisku, key=f"btn_{mecz_id}", width="stretch"):
                            with conn.session as s_zapis:
                                if obecny_typ:
                                    s_zapis.execute(text('''
                                        UPDATE typy SET typ_home = :th, typ_away = :ta 
                                        WHERE uzytkownik_id = :uid AND mecz_id = :mid
                                    '''), {"th": typ_h, "ta": typ_a, "uid": st.session_state.user_id, "mid": mecz_id})
                                else:
                                    s_zapis.execute(text('''
                                        INSERT INTO typy (uzytkownik_id, mecz_id, typ_home, typ_away) 
                                        VALUES (:uid, :mid, :th, :ta)
                                    '''), {"uid": st.session_state.user_id, "mid": mecz_id, "th": typ_h, "ta": typ_a})
                                s_zapis.commit()
                            st.toast(f"Zapisano typ {typ_h}:{typ_a} dla {home} vs {away}", icon="✅")
                            time.sleep(0.5)
                            st.rerun()
                else:
                    if obecny_typ:
                        punkty_info = ""
                        if wynik_h is not None:
                            moje_pkt = next((pkt for login, th, ta, pkt in slownik_wszystkich_typow.get(mecz_id, []) if login == st.session_state.login), 0)
                            punkty_info = f"🏆 **Zdobyte punkty: {moje_pkt}**"
                        st.info(f"Twój typ: **{obecny_typ[0]} : {obecny_typ[1]}** 🔒 {punkty_info}")
                    else:
                        st.warning("Nie wytypowano tego meczu. 🔒")
                        
                    typy_dla_meczu = slownik_wszystkich_typow.get(mecz_id, [])
                    if typy_dla_meczu:
                        with st.expander("👀 Zobacz, jak obstawili inni znajomi"):
                            for gracz_login, gracz_th, gracz_ta, gracz_pkt in typy_dla_meczu:
                                znacznik_pkt = f" *(Pkt: {gracz_pkt})*" if wynik_h is not None else ""
                                if gracz_login == st.session_state.login:
                                    st.markdown(f"👤 **{gracz_login} (Ty)**: {gracz_th} : {gracz_ta}{znacznik_pkt}")
                                else:
                                    st.markdown(f"👤 **{gracz_login}**: {gracz_th} : {gracz_ta}{znacznik_pkt}")
                    else:
                        with st.expander("👀 Zobacz, jak obstawili inni znajomi"):
                            st.caption("Nikt nie obstawił tego meczu.")
                            
                st.divider()