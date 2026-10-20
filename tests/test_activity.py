import threading
import unittest
from types import SimpleNamespace
from h3video.web import App


class ActivityTests(unittest.TestCase):
    def test_current_tasks_exclude_finished_and_historical_errors(self):
        jobs = [dict(id='done', status='completed', prompt='old output'),
                dict(id='failed', status='failed', prompt='old failure'),
                dict(id='live', status='running', title='current', prompt='', scenes=[dict(status='completed'), dict(status='in_progress', stage='디코딩')]),
                dict(id='next', status='pending', prompt='waiting')]
        app = SimpleNamespace(store=SimpleNamespace(list=lambda: jobs), worker=SimpleNamespace(queue=['next']),
            studio=SimpleNamespace(lock=threading.RLock(), active={'editor': dict(id='editor', title='Editing', task=dict(status='queued', message='편집 대기'))}),
            motion=SimpleNamespace(lock=threading.RLock(), active={'motion'}, get=lambda _: dict(title='Render', task=dict(status='running'))),
            references=SimpleNamespace(lock=threading.RLock(), active={}))
        result = App.activity(app)
        self.assertEqual(result['activeCount'], 2)
        self.assertEqual(result['waitingCount'], 2)
        self.assertEqual(result['running'][0]['item'], '2/2')
        self.assertEqual(result['running'][0]['stage'], '디코딩')
        self.assertEqual(result['pending'][0]['position'], 1)
        self.assertFalse({'done', 'failed'} & {j['id'] for j in result['running'] + result['pending']})
