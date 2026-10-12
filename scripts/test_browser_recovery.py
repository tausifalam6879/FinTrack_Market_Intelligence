"""Disposable synthetic SQL backup -> restored API/gateway -> real React browser.

Uses local Docker only. No cloud credentials or production records are required.
Build the three fintrack-rehearsal images before running this integration check.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, timeout=kwargs.pop('timeout',180), **kwargs)

name='fintrack-browser-fixture-'+uuid.uuid4().hex[:10]
network=name+'-net'
try:
    run('docker','network','create','--internal',network)
    run('docker','run','-d','--rm','--name',name,'--network',network,'--tmpfs','/var/lib/mysql',
        '-e','MYSQL_ALLOW_EMPTY_PASSWORD=yes','-e','MYSQL_DATABASE=fintrack_restore',
        '-e','MYSQL_USER=rehearsal','-e','MYSQL_PASSWORD=synthetic-test-password','mysql:8.4')
    for _ in range(60):
        logs=run('docker','logs',name)
        if b'MySQL init process done' in logs.stdout+logs.stderr:
            break
        time.sleep(2)
    else:
        raise RuntimeError('Fixture database did not initialize')
    code='''from persistence import Database
from data_pipeline import bars_from_frame
import numpy as np, pandas as pd
d=Database(); d.initialize_schema()
rng=np.random.default_rng(14)
close=100*np.cumprod(1+rng.normal(0.001,.01,250))
frame=pd.DataFrame({"Open":close,"High":close*1.01,"Low":close*.99,"Close":close,"Adj Close":close,"Volume":1000},index=pd.bdate_range("2025-01-01",periods=250))
d.upsert_company({"symbol":"TEST.NS","name":"Synthetic test only","source":"synthetic"})
d.upsert_market_bars(bars_from_frame("TEST.NS",frame))
'''
    run('docker','run','--rm','--network',network,
        '-e','MYSQL_HOST='+name,'-e','MYSQL_PORT=3306','-e','MYSQL_DATABASE=fintrack_restore',
        '-e','MYSQL_USER=rehearsal','-e','MYSQL_PASSWORD=synthetic-test-password',
        'fintrack-rehearsal-api:local','python','-c',code)
    dump=run('docker','exec',name,'mysqldump','-uroot','--single-transaction','--no-tablespaces',
             '--set-gtid-purged=OFF','fintrack_restore').stdout
    directory=Path(tempfile.mkdtemp(prefix='fintrack-browser-test-'))
    backup=directory/'synthetic.sql'
    backup.write_bytes(dump)
    backup.with_suffix('.sql.manifest.json').write_text(json.dumps({'format':'mysql-sql','sha256':hashlib.sha256(dump).hexdigest()}))
    subprocess.run([sys.executable,str(Path(__file__).with_name('rehearse_mysql_restore.py')),
                    str(backup),'--application','--browser'],check=True,timeout=480)
    print('Synthetic browser recovery verified; report: '+str(backup.with_suffix('.sql.restore-report.json')))
finally:
    subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=30)
    subprocess.run(['docker','network','rm',network],capture_output=True,timeout=30)
