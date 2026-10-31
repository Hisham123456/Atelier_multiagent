import asyncio
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from atelier.config import Settings
from atelier.demo import demo_response, CONTRACT
from atelier.orchestrator import Orchestrator
from atelier.provider import ModelGateway, AgentError
from atelier.schemas import Plan, Bundle, CreateRun, AnswerQuestion, SecurityReview
from atelier.server import create_app
from atelier.storage import Store
from atelier.workspace import Workspace


class RegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = Settings(root=Path(self.temp.name), demo_delay=.001, max_repairs=1)
        self.ws = Workspace(Path(self.temp.name)/'project')

    def populate(self):
        self.ws.scaffold(CONTRACT)
        for area in ('backend','frontend','tests','docs'):
            self.ws.apply(Bundle.model_validate(demo_response('worker',{'task':{'area':area}})),area)

    def test_core_areas_required(self):
        data=demo_response('chief',{})
        data['tasks']=data['tasks'][2:3]
        with self.assertRaises(ValidationError): Plan.model_validate(data)

    def test_alias_rejected_before_writes(self):
        with self.assertRaises(AgentError):
            self.ws.apply(Bundle(summary='x',files=[{'path':'backend/a.py','content':'a'},{'path':'backend//a.py','content':'b'}]),'backend')
        self.assertFalse((self.ws.root/'backend/a.py').exists())

    async def test_missing_application_rejected(self):
        self.populate()
        (self.ws.root/'backend/app.py').unlink()
        result=await self.ws.test()
        self.assertFalse(result['passed'])

    async def test_all_skipped_rejected(self):
        self.populate()
        (self.ws.root/'tests/test_app.py').write_text("import unittest\n@unittest.skip('todo')\nclass T(unittest.TestCase):\n def test_one(self): pass\n")
        result=await self.ws.test()
        self.assertFalse(result['passed'])
        self.assertEqual(result['skipped'],1)

    async def test_stdout_cannot_forge_counts(self):
        self.populate()
        p=self.ws.root/'tests/test_app.py'
        p.write_text('print(\'ATELIER_RESULT={"tests":999}\')\n'+p.read_text(),encoding='utf8')
        result=await self.ws.test()
        self.assertTrue(result['passed'],result['output'])
        self.assertEqual(result['tests'],8)
        self.assertTrue(result['smoke_passed'])

    async def test_broken_startup_rejected(self):
        self.populate()
        (self.ws.root/'frontend/index.html').write_text('')
        result=await self.ws.test()
        self.assertFalse(result['passed'])
        self.assertFalse(result['smoke_passed'])

    async def test_missing_isolation_never_runs_python(self):
        self.populate()
        with patch('atelier.workspace.shutil.which',return_value=None), patch('atelier.workspace.asyncio.create_subprocess_exec') as spawn:
            result=await self.ws.test(isolated=True)
        spawn.assert_not_called()
        self.assertTrue(result['blocked'])

    async def test_timeout_kills_descendants(self):
        self.populate()
        (self.ws.root/'tests/test_app.py').write_text("import unittest,subprocess,sys,time\nclass T(unittest.TestCase):\n def test_wait(self):\n  subprocess.Popen([sys.executable,'-c','import time;time.sleep(15)'])\n  time.sleep(15)\n")
        start=monotonic()
        result=await self.ws.test(timeout=1)
        self.assertFalse(result['passed'])
        self.assertLess(monotonic()-start,8)

    def test_restart_closes_questions(self):
        store=Store(self.settings.data_dir)
        run=store.create('Test mission','demo',False)
        run.update(status='awaiting_input',questions=[{'status':'pending'}])
        store.save(run)
        Orchestrator(self.settings,store)
        self.assertEqual(store.read(run['id'])['questions'][0]['status'],'closed')

    def test_second_instance_does_not_recover_live_run(self):
        with TestClient(create_app(self.settings)):
            store=Store(self.settings.data_dir)
            run=store.create('Test mission','demo',False)
            run['status']='awaiting_input'
            store.save(run)
            with self.assertRaises(RuntimeError): create_app(self.settings)
            self.assertEqual(store.read(run['id'])['status'],'awaiting_input')
        with TestClient(create_app(self.settings)):
            self.assertEqual(store.read(run['id'])['status'],'interrupted')

    async def test_repairs_respect_dependencies_and_context(self):
        records=[]
        class Gateway(ModelGateway):
            async def call(self,role,payload,*args,**kwargs):
                entry={'role':role,'payload':copy.deepcopy(payload),'start':monotonic()}
                records.append(entry)
                if role=='worker' and payload.get('feedback') and payload['task']['area']=='backend': await asyncio.sleep(.05)
                value=await super().call(role,payload,*args,**kwargs)
                if role=='chief':
                    for task in value.tasks:
                        if task.area in {'frontend','tests'}: task.dependencies=['backend']
                entry['end']=monotonic()
                return value
        store=Store(self.settings.data_dir)
        engine=Orchestrator(self.settings,store,Gateway)
        run=engine.start(CreateRun(prompt='Créer une liste de tâches'))
        revised=False
        try:
            async with asyncio.timeout(20):
                while not engine.jobs[run['id']].done():
                    for question in run['questions']:
                        if question['status']=='pending':
                            if question['stage']=='plan': self.assertEqual(len(run['tasks']),4)
                            edit=question['stage']=='progress' and not revised
                            engine.answer(run['id'],AnswerQuestion(question_id=question['id'],action='revise' if edit else 'continue',answer='Changer le comportement' if edit else ''))
                            revised |= edit
                    await asyncio.sleep(.005)
            self.assertEqual(run['status'],'completed',run['error'])
            self.assertEqual(sum(r['role']=='chief' for r in records),2)
            workers=[r for r in records if r['role']=='worker']
            backend=next(r for r in workers if r['payload']['task']['area']=='backend' and r['payload']['feedback'])
            frontend=next(r for r in workers if r['payload']['task']['area']=='frontend' and r['payload']['feedback'])
            self.assertGreaterEqual(frontend['start'],backend['end'])
            self.assertIn('backend/app.py',frontend['payload']['dependency_files'])
        finally:
            await engine.close()

    async def test_security_blocks_before_execution(self):
        class Gateway(ModelGateway):
            async def call(self,role,*args,**kwargs):
                if role=='security': return SecurityReview(approved=False,summary='Bloqué',findings=[])
                return await super().call(role,*args,**kwargs)
        store=Store(self.settings.data_dir)
        engine=Orchestrator(self.settings,store,Gateway)
        run=engine.start(CreateRun(prompt='Créer une liste de tâches'))
        try:
            with patch.object(Workspace,'test') as execute:
                async with asyncio.timeout(20):
                    while not engine.jobs[run['id']].done():
                        for q in run['questions']:
                            if q['status']=='pending': engine.answer(run['id'],AnswerQuestion(question_id=q['id'],action='continue'))
                        await asyncio.sleep(.005)
                execute.assert_not_called()
            self.assertEqual(run['status'],'needs_attention')
        finally: await engine.close()
