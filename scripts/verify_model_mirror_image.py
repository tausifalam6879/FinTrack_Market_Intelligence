"""Check approved-model identities and inference in a network-disabled image."""
import argparse
import json
from pathlib import Path
import subprocess
import uuid

from production_smoke_test import request_json

WORKER = r'''
import hashlib,json,os,sys
from pathlib import Path
import joblib,numpy as np,pandas as pd
from artifact_storage import resolve_artifact
expected=json.load(sys.stdin)
root=Path(os.environ['MODEL_ARTIFACT_DIR'])
assert os.environ.get('MODEL_ARTIFACT_OFFLINE_ONLY')=='true'
assert not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
found={}; verified=0; unavailable=0
for path in sorted(root.glob('*.joblib')):
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.name==digest+'.joblib', 'Invalid model file checksum'
    resolve_artifact('gs://'+os.environ['MODEL_ARTIFACT_BUCKET']+'/models/'+path.name,root,digest)
    verified+=1
    try:
        artifact=joblib.load(path)
    except (ImportError,RuntimeError,AttributeError):
        unavailable+=1
        continue
    if not isinstance(artifact,dict): continue
    symbol=artifact.get('symbol')
    spec=expected.get(symbol)
    if not spec or artifact.get('modelRunId')!=spec['id']: continue
    assert symbol not in found, 'Duplicate approved artifact identity'
    assert artifact.get('datasetVersion')==spec['datasetVersion'], 'Dataset identity mismatch'
    frame=pd.DataFrame([artifact['explainabilityReference']],columns=artifact['featureColumns'])
    probability=artifact['estimator'].predict_proba(frame)
    assert probability.shape==(1,2) and np.isfinite(probability).all()
    assert (probability>=0).all() and (probability<=1).all() and np.allclose(probability.sum(axis=1),1)
    found[symbol]={'runId':spec['id'],'artifactSha256':digest,'probabilityShape':list(probability.shape)}
assert set(found)==set(expected), 'Required approved models missing or unloadable: '+str(sorted(set(expected)-set(found)))
print(json.dumps({'status':'offline_inference_verified','network':'none','googleCredentialsSupplied':False,
                  'modelFilesVerified':verified,'unloadableNonRequiredArtifacts':unavailable,'approvedModels':found}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='fintrack-market-mirror:recovery')
    parser.add_argument('--api', default='https://fintrack-gateway-304232323336.asia-south1.run.app')
    parser.add_argument('--symbols', nargs='+', required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    expected = {}
    for symbol in args.symbols:
        data = request_json(args.api.rstrip('/') + '/market/model-status?symbol=' + symbol)
        model = data.get('approvedModel') or {}
        if model.get('status') != 'approved' or not model.get('id') or not model.get('datasetVersion'):
            raise ValueError(f'{symbol}: no approved model identity available.')
        expected[symbol] = {'id': model['id'], 'datasetVersion': model['datasetVersion']}
    name = 'fintrack-model-verify-' + uuid.uuid4().hex[:12]
    try:
        result = subprocess.run([
            'docker', 'run', '--name', name, '--rm', '-i', '--network', 'none', '--read-only', '--memory', '512m',
            '--cpus', '1', '--pids-limit', '128', '--tmpfs', '/tmp:rw,size=32m',
            '-e', 'OPENBLAS_NUM_THREADS=1', '-e', 'OMP_NUM_THREADS=1', '-e', 'MKL_NUM_THREADS=1',
            '--entrypoint', 'python', args.image, '-c', WORKER,
        ], input=json.dumps(expected), text=True, capture_output=True, timeout=180)
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Offline model verification failed: ' + result.stderr[-3000:])
    report = json.loads(result.stdout)
    report['scope'] = 'Local image inference for requested approved identities; Render deployment/database integration not verified.'
    if args.report:
        root = (Path(__file__).resolve().parents[1] / 'backups').resolve()
        target = args.report.resolve()
        if not target.is_relative_to(root) or target.exists():
            raise ValueError('Report must be a new file inside ignored backups/.')
        target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
