# ClutchDATA

Aplikacja webowa do sprawdzania statystyk CS2.

## Struktura projektu

- `app/` - kod aplikacji FastAPI
- `app/api/` - endpointy i routery
- `app/core/` - konfiguracja aplikacji
- `app/db/` - obsługa bazy danych i modele
- `app/models/` - domenowe modele danych
- `app/schemas/` - schematy Pydantic dla request/response
- `app/services/` - logika pobierania i przetwarzania statystyk
- `app/utils/` - pomocnicze funkcje
- `tests/` - testy jednostkowe

## Uruchomienie

1. Utwórz środowisko wirtualne:
   ```bash
   python -m venv venv
   .\\venv\\Scripts\\activate
   ```
2. Zainstaluj zależności:
   ```bash
   pip install -r requirements.txt
   ```
3. Uruchom serwer:
   ```bash
   uvicorn app.main:app --reload
   ```

## Kolejne kroki

- dodać integrację z API CS2 lub lokalną bazę statystyk
- napisać endpointy do wyszukiwania graczy, meczów i clutchów
- zbudować interfejs frontendowy lub API dla dashboardu
