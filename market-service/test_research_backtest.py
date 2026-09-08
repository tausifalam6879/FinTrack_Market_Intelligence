import unittest
import numpy as np
import pandas as pd
from research_backtest import simulate_backtest

class BacktestTests(unittest.TestCase):
    def frame(self):
        rng=np.random.default_rng(31)
        close=100*np.cumprod(1+rng.normal(.0005,.01,240))
        return pd.DataFrame({'Open':close*(1+rng.normal(0,.002,240)),'Close':close,'Volume':rng.integers(100,900,240)},index=pd.bdate_range('2024-01-01',periods=240))

    def test_chronological_audit_costs_and_finite_metrics(self):
        frame=self.frame()
        free=simulate_backtest(frame,0);paid=simulate_backtest(frame,20)
        self.assertGreater(paid['observations'],50)
        self.assertLessEqual(paid['strategyReturnPercent'],free['strategyReturnPercent'])
        self.assertTrue(all(r['trainingThrough']<r['firstSignal'] for r in paid['audit']))
        self.assertLessEqual(paid['maximumDrawdownPercent'],0)

    def test_future_prices_do_not_change_earlier_results(self):
        frame=self.frame();before=simulate_backtest(frame)
        modified=frame.copy();modified.iloc[-20:,modified.columns.get_loc('Close')]*=1.2
        modified.iloc[-20:,modified.columns.get_loc('Open')]*=1.2
        after=simulate_backtest(modified)
        self.assertEqual(before['curve'][:30],after['curve'][:30])

    def test_rejects_insufficient_history_and_invalid_cost(self):
        with self.assertRaises(ValueError):simulate_backtest(self.frame().head(80))
        with self.assertRaises(ValueError):simulate_backtest(self.frame(),-1)

    def test_handler_returns_result_and_handles_insufficient_data(self):
        from fastapi import HTTPException
        from unittest.mock import patch
        from research_backtest import backtest
        with patch('research_backtest._cache_get',return_value=None), patch('research_backtest._history',return_value=self.frame()):
            response=backtest('AAPL')
        self.assertEqual('AAPL',response['symbol'])
        with patch('research_backtest._cache_get',return_value=None), patch('research_backtest._history',return_value=self.frame().head(50)):
            with self.assertRaises(HTTPException) as error:backtest('AAPL')
        self.assertEqual(422,error.exception.status_code)

if __name__=='__main__':unittest.main()
