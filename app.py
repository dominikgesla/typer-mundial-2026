import streamlit as st
from sqlalchemy import text
import bcrypt
from zoneinfo import ZoneInfo
from streamlit_cookies_controller import CookieController
import time
from datetime import datetime, timezone
import requests

st.set_page_config(
    page_title="Typer Mundial 2026",
    page_icon="🏆",                   
    layout="centered"                 
)

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

# --- RDZEŃ POBIERANIA WYNIKÓW ---
@st.cache_data(ttl=60)
def pobierz_wyniki_z_api():
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

# --- INTELIGENTNY AUTOMAT AKTUALIZACJI Z OKNAMI CZASOWYMI ---
def automatyczna_synchronizacja():
    with conn.session as s:
        aktywne_mecze = s.execute(text('''
            SELECT id, data_rozpoczecia FROM mecze 
            WHERE data_rozpoczecia <= :teraz 
            AND status NOT IN ('FINISHED', 'AWARDED', 'CANCELLED')
        '''), {"teraz": datetime.now(timezone.utc)}).fetchall()
        
        if not aktywne_mecze:
            return

    teraz = datetime.now(timezone.utc)
    czy_odpytac_api = False
    
    for mecz in aktywne_mecze:
        start_meczu = mecz[1]
        minuty_od_startu = (teraz - start_meczu).total_seconds() / 60.0
        
        # 1. Okno: Przerwa (od 45 do 55 minuty)
        if 45 <= minuty_od_startu <= 55:
            czy_odpytac_api = True
            break
        # 2. Okno: Koniec meczu (od 105 do 120 minuty)
        elif 105 <= minuty_od_startu <= 120:
            czy_odpytac_api = True
            break
        # 3. Nadrabianie nocnych meczów (więcej niż 120 minut i wciąż brak statusu FINISHED)
        elif minuty_od_startu > 180:
            czy_odpytac_api = True
            break

    if czy_odpytac_api:
        pobierz_wyniki_z_api()

# Uruchomienie automatu w tle
automatyczna_synchronizacja()

# --- MECHANIZM AUTO-WYLOGOWANIA (BRAK AKTYWNOŚCI) ---
LIMIT_NIEAKTYWNOSCI = 259200 
obecny_czas = time.time()

c_login = controller.get("login")
c_user_id = controller.get("user_id")
c_ostatnia_aktywnosc = controller.get("ostatnia_aktywnosc")

