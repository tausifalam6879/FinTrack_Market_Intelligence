"""Staged checks for question-scoped research and cited document retrieval."""
from __future__ import annotations

import argparse
import json
import re
import time

from production_smoke_test import request_json


def validate_agent(data, symbol, *, documents=False):
    if data.get("symbol") != symbol or not str(data.get("answer") or "").strip():
        raise ValueError(f"{symbol}: missing answer or incorrect company")
    tools = data.get("toolsUsed") or []
    if "technical_prediction" in tools:
        raise ValueError(f"{symbol}: unrelated model analysis still runs")
    timings = data.get("timings") or {}
    if not all(type(timings.get(key)) in (int, float) and timings[key] >= 0 for key in ("evidenceMs", "totalMs")):
        raise ValueError(f"{symbol}: updated research timing fields missing")
    if documents:
        if tools != ["company_document_rag"]:
            raise ValueError(f"{symbol}: report question fetched unrelated tools")
        citations = data.get("citations") or []
        allowed = {f"[{item['citation']} p.{item['page']}]".lower() for item in citations}
        used = set(re.findall(r"\[s\d+ p\.\d+\]", data["answer"].lower()))
        if citations and (not used or not used.issubset(allowed)):
            raise ValueError(f"{symbol}: invalid report citations")
        if not citations and data.get("llmAnswerAccepted") is not False:
            raise ValueError(f"{symbol}: accepted a report answer without passages")
    elif "company_fundamentals" not in tools:
        raise ValueError(f"{symbol}: missing company evidence")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--symbols", default="INFY.NS,AAPL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    health = request_json(base + "/health/ready", timeout=60)
    if health.get("status") != "ready":
        raise ValueError("Updated service is not ready")
    for symbol in [item.strip() for item in args.symbols.split(",") if item.strip()]:
        for documents, question in (
            (False, "Explain this company's basic fundamentals"),
            (True, "What does the annual report say about the company's business?"),
        ):
            started = time.monotonic()
            response = request_json(base + "/market/agent", {"symbol": symbol, "message": question}, timeout=75)
            validate_agent(response, symbol, documents=documents)
            print(json.dumps({"symbol": symbol, "request": "report" if documents else "fundamentals",
                              "elapsedSeconds": round(time.monotonic() - started, 2),
                              "tools": response["toolsUsed"], "llmStatus": response.get("llmStatus"),
                              "citationCount": len(response.get("citations") or []),
                              "timings": response["timings"]}), flush=True)
    print("Question routing, response timing and report citation checks passed.", flush=True)


if __name__ == "__main__":
    main()
