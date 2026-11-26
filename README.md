# health-coach

Osobisty asystent treningowo-zdrowotny. Pobiera dane z Garmin Connect, Withings i Fitatu,
zapisuje je lokalnie (SQLite) i udostępnia coacha opartego o LLM (Anthropic Claude lub lokalny
Ollama jako fallback) przez prosty interfejs web (FastAPI).

## Funkcje

- Synchronizacja aktywności i danych dziennych z Garmin Connect.
- Pomiary masy / składu ciała z Withings.
- Dane żywieniowe z Fitatu.
- Coach LLM: analiza sesji, plany treningowe, rekomendacje żywieniowe i regeneracyjne.

## Wymagania

- Python 3.11+
- Konto Garmin Connect, (opcjonalnie) Withings i Fitatu
- Klucz API Anthropic **lub** lokalny Ollama

## Instalacja

```bash
pip install -r requirements.txt
```

## Konfiguracja

1. Skopiuj `.env.example` do `.env` i uzupełnij wartości:
   ```bash
   cp .env.example .env
   ```
2. Skopiuj szablon profilu i dostosuj do siebie:
   ```bash
   cp prompts/profile.example.md prompts/profile.md
   ```

> `.env`, `prompts/profile.md`, baza `health.db*` oraz katalog `data/` są ignorowane przez git —
> zawierają dane osobowe i poświadczenia. Nigdy ich nie commituj.

## Uruchomienie

```bash
uvicorn app.main:app --reload
```

Aplikacja wystartuje domyślnie na `http://localhost:8000`.

## Struktura

- `app/` - backend FastAPI, integracje (garmin / withings / fitatu), coach LLM, DB.
- `app/static/` - frontend (HTML/CSS/JS).
- `prompts/` - prompty coacha (profil użytkownika trzymany lokalnie).
