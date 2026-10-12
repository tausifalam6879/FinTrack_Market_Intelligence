"""Run inside recovered API. Read credentials from stdin, never print them."""
import json
import os
import sys

settings = json.load(sys.stdin)
for key in ("GEMINI_API_KEY", "GEMINI_MODEL", "LLM_MODEL"):
    if settings.get(key):
        os.environ[key] = settings[key]
os.environ["LLM_PROVIDER"] = "gemini"
os.environ["GEMINI_TIMEOUT_MS"] = "25000"

from persistence import Database
from market_intelligence import _provider_chat

database = Database()
symbols = database.operational_symbols()
if not symbols:
    raise RuntimeError("Restored database has no symbols")
symbol = symbols[0]
bars = database.load_market_bars(symbol)
last = bars[-1]
# Send only public market facts from the recovered store, no personal records.
evidence = {"symbol": symbol, "session": str(last["session_date"]), "close": float(last["close"])}
try:
    answer, provider = _provider_chat([
        {"role": "system", "content": "Explain the supplied historical observation in 2 sentences. Include the exact symbol and session date. State that it is historical data, not a forecast. Do not invent predictions or additional numbers."},
        {"role": "user", "content": json.dumps(evidence)},
    ])
    if provider != "gemini" or symbol not in answer or evidence["session"] not in answer or "histor" not in answer.lower():
        raise RuntimeError("Provider did not return the required grounded response")
except Exception as error:
    print(json.dumps({"status": "external_ai_failed", "errorType": type(error).__name__}))
    raise SystemExit(1)
print(json.dumps({"status": "external_ai_verified", "provider": provider,
                  "symbol": symbol, "session": evidence["session"],
                  "scope": "Real Gemini call using public price evidence from recovered database; no deterministic fallback"}))
