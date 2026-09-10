#!/usr/bin/env python3
"""GRETL + real Garage publication tests. Creates and removes only its own containers/network.
Does not touch the running Compose stack or its volumes. Git pushes use a disposable bare repo.
"""
from pathlib import Path
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.request
import urllib.error

STACK=Path(__file__).resolve().parents[1]
TOPICS=STACK.parent/'datenportal-themenrepo'
IMAGE=os.environ.get('DATENPORTAL_JENKINS_IMAGE','datenportal-jenkins:local')
WORK=Path(tempfile.mkdtemp(prefix='datenportal-publication-'))
NET='dp-publication-'+secrets.token_hex(5)
print('Integration artifacts:',WORK,flush=True)
containers=[]
DATASET='ch.so.bevoelkerung.altersstruktur'
REL=Path('statistikdienst')/DATASET/('meta-'+DATASET+'.xtf')
REPO=WORK/'repo'
shutil.copytree(TOPICS,REPO,ignore=shutil.ignore_patterns('.git','.gradle','build','.DS_Store'))
OUTPUT=REPO/'statistikdienst/build/publication/outputs'
(WORK/'control.json').write_text('{}')

def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs).stdout.strip()

def service(name,image,*args,env=None,volumes=()):
    full=NET+'-'+name
    cmd=['docker','run','-d','--name',full,'--network',NET,'--network-alias',name]
    if env:
        f=WORK/(name+'.env');f.write_text('\n'.join(k+'='+v for k,v in env.items())+'\n');f.chmod(0o600)
        cmd+=['--env-file',str(f)]
    for volume in volumes:cmd+=['-v',volume]
    if name=='proxy':cmd+=['-p','127.0.0.1::8000']
    run(*cmd,image,*args);containers.append(full)

def git(*args):return run('git','-C',str(REPO),*args)
def control(**kwargs): (WORK/'control.json').write_text(json.dumps(kwargs))

def gradle(name,extra=(),root=False,success=True,write=False):
    project='/test/repo' if root else '/test/repo/statistikdienst'
    command=['docker','run','--rm','--network',NET,'--user','jenkins','--env-file',str(WORK/'gradle.env'),
        '-v',str(WORK)+':/test','-v',str(STACK.parent/'datenportal-pilot-daten')+':/pilot:ro','--entrypoint','/bin/bash',IMAGE,
        '-c','/usr/local/bin/configure-duckdb-extensions.sh; git config --global --add safe.directory /test/repo; exec "$@"','bash',
        '/test/repo/shared/bin/gradlew-java17.sh','--no-daemon','-I','/test/repo/shared/gradle/init.gradle','-p',project,
        'initializePublication' if root else 'publishToDatenportal']
    if not root:command+=['-Pdataset='+DATASET]
    if write:command+=['-PgitWriteBack=true','-PtopicRepositoryMode=managed-git','-PtopicRepositoryUrl=file:///test/accepted.git',
        '-PtopicRepositoryBranch=main','-PgitBaseRevision='+git('rev-parse','HEAD'),'-PgitCommitterName=Test','-PgitCommitterEmail=test@example.invalid']
    print(name,flush=True)
    with (WORK/(name+'.log')).open('w') as stream:
        result=subprocess.run(command+list(extra),stdout=stream,stderr=subprocess.STDOUT)
    if (result.returncode==0)!=success:
        raise AssertionError(name+'\n'+'\n'.join((WORK/(name+'.log')).read_text().splitlines()[-45:]))
    return json.loads(((REPO/'build/publication/outputs' if root else OUTPUT)/'report.json').read_text())

