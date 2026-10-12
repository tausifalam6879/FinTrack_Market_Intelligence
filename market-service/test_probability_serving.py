import unittest
from contextlib import ExitStack
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np
import pandas as pd
import market_intelligence as market


class ProbabilityServingTests(unittest.TestCase):
    def test_approved_output_is_not_shrunk_capped_or_shifted_by_headlines(self):
        rng = np.random.default_rng(4)
        frame = pd.DataFrame({"Close": 100*np.cumprod(1+rng.normal(0,.01,200)),
                              "Volume": rng.integers(100,1000,200)}, index=pd.bdate_range('2025-01-01',periods=200))
        selection = {"id":"approved", "name":"Test", "accuracy":.56,"balancedAccuracy":.56,
                     "precision":.56,"recall":.56,"f1":.56,"rocAuc":.59,"brierScore":.24}
        for probability in (.0, .49, .80, .99):
            with self.subTest(probability=probability), ExitStack() as stack:
                estimator = SimpleNamespace(predict_proba=lambda x:np.array([[1-probability,probability]]))
                registry = {"artifact":{"estimator":estimator,"featureColumns":list(market.FEATURE_LABELS)},
                    "metrics":{"selection":selection},
                    "run":{"id":"run", "dataset_version":"data", "model_name":"Test", "training_rows":100,
                           "holdout_rows":30,"balanced_accuracy":.56,"roc_auc":.59,"brier_score":.24,
                           "created_at":"2025-01-01","holdout_start":"2025-06-01","holdout_end":"2025-07-01"}}
                values={"_cache_get":None,"_history":frame,"approved_model":registry,
                        "market_news":{"articles":[],"sentimentScore":1,"sentimentLabel":"positive"},
                        "_macro_adjustment":{"probabilityAdjustmentPoints":5},
                        "market_snapshot":{"name":"Test","currency":"USD","dataAsOf":"2025-10-01"},
                        "market_risk_context":{},"_feature_importance":[],"_local_feature_explanation":{},
                        "_persist_research_history":200,"_record_prediction":{},"record_persistent_prediction":None}
                for name, value in values.items():
                    stack.enter_context(patch.object(market,name,return_value=value))
                stack.enter_context(patch.object(market,"_cache_put",side_effect=lambda key,value:value))
                result=market.market_prediction('TEST')
                self.assertEqual(round(probability*100,1),result['probabilityUp'])
                self.assertEqual(0,result['newsFactor']['probabilityAdjustmentPoints'])
                self.assertEqual(0,result['macroFactor']['probabilityAdjustmentPoints'])

    def test_missing_model_cannot_receive_an_invented_ai_probability(self):
        result=market._llm_grounding_issue(
            'The company has a probability of rising of 99 percent. This is a forecast based on its recent financial performance and observed market trends.',
            'Explain the company', {'predictionAvailable':False}, {})
        self.assertEqual('unsupported forecast probability without an approved model',result)