if not c_login:
    time.sleep(0.5)
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
        st.markdown("<div style='text-align: center; margin-top: 15px; opacity: 0.7; font-size: 0.9em;'>🔑 Zapomniałeś hasła? Skontaktuj się z majstrem adminem</div>", unsafe_allow_html=True)
                    
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
    if st.session_state.login == "admin":
        st.divider()
        st.subheader("🛠️ Panel Administratora")
        
        with st.expander("👤 Zarządzanie użytkownikami"):
            with conn.session as s:
                users = s.execute(text("SELECT id, login FROM uzytkownicy WHERE login != 'admin'")).fetchall()
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

        with st.expander("🔑 Resetuj hasło użytkownikowi"):
            with conn.session as s:
                users = s.execute(text("SELECT login FROM uzytkownicy WHERE login != 'admin'")).fetchall()
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
        
        with st.expander("⚽ Opcje Administratora (Synchronizacja)"):
            st.warning("Użyj tego przycisku tylko, jeśli chcesz pobrać listę meczów od zera.")
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
                    fake_id = int(time.time()) 
                    
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
        ranking = s.execute(text('''
            SELECT u.login, SUM(COALESCE(t.punkty, 0)) as total_pkt
            FROM uzytkownicy u
            LEFT JOIN typy t ON u.id = t.uzytkownik_id
            WHERE u.login != 'admin'
            GROUP BY u.login
            ORDER BY total_pkt DESC, u.login ASC
        ''')).fetchall()
        
        if ranking:
            ranking_data = [{"Miejsce": i+1, "Gracz": r[0], "Suma Punktów": r[1]} for i, r in enumerate(ranking)]
            st.dataframe(ranking_data, hide_index=True, width="stretch")
        else:
            st.info("Brak graczy do wyświetlenia.")

    # --- WIDOK GŁÓWNY (LISTA MECZÓW I RĘCZNE ODŚWIEŻANIE) ---
    st.divider()
    
    col_tytul, col_odswiez = st.columns([2.5, 1.5])
    with col_tytul:
        st.subheader("📅 Terminarz i Typy")
    with col_odswiez:
        if st.button("🔄 Odśwież wyniki", width="stretch", type="primary"):
            with st.spinner("Pobieranie najnowszych danych..."):
                pobierz_wyniki_z_api()
            st.rerun()

    # --- PANEL Z ZASADAMI PUNKTACJI ---
    with st.expander("ℹ️ Zobacz zasady punktacji turnieju"):
        st.markdown("""
        **System naliczania punktów za każdy mecz:**
        * 🎯 **5 punktów** – **Dokładny wynik** (trafiony idealnie w punkt, np. Twój typ: *2:1*, wynik meczu: *2:1*)
        * ⚖️ **3 punkty** – **Trafiony remis** (wytypowany remis i padł remis, ale inny stosunek bramek, np. Twój typ: *1:1*, wynik meczu: *2:2*)
        * 👍 **1 punkt** – **Trafiony zwycięzca** (wytypowany dobry zwycięzca, ale inny wynik, np. Twój typ: *1:0*, wynik meczu: *3:1*)
        * ❌ **0 punktów** – **Błędny typ** (nietrafiony ani zwycięzca, ani remis)
            
        *Możliwość dodawania i edycji typów zostaje automatycznie zablokowana w momencie planowanego rozpoczęcia meczu.*
        """)
            
    with conn.session as s:
        # 1. Pobieranie danych z bazy
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
           # 2. Segregacja meczów do odpowiednich koszyków
            mecze_aktywne = []
            mecze_zakonczone = []
            mecze_kalendarz = {}
            brak_typow_48h = 0  # <--- INICJALIZACJA NASZEGO INTELIGENTNEGO LICZNIKA

            for mecz in mecze:
                mecz_id, home, away, data_utc, status, wynik_h, wynik_a = mecz
                
                data_pl = data_utc.astimezone(ZoneInfo("Europe/Warsaw"))
                czas_format = data_pl.strftime("%d.%m.%Y, godz. %H:%M")
                dzien_klucz = data_pl.strftime("%d.%m.%Y")
                obecny_czas_utc = datetime.now(timezone.utc)
                
                mozna_typowac = False
                status_pl = status
                
                if status == "TIMED" or status == "SCHEDULED": 
                    if obecny_czas_utc < data_utc:
                        status_pl = "Zaplanowany"
                        mozna_typowac = True
                        
                        # --- INTELIGENTNY SYSTEM ALERTÓW (48H + Odrzucenie TBD) ---
                        sekundy_do_meczu = (data_utc - obecny_czas_utc).total_seconds()
                        if sekundy_do_meczu <= 48 * 3600:  # 48 godzin przeliczone na sekundy
                            if "TBD" not in home.upper() and "TBD" not in away.upper():
                                if mecz_id not in slownik_typow:
                                    brak_typow_48h += 1
                                    
                    else:
                        status_pl = "Rozpoczęty (Zakłady zamknięte)"
                        mozna_typowac = False
                elif status == "FINISHED": status_pl = "Zakończony"
                elif status == "IN_PLAY": status_pl = "W trakcie"
                elif status == "PAUSED": status_pl = "Przerwa"
                
                # Zwijamy wszystko w jeden "pakiet" informacyjny
                pakiet = (mecz_id, home, away, czas_format, status_pl, mozna_typowac, wynik_h, wynik_a)

                # Rozdzielanie do zakładek (Zakończone vs Reszta)
                if status in ["FINISHED", "AWARDED"]:
                    mecze_zakonczone.append(pakiet)
                else:
                    mecze_aktywne.append(pakiet)

                # Grupowanie do Kalendarza
                if dzien_klucz not in mecze_kalendarz:
                    mecze_kalendarz[dzien_klucz] = []
                mecze_kalendarz[dzien_klucz].append(pakiet)

           # 3. Funkcje pomocnicze
            def zapisz_typ_callback(m_id, pref, czy_aktualizacja, druzyna_h, druzyna_a):
                val_h = st.session_state[f"h_{m_id}_{pref}"]
                val_a = st.session_state[f"a_{m_id}_{pref}"]
                
                with conn.session as s_zapis:
                    if czy_aktualizacja:
                        s_zapis.execute(text('''
                            UPDATE typy SET typ_home = :th, typ_away = :ta 
                            WHERE uzytkownik_id = :uid AND mecz_id = :mid
                        '''), {"th": val_h, "ta": val_a, "uid": st.session_state.user_id, "mid": m_id})
                    else:
                        s_zapis.execute(text('''
                            INSERT INTO typy (uzytkownik_id, mecz_id, typ_home, typ_away) 
                            VALUES (:uid, :mid, :th, :ta)
                        '''), {"uid": st.session_state.user_id, "mid": m_id, "th": val_h, "ta": val_a})
                    s_zapis.commit()
                
                # --- TWARDY RESET PAMIĘCI WIDŻETÓW (OSTATECZNY FIX DLA iOS) ---
                for zakladka in ["nad", "zak", "kal"]:
                    if f"h_{m_id}_{zakladka}" in st.session_state:
                        del st.session_state[f"h_{m_id}_{zakladka}"]
                    if f"a_{m_id}_{zakladka}" in st.session_state:
                        del st.session_state[f"a_{m_id}_{zakladka}"]

            def renderuj_mecz(pakiet_meczu, prefix_zakladki):
                mid, m_home, m_away, m_czas, m_status, m_mozna, m_wh, m_wa = pakiet_meczu
                
                wynik_wyswietl = f"&nbsp;&nbsp;{m_wh} : {m_wa}&nbsp;&nbsp;" if m_wh is not None else "&nbsp;&nbsp;⚔️&nbsp;&nbsp;"
                st.markdown(f"#### {m_home} {wynik_wyswietl} {m_away}")
                
                obecny_t = slownik_typow.get(mid)
                
                if m_mozna:
                    if not obecny_t:
                        alert_braku = "<span style='color: #ff4b4b; font-weight: bold;'>🚨 BRAK TYPU!</span> | "
                    else:
                        alert_braku = "<span style='color: #888888; font-weight: 500;'>✅ Typ zapisany</span> | "
                else:
                    alert_braku = ""
                    
                st.markdown(f"<div style='display: block; min-height: 35px; font-size: 1.15em; opacity: 0.8; margin-bottom: 15px;'>{alert_braku}🕒 <b>{m_czas}</b> | Status: <b>{m_status}</b></div>", unsafe_allow_html=True)
                
                if m_mozna:
                    val_h = obecny_t[0] if obecny_t else 0
                    val_a = obecny_t[1] if obecny_t else 0
                    
                    with st.form(key=f"form_{mid}_{prefix_zakladki}", border=False):
                        c1, c2, c3, c4 = st.columns([1.5, 0.5, 1.5, 2])
                        with c1:
                            t_h = st.number_input("H", min_value=0, max_value=20, step=1, value=val_h, key=f"h_{mid}_{prefix_zakladki}", label_visibility="collapsed")
                        with c2:
                            st.markdown("<h3 style='text-align: center; margin-top: -10px;'>:</h3>", unsafe_allow_html=True)
                        with c3:
                            t_a = st.number_input("A", min_value=0, max_value=20, step=1, value=val_a, key=f"a_{mid}_{prefix_zakladki}", label_visibility="collapsed")
                        with c4:
                            etykieta = "Zaktualizuj typ" if obecny_t else "Zapisz typ"
                            typ_przycisku = "secondary" if obecny_t else "primary"
                            
                            st.form_submit_button(
                                etykieta, 
                                width="stretch", 
                                type=typ_przycisku,
                                on_click=zapisz_typ_callback,
                                args=(mid, prefix_zakladki, bool(obecny_t), m_home, m_away)
                            )
                else:
                    if obecny_t:
                        punkty_info = ""
                        if m_wh is not None:
                            moje_pkt = next((pkt for login, th, ta, pkt in slownik_wszystkich_typow.get(mid, []) if login == st.session_state.login), 0)
                            punkty_info = f"🏆 **Zdobyte punkty: {moje_pkt}**"
                        st.info(f"Twój typ: **{obecny_t[0]} : {obecny_t[1]}** 🔒 {punkty_info}")
                    else:
                        st.warning("Nie wytypowano tego meczu. 🔒")
                        
                    typy_dla_m = slownik_wszystkich_typow.get(mid, [])
                    if typy_dla_m:
                        with st.expander("👀 Zobacz, jak obstawili inni gracze"):
                            for g_log, g_th, g_ta, g_pkt in typy_dla_m:
                                z_pkt = f" *(Pkt: {g_pkt})*" if m_wh is not None else ""
                                if g_log == st.session_state.login:
                                    st.markdown(f"👤 **{g_log} (Ty)**: {g_th} : {g_ta}{z_pkt}")
                                else:
                                    st.markdown(f"👤 **{g_log}**: {g_th} : {g_ta}{z_pkt}")
                    else:
                        with st.expander("👀 Zobacz, jak obstawili inni gracze"):
                            st.caption("Nikt nie obstawił tego meczu.")
                st.divider()

                st.markdown("<div id='gora-strony'></div>", unsafe_allow_html=True)

            # 4. Rysowanie frontu aplikacji (Zakładki)
            tab_nadchodzace, tab_zakonczone, tab_kalendarz = st.tabs(["⏳ Nadchodzące", "✅ Zakończone", "📅 Kalendarz"])
            
            with tab_nadchodzace:
                if brak_typow_48h > 0:
                    st.error(f"🚨 Brak typów na najbliższe 48h: **{brak_typow_48h}**")

                if not mecze_aktywne:
                    st.success("Wszystkie aktualne mecze zostały już rozegrane!")
                else:
                    for p in mecze_aktywne:
                        renderuj_mecz(p, prefix_zakladki="nad")
                    
                    # --- PRZYCISK POWROTU NA GÓRĘ ---
                    st.markdown("""
                        <a href="#gora-strony" target="_self" style="text-decoration: none;">
                            <div style="background-color: #ff4b4b; color: white; text-align: center; padding: 10px; border-radius: 8px; margin-top: 25px; font-weight: bold; cursor: pointer;">
                                ⬆️ Wróć na górę strony
                            </div>
                        </a>
                    """, unsafe_allow_html=True)

            with tab_zakonczone:
                if not mecze_zakonczone:
                    st.info("Brak zakończonych meczów w bazie.")
                else:
                    # Funkcja reversed() odwraca listę - najświeższe wyniki są na samej górze
                    for p in reversed(mecze_zakonczone):
                        renderuj_mecz(p, prefix_zakladki="zak")

            with tab_kalendarz:
                for dzien, lista_meczow in mecze_kalendarz.items():
                    # Tworzymy zwijany panel dla każdej daty
                    with st.expander(f"📁 Mecze z dnia: {dzien}"):
                        for p in lista_meczow:
                            renderuj_mecz(p, prefix_zakladki=f"kal_{dzien}")