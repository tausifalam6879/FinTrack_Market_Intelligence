import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from deep_learning import train_pytorch_mlp_experiment
from market_intelligence import FEATURE_LABELS


class DeepLearningExperimentTests(unittest.TestCase):
    def _dataset(self, rows: int = 220) -> pd.DataFrame:
        generator = np.random.default_rng(17)
        index = pd.bdate_range("2025-01-01", periods=rows)
        frame = pd.DataFrame(
            generator.normal(0, 1, (rows, len(FEATURE_LABELS))),
            columns=list(FEATURE_LABELS),
            index=index,
        )
        score = frame["return_1"] * 0.45 - frame["volatility_10"] * 0.20
        noise = generator.normal(0, 0.45, rows)
        frame["target"] = ((score + noise) > 0).astype(int)
        return frame

    def test_seeded_mlp_is_reproducible_and_keeps_holdout_out_of_tuning(self):
        dataset = self._dataset()
        training = dataset.iloc[:180]
        holdout = dataset.iloc[180:]
        with tempfile.TemporaryDirectory() as directory:
            first = train_pytorch_mlp_experiment(
                training,
                holdout,
                list(FEATURE_LABELS),
                Path(directory) / "first.pt",
                max_epochs=60,
                patience=8,
            )
            second = train_pytorch_mlp_experiment(
                training,
                holdout,
                list(FEATURE_LABELS),
                Path(directory) / "second.pt",
                max_epochs=60,
                patience=8,
            )

        self.assertEqual(1, first["dataSplit"]["purgeGapRows"])
        self.assertLess(
            first["dataSplit"]["fit"]["end"],
            first["dataSplit"]["validation"]["start"],
        )
        self.assertLess(
            first["dataSplit"]["validation"]["end"],
            first["dataSplit"]["untouchedHoldout"]["start"],
        )
        self.assertAlmostEqual(
            first["holdoutMetrics"]["balancedAccuracy"],
            second["holdoutMetrics"]["balancedAccuracy"],
            places=7,
        )
        self.assertEqual(
            first["earlyStopping"]["bestEpoch"],
            second["earlyStopping"]["bestEpoch"],
        )


if __name__ == "__main__":
    unittest.main()
