import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('MONGODB_URI', 'mongodb://localhost:27017')
os.environ.setdefault('MONGODB_DB', 'au_connect')
os.environ.setdefault('INTERNAL_API_KEY', 'test-internal-key')

from bson import ObjectId
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient
from au_connect_recommendation_service.services import job_embeddings as je, job_recommender as jr
from au_connect_recommendation_service.routes import internal_job_embeddings as route
from au_connect_recommendation_service.main import app
from au_connect_recommendation_service.core.env import INTERNAL_API_KEY


def vector(axis=0):
    return [float(i == axis) for i in range(384)]


class Collection:
    def __init__(self, docs=()):
        self.docs = list(docs)
        self.calls = []
        self.bulk_write = AsyncMock()
        self.find_one = AsyncMock(return_value=self.docs[0] if self.docs else None)
        self.delete_one = AsyncMock(return_value=SimpleNamespace(deleted_count=1))

    def find(self, query, projection=None):
        self.calls.append((query, projection))
        return self

    async def to_list(self, length=None):
        return self.docs


class JobTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime.now(UTC)
        self.uid, self.pid, self.jid = ObjectId(), ObjectId(), ObjectId()
        self.job = {'_id': self.jid, 'postId': self.pid, 'status': 'OPEN',
                    'createdAt': self.now, 'jobTitle': 'Software engineer',
                    'positionsAvailable': 1, 'positionsFilled': 0}
        self.posts = {self.pid: {'_id': self.pid, 'userId': ObjectId(), 'moderationStatus': 'VISIBLE'}}
        self.user = SimpleNamespace(id=str(self.uid), title='software', about=None,
                                    location=None, experience=[], education=[])

    def test_eligibility(self):
        self.assertTrue(jr.eligible(self.job, self.posts, set(), self.uid, self.now))
        for changes in ({'status': 'CLOSED'}, {'deadline': self.now-timedelta(seconds=1)},
                        {'positionsFilled': 1}):
            with self.subTest(changes=changes):
                self.assertFalse(jr.eligible(self.job | changes, self.posts, set(), self.uid, self.now))
        for posts in ({}, {self.pid: self.posts[self.pid] | {'moderationStatus': 'REMOVED'}},
                      {self.pid: self.posts[self.pid] | {'userId': self.uid}}):
            self.assertFalse(jr.eligible(self.job, posts, set(), self.uid, self.now))
        self.assertFalse(jr.eligible(self.job, self.posts, {self.jid}, self.uid, self.now))

    def test_location(self):
        self.assertEqual(jr.location_score(None, {'locationType': 'REMOTE'}), 1)
        for kind in ('ONSITE', 'HYBRID'):
            self.assertEqual(jr.location_score('  ＢANGKOK  city ', {'locationType': kind, 'location': 'bangkok   CITY'}), 1)
            self.assertEqual(jr.location_score('Bangkok', {'locationType': kind, 'location': 'Paris'}), 0)
            self.assertIsNone(jr.location_score(None, {'locationType': kind, 'location': 'Paris'}))

    def test_freshness(self):
        for days, expected in ((0, 1), (30, .5), (60, .25), (-10, 1)):
            self.assertEqual(jr.freshness_score(self.now-timedelta(days=days), self.now), expected)
        self.assertEqual(jr.freshness_score(self.now.replace(tzinfo=None), self.now), 1)

    def test_skill_ids_and_missing_data(self):
        a, b = ObjectId(), ObjectId()
        self.assertEqual(jr.skill_score({a}, {a, b}), .5)
        self.assertEqual(jr.skill_score({str(a)}, {a}), 0)
        self.assertIsNone(jr.skill_score(set(), {a}))
        self.assertIsNone(jr.skill_score({a}, set()))
        result = jr._weighted_breakdown({'semantic': 1, 'skills': None, 'location': None, 'freshness': .5}, jr.WEIGHTS)
        self.assertAlmostEqual(result['available_weight_coverage'], .6)
        self.assertAlmostEqual(result['final_score'], .575/.6)

    def test_semantic_profile_and_missing_fields(self):
        self.assertEqual(jr.semantic_score(self.user, {'software': vector()}, vector()), 1)
        self.assertEqual(jr.semantic_score(self.user, {'software': vector()}, vector(1)), 0)
        self.user.title = None
        self.assertIsNone(jr.semantic_score(self.user, {}, vector()))

    def test_text_deterministic_and_excludes_metadata(self):
        text = je.job_text(self.job, ['Python', 'SQL'])
        self.assertEqual(text, je.job_text(self.job | {'salaryMin': 42, 'companyName': 'SECRET', 'location': 'SECRET'}, ['SQL', 'Python']))
        self.assertNotIn('SECRET', text)

    async def test_embedding_reuse_and_regeneration(self):
        collection = Collection()
        with patch.object(je, 'db', {'JobEmbedding': collection}), patch.object(je, '_encode_passages', return_value={je.job_text(self.job, []): vector()}) as encode:
            _, count = await je.ensure_job_embeddings([self.job], {})
            self.assertEqual(count, 1)
            update = collection.bulk_write.call_args.args[0][0]._doc
            collection.docs = [update['$set']]
            encode.reset_mock()
            _, count = await je.ensure_job_embeddings([self.job], {})
            self.assertEqual(count, 0)
            encode.assert_not_called()
            for field, value in (('sourceHash', 'stale'), ('model', {}), ('embedding', [1]), ('embedding', [float('nan')]*384)):
                collection.docs = [update['$set'] | {field: value}]
                _, count = await je.ensure_job_embeddings([self.job], {})
                self.assertEqual(count, 1)
            await je.ensure_job_embeddings([self.job], {}, force=True)
            self.assertIn('createdAt', update['$setOnInsert'])

    async def test_ranking_skills_ties_limit_and_no_skills(self):
        second = self.job | {'_id': ObjectId(), 'jobTitle': 'Unrelated'}
        skill = ObjectId()
        database = {'JobPost': Collection([second, self.job]), 'Post': Collection(self.posts.values()),
                    'JobApplication': Collection(), 'UserSkill': Collection()}
        required = {self.jid: {skill}, second['_id']: {ObjectId()}}
        with patch.object(jr, 'db', database), patch.object(jr, 'load_requesting_user', AsyncMock(return_value=self.user)), patch.object(jr, 'load_job_skills', AsyncMock(return_value=(required, {}))), patch.object(jr, 'ensure_job_embeddings', AsyncMock(return_value=({self.jid: vector(), second['_id']: vector(1)}, 0))) as embeddings, patch.object(jr, 'prepare_persistent_profile_embeddings', AsyncMock(return_value={'software': vector()})):
            result = await jr.get_job_recommendations(str(self.uid))
            self.assertEqual(result[0]['jobPostId'], str(self.jid))
            self.assertIsNone(result[0]['breakdown']['skills'])
            self.assertEqual(result[0]['coverage'], .6)
            embeddings.return_value = ({self.jid: vector(), second['_id']: vector()}, 0)
            database['UserSkill'].docs = [{'skillId': skill}]
            result = await jr.get_job_recommendations(str(self.uid), 1)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['jobPostId'], str(self.jid))
            database['UserSkill'].docs = []
            result = await jr.get_job_recommendations(str(self.uid))
            self.assertEqual([r['jobPostId'] for r in result], sorted([str(self.jid), str(second['_id'])]))
            second['createdAt'] = self.now + timedelta(days=1)
            result = await jr.get_job_recommendations(str(self.uid))
            self.assertEqual(result[0]['jobPostId'], str(second['_id']))
            database['JobPost'].docs = []
            self.assertEqual(await jr.get_job_recommendations(str(self.uid)), [])
        for limit in (0, 51, -1):
            with self.assertRaises(ValueError):
                await jr.get_job_recommendations(str(self.uid), limit)
        with self.assertRaises(ValueError):
            await jr.get_job_recommendations('invalid')

    async def test_refresh_validation_and_deferred_work(self):
        tasks = BackgroundTasks()
        with patch.object(route, 'db', {'JobPost': Collection([self.job])}), patch.object(route, 'refresh_job_embedding_background', AsyncMock()) as refresh:
            result = await route.schedule_job_embedding_refresh(str(self.jid), tasks)
            self.assertEqual(result['status'], 'accepted')
            refresh.assert_not_awaited()
            self.assertEqual(len(tasks.tasks), 1)
        for value, database, status in (('invalid', {}, 422), (str(self.jid), {'JobPost': Collection()}, 404)):
            with patch.object(route, 'db', database), self.assertRaises(HTTPException) as error:
                await route.schedule_job_embedding_refresh(value, BackgroundTasks())
            self.assertEqual(error.exception.status_code, status)

    def test_registered_routes_auth_validation_and_202(self):
        client = TestClient(app)
        headers = {'x-internal-service-key': INTERNAL_API_KEY}
        for method, path in (('get', f'/recommendations/jobs/{self.uid}'), ('put', f'/internal/jobs/{self.jid}/embedding'), ('delete', f'/internal/jobs/{self.jid}/embedding')):
            self.assertEqual(getattr(client, method)(path).status_code, 401)
            self.assertEqual(getattr(client, method)(path, headers={'x-internal-service-key': 'wrong'}).status_code, 403)
        for suffix in ('invalid', f'{self.uid}?limit=0', f'{self.uid}?limit=51'):
            self.assertEqual(client.get('/recommendations/jobs/'+suffix, headers=headers).status_code, 422)
        with patch.object(route, 'db', {'JobPost': Collection([self.job])}), patch.object(route, 'refresh_job_embedding_background', AsyncMock()):
            self.assertEqual(client.put(f'/internal/jobs/{self.jid}/embedding', headers=headers).status_code, 202)

    async def test_batch_skill_loading_and_passage_prefix(self):
        skill = ObjectId()
        links = Collection([{'jobPostId': self.jid, 'skillId': skill}])
        skills = Collection([{'_id': skill, 'name': 'Python'}])
        with patch.object(je, 'db', {'JobSkill': links, 'Skill': skills}):
            required, names = await je.load_job_skills([self.job])
        self.assertEqual(required, {self.jid: {skill}})
        self.assertEqual(names, {self.jid: ['Python']})
        self.assertEqual(len(links.calls), 1)
        self.assertEqual(len(skills.calls), 1)
        model = SimpleNamespace(encode=lambda texts, **kwargs: [vector() for _ in texts])
        with patch.object(je, 'get_embedding_model', return_value=model), patch.object(model, 'encode', return_value=[vector()]) as encode:
            je._encode_passages(['software'])
        self.assertEqual(encode.call_args.args[0], ['passage: software'])
        self.assertTrue(encode.call_args.kwargs['normalize_embeddings'])

    async def test_unique_index_cleanup_and_force_refresh(self):
        collection = Collection()
        collection.create_index = AsyncMock(return_value='index')
        with patch.object(je, 'db', {'JobEmbedding': collection}):
            await je.ensure_job_embedding_index()
        self.assertTrue(collection.create_index.call_args.kwargs['unique'])
        with patch.object(route, 'db', {'JobEmbedding': collection}):
            result = await route.delete_job_embedding(str(self.jid))
        self.assertTrue(result['deleted'])
        with patch.object(je, 'db', {'JobPost': Collection([self.job])}), patch.object(je, 'load_job_skills', AsyncMock(return_value=({}, {}))), patch.object(je, 'ensure_job_embeddings', AsyncMock()) as ensure:
            await je.refresh_job_embedding(str(self.jid))
        self.assertTrue(ensure.call_args.kwargs['force'])