try:
    run('docker','network','create',NET)
    config=(STACK/'services/garage/garage.toml.template').read_text()
    for key in ('RPC_SECRET','ADMIN_TOKEN','METRICS_TOKEN'):config=config.replace('__'+key+'__',secrets.token_hex(32))
    (WORK/'garage.toml').write_text(config)
    key='GK'+secrets.token_hex(16); secret=secrets.token_hex(32)
    service('garage','dxflrs/garage:v2.3.0','/garage','server','--single-node','--default-bucket',
        env={'GARAGE_DEFAULT_ACCESS_KEY':key,'GARAGE_DEFAULT_SECRET_KEY':secret,'GARAGE_DEFAULT_BUCKET':'ch.so.daten'},
        volumes=[str(WORK/'garage.toml')+':/etc/garage.toml:ro'])
    for _ in range(40):
        try:run('docker','exec',NET+'-garage','/garage','status');break
        except subprocess.CalledProcessError:time.sleep(.5)
    service('browser','rclone/rclone:1.75.1','serve','http','test:ch.so.daten','--addr',':8080','--read-only','--dir-cache-time','0s',
        env={'RCLONE_CONFIG_TEST_TYPE':'s3','RCLONE_CONFIG_TEST_PROVIDER':'Other','RCLONE_CONFIG_TEST_ACCESS_KEY_ID':key,
            'RCLONE_CONFIG_TEST_SECRET_ACCESS_KEY':secret,'RCLONE_CONFIG_TEST_REGION':'garage',
            'RCLONE_CONFIG_TEST_ENDPOINT':'http://garage:3900','RCLONE_CONFIG_TEST_FORCE_PATH_STYLE':'true'})
    shutil.copy(STACK/'scripts/testing/publication-proxy.py',WORK/'proxy.py')
    service('proxy','python:3.12-alpine','python','/test/proxy.py',volumes=[str(WORK)+':/test'])
    port=run('docker','port',NET+'-proxy','8000/tcp').rsplit(':',1)[1]
    public='http://127.0.0.1:'+port+'/public/current.json'
    for _ in range(60):
        try:
            urllib.request.urlopen(public, timeout=2).close()
            break
        except urllib.error.HTTPError as error:
            if error.code == 404: break
        except OSError: pass
        time.sleep(.5)
    else: raise AssertionError('Temporary public gateway did not become ready')
    def current():
        with urllib.request.urlopen(public,timeout=10) as response:return json.load(response)
    (WORK/'gradle.env').write_text('\n'.join(k+'='+v for k,v in {
        'ORG_GRADLE_PROJECT_s3Publish':'true','ORG_GRADLE_PROJECT_s3Endpoint':'http://proxy:8000',
        'ORG_GRADLE_PROJECT_s3Region':'garage','ORG_GRADLE_PROJECT_s3BucketName':'ch.so.daten',
        'ORG_GRADLE_PROJECT_s3AccessKey':key,'ORG_GRADLE_PROJECT_s3SecretKey':secret,'ORG_GRADLE_PROJECT_s3Acl':'private',
        'ORG_GRADLE_PROJECT_publicationManifestUrl':'http://proxy:8000/public/current.json',
        'ORG_GRADLE_PROJECT_catalogDownloadBase':'http://proxy:8000/public',
        'ORG_GRADLE_PROJECT_portalReloadUrl':'http://proxy:8000/reload','ORG_GRADLE_PROJECT_portalReloadToken':'local-test-token',
        'JENKINS_RUNTIME_MODE':'dev'}.items())+'\n')
    (WORK/'gradle.env').chmod(0o600)
    git('init','-b','main');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
    git('add','--all');git('commit','-m','fixture')
    run('git','clone','--bare',str(REPO),str(WORK/'accepted.git'))
    git('remote','add','origin','file:///test/accepted.git')
    report=gradle('initialize',root=True)
    assert report['publication']=='accepted' and current()['catalog'] is None
    gradle('initialize-again',root=True,success=False)
    data=['-PdataFile=/pilot/'+DATASET+'/so_bevo_altersstruktur_2025.csv','-PseriesId=2025']
    report=gradle('data-and-git',data+['-PreloadPortal=true'],write=True)
    assert report['publication']=='accepted' and report['git']=='pushed' and report['reload']=='succeeded', report
    assert git('diff-tree','--no-commit-id','--name-only','-r','HEAD').splitlines()==[str(REL)]
    baseline=current()
    control(fail_catalog=True)
    gradle('partial-xtf-upload',['-PpublicationMode=repository-metadata'],success=False)
    assert current()==baseline
    control()
    hook=WORK/'accepted.git/hooks/pre-receive';hook.write_text('#!/bin/sh\nexit 1\n');hook.chmod(0o755)
    # Change metadata to guarantee a Git commit rather than a no-op.
    delivered=WORK/'changed.xtf';delivered.write_text((REPO/REL).read_text().replace('Altersstruktur','Altersstruktur Test'))
    report=gradle('push-rejected',['-PmetadataFile=/test/changed.xtf'],write=True,success=False)
    assert current()==baseline and report['git']=='failed'
    hook.unlink()
    control(fail_pointer=True)
    report=gradle('pointer-failure',['-PpublicationMode=repository-metadata'],success=False)
    assert current()==baseline and report['publication']=='not-published'
    control(lose_pointer_response=True)
    report=gradle('pointer-response-lost',['-PpublicationMode=repository-metadata'],success=False)
    assert current()['releaseId']==report['releaseId'] and report['publication']=='accepted'
    control(reload_failure=True)
    report=gradle('reload-failure',['-PpublicationMode=repository-metadata','-PreloadPortal=true'],success=False)
    assert current()['releaseId']==report['releaseId'] and report['reload']=='failed'
    control()
    baseline=current()
    report=gradle('preview',['-PpublicationMode=repository-metadata','-Ps3Publish=false','-PreloadPortal=true'])
    assert current()==baseline and report['mode']=='preview' and report['reload']=='not-requested'
    source_sheet=(REPO/REL).read_bytes()
    source_head=git('rev-parse','HEAD')
    for label in ['working-tree-first','working-tree-next']:
        baseline=current()
        report=gradle(label,['-PpublicationMode=repository-metadata','-PtopicRepositoryMode=working-tree'])
        assert report['sourceReleaseId']==baseline['releaseId']
        assert current()['releaseId']==report['releaseId']
        assert (REPO/REL).read_bytes()==source_sheet and git('rev-parse','HEAD')==source_head
        assert report['git']=='not-requested'
    print('PASS: real Garage, public readback, Git gate and publication failure scenarios',flush=True)
finally:
    for container in reversed(containers):
        with (WORK/(container+'.log')).open('w') as log:
            subprocess.run(['docker','logs',container],stdout=log,stderr=subprocess.STDOUT)
        subprocess.run(['docker','rm','-f',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['docker','network','rm',NET],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    print('Artifacts:',WORK,flush=True)
