"""Executed only inside the isolated rehearsal API container."""
import json
import sys
import numpy as np
import pandas as pd
from model_registry import approved_model

results = []
for symbol in json.loads(sys.argv[1]):
    model = approved_model(symbol)
    if not model:
        raise RuntimeError("Approved recovered model missing")
    artifact = model["artifact"]
    frame = pd.DataFrame([artifact["explainabilityReference"]], columns=artifact["featureColumns"])
    probabilities = artifact["estimator"].predict_proba(frame)
    if probabilities.shape != (1, 2) or not np.isfinite(probabilities).all():
        raise RuntimeError("Invalid recovered inference output")
    if not ((probabilities >= 0).all() and (probabilities <= 1).all() and np.allclose(probabilities.sum(axis=1), 1)):
        raise RuntimeError("Invalid recovered probabilities")
    results.append({"symbol": symbol, "runId": model["run"]["id"],
                    "status": "inference_verified", "probabilityShape": list(probabilities.shape)})
print(json.dumps(results))
