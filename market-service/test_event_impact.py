import unittest
import pandas as pd
from event_impact import event_window

class EventImpactTests(unittest.TestCase):
    def test_exact_dates_and_excess_returns(self):
        frame=pd.DataFrame({'Close':[100,110,120,130,140,150]},index=pd.bdate_range('2024-01-05',periods=6))
        benchmark=pd.DataFrame({'Close':[100,105,110,115,120,125]},index=frame.index)
        result=event_window(frame,'2024-01-06',benchmark)
        self.assertEqual('2024-01-05',result['baselineDate'])
        self.assertEqual('2024-01-08',result['firstSession'])
        self.assertEqual(10,result['windows'][0]['returnPercent'])
        self.assertEqual(5,result['windows'][0]['excessReturnPoints'])
        self.assertEqual('not_yet_available',result['windows'][2]['status'])

    def test_missing_benchmark_date_is_not_forward_filled(self):
        frame=pd.DataFrame({'Close':[100,110,120]},index=pd.bdate_range('2024-01-01',periods=3))
        result=event_window(frame,'2024-01-02',frame.iloc[[0,2]])
        self.assertIsNone(result['windows'][0]['benchmarkReturnPercent'])
        with self.assertRaises(ValueError):event_window(frame,'2024-01-01')
        with self.assertRaises(ValueError):event_window(frame,'not-a-date')

if __name__=='__main__':unittest.main()
