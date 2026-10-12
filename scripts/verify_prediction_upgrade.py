"""Acceptance checks for a staged probability/research API revision."""
import argparse
import json
from production_smoke_test import request_json

parser = argparse.ArgumentParser()
parser.add_argument('--api', required=True)
args = parser.parse_args()
base=args.api.rstrip('/')
health=request_json(base+'/health/ready')
assert health['status']=='ready'
approved=request_json(base+'/market/analysis?symbol=RELIANCE.NS&refresh=true')
assert approved['model']['servingMode']=='approved_artifact'
assert approved['model']['localExplanation']['probabilityPath']['method']=='estimator_probability'
assert approved['probabilityUp']==approved['model']['rawTechnicalProbabilityUp']
research=request_json(base+'/market/analysis?symbol=INFY.NS&refresh=true')
assert research.get('history')
if research.get('predictionAvailable') is False:
    assert research['probabilityUp'] is None
agent=request_json(base+'/market/agent', {'symbol':'INFY.NS',
    'message':'Explain the observed company fundamentals in English. Use only the available financial evidence.'})
assert agent.get('llmUsed') is True and agent.get('llmProvider')=='gemini', 'Real Gemini response required'
assert agent.get('llmAnswerAccepted') is True, 'Grounded Gemini response required'
print(json.dumps({'status':'upgrade_verified','health':'ready','probabilityMethod':'estimator_probability',
                  'researchHistory':'available','predictionAvailable':research.get('predictionAvailable'),
                  'externalAI':agent['llmStatus']}))
