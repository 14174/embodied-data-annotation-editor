"""Exercise bootstrap orchestration without installing packages or user services."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class DeployTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()/'checkout with spaces'
        self.root.mkdir()
        source = Path(__file__).resolve().parents[1]
        self.script = self.root/'deploy.sh'
        if (source/'deploy.sh').exists():
            shutil.copyfile(source/'deploy.sh', self.script)
        (self.root/'requirements.txt').write_text('fixture\n')
        self.dataset = self.root/'data set'
        (self.dataset/'meta').mkdir(parents=True)
        (self.dataset/'meta/info.json').write_text('{}')
        self.log = self.root/'calls.jsonl'
        python = self.root/'bootstrap-python'
        python.write_text('''#!/usr/bin/env python3
import json,os,pathlib,sys
with open(os.environ['DEPLOY_TEST_LOG'],'a') as log:log.write(json.dumps(sys.argv[1:])+'\\n')
if sys.argv[1:3]==['-m','venv']:
    target=pathlib.Path(sys.argv[3])/'bin/python';target.parent.mkdir(parents=True)
    target.symlink_to(pathlib.Path(__file__).resolve())
if sys.argv[1:3]==['-m','pip'] and os.environ.get('DEPLOY_TEST_PIP_FAIL'):sys.exit(7)
''')
        python.chmod(0o755)
        ctl = self.root/'annotationctl'
        ctl.write_text('''#!/usr/bin/env python3
import json,os,sys
with open(os.environ['DEPLOY_TEST_LOG'],'a') as log:log.write(json.dumps(['annotationctl',*sys.argv[1:]])+'\\n')
''')
        ctl.chmod(0o755)
        self.env = dict(os.environ, ANNOTATION_PYTHON=str(python), DEPLOY_TEST_LOG=str(self.log))

    def run_deploy(self, *args):
        return subprocess.run(['bash',str(self.script),*map(str,args)],env=self.env,text=True,capture_output=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_first_start_creates_environment_installs_requirements_and_preserves_path_arguments(self):
        output = self.root/'human labels'
        result = self.run_deploy(self.dataset,output,'--port','18081','--collection-root',self.root/'collections')
        self.assertEqual(result.returncode,0,result.stderr)
        calls = self.calls()
        self.assertIn(['-m','venv',str(self.root/'.venv')],calls)
        self.assertIn(['-m','pip','install','-r',str(self.root/'requirements.txt')],calls)
        self.assertEqual(calls[-1],['annotationctl','platform','run','--dataset',str(self.dataset),
                                   '--output',str(output),'--port','18081','--collection-root',str(self.root/'collections')])

    def test_failed_dependency_install_does_not_start_platform(self):
        self.env['DEPLOY_TEST_PIP_FAIL']='1'
        result=self.run_deploy(self.dataset,self.root/'labels')
        self.assertEqual(result.returncode,7,result.stderr)
        self.assertFalse(any(call[0]=='annotationctl' for call in self.calls()))

    def test_service_flag_delegates_install_with_original_options(self):
        for tool in ['systemctl','systemd-analyze']:
            stub=self.root/tool
            stub.write_text('#!/usr/bin/env bash\nexit 0\n')
            stub.chmod(0o755)
        self.env['PATH']=str(self.root)+os.pathsep+self.env['PATH']
        result=self.run_deploy(self.dataset,self.root/'labels','--service','--port','18082')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.calls()[-1],['annotationctl','platform','install','--dataset',str(self.dataset),
                                          '--output',str(self.root/'labels'),'--port','18082'])

    def test_default_start_reuses_existing_environment(self):
        result=self.run_deploy(self.dataset,self.root/'labels')
        self.assertEqual(result.returncode,0,result.stderr)
        first=len(self.calls())
        result=self.run_deploy(self.dataset,self.root/'labels')
        self.assertEqual(result.returncode,0,result.stderr)
        repeated=self.calls()[first:]
        self.assertFalse(any(call[:2]==['-m','venv'] for call in repeated))
        self.assertEqual(repeated[-1],['annotationctl','platform','run','--dataset',str(self.dataset),
                                      '--output',str(self.root/'labels')])

    def test_help_and_missing_dataset_do_not_install_anything(self):
        result=self.run_deploy('--help')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--service',result.stdout)
        self.assertEqual(self.calls(),[])
        result=self.run_deploy(self.root/'missing',self.root/'labels')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.calls(),[])


if __name__=='__main__':
    unittest.main()
