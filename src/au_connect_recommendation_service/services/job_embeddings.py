"""Batch-persisted E5 passages; no recommendation lists or JobPost mutations."""
import hashlib
import math
import unicodedata
from datetime import UTC, datetime

from bson import ObjectId
from pymongo import ASCENDING, UpdateOne
from starlette.concurrency import run_in_threadpool

from au_connect_recommendation_service.core.embedding_model import get_embedding_model
from au_connect_recommendation_service.db.mongodb import db
from au_connect_recommendation_service.services.profile_embeddings import _model_identity

JOB_PROJECTION = {field: 1 for field in (
    '_id', 'postId', 'jobTitle', 'jobDetails', 'employmentType', 'locationType',
    'location', 'status', 'deadline', 'positionsAvailable', 'positionsFilled', 'createdAt',
)}


def normalize_job_text(value):
    return ' '.join(unicodedata.normalize('NFKC', value or '').split()).casefold()


def job_text(job, skill_names):
    skills = sorted({normalize_job_text(name) for name in skill_names} - {''})
    fields = [(name, normalize_job_text(job.get(name))) for name in
              ('jobTitle', 'jobDetails', 'employmentType', 'locationType')]
    fields.insert(2, ('skills', ', '.join(skills)))
    return '\n'.join(f'{name}: {value}' for name, value in fields if value)


async def load_job_skills(jobs):
    ids = [job['_id'] for job in jobs]
    if not ids:
        return {}, {}
    links = await db['JobSkill'].find({'jobPostId': {'$in': ids}},
                                     {'jobPostId': 1, 'skillId': 1}).to_list(None)
    required = {job_id: set() for job_id in ids}
    for link in links:
        required[link['jobPostId']].add(link['skillId'])
    skill_ids = list({skill for skills in required.values() for skill in skills})
    skills = await db['Skill'].find({'_id': {'$in': skill_ids}}, {'name': 1}).to_list(None)
    names = {skill['_id']: skill['name'] for skill in skills}
    return required, {job_id: [names[s] for s in skills if s in names]
                      for job_id, skills in required.items()}


def valid_vector(vector):
    return (isinstance(vector, list) and len(vector) == 384
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in vector)
            and any(vector))


def _encode_passages(texts):
    vectors = get_embedding_model().encode(
        [f'passage: {text}' for text in texts], normalize_embeddings=True,
        show_progress_bar=False,
    )
    return {text: [float(v) for v in vector]
            for text, vector in zip(texts, vectors, strict=True)}


async def ensure_job_embeddings(jobs, skill_names, *, force=False):
    if not jobs:
        return {}, 0
    texts = {job['_id']: job_text(job, skill_names.get(job['_id'], [])) for job in jobs}
    hashes = {key: hashlib.sha256(text.encode('utf-8')).hexdigest() for key, text in texts.items()}
    saved = await db['JobEmbedding'].find({'jobPostId': {'$in': list(texts)}}).to_list(None)
    saved = {doc['jobPostId']: doc for doc in saved}
    vectors, stale = {}, []
    for job_id in texts:
        doc = saved.get(job_id, {})
        if (not force and doc.get('model') == _model_identity()
                and doc.get('sourceHash') == hashes[job_id]
                and valid_vector(doc.get('embedding'))):
            vectors[job_id] = doc['embedding']
        else:
            stale.append(job_id)
    if stale:
        generated = await run_in_threadpool(_encode_passages, sorted({texts[key] for key in stale}))
        now = datetime.now(UTC)
        operations = []
        for job_id in stale:
            vector = generated[texts[job_id]]
            if not valid_vector(vector):
                raise ValueError('Invalid generated job embedding')
            vectors[job_id] = vector
            operations.append(UpdateOne({'jobPostId': job_id}, {'$set': {
                'jobPostId': job_id, 'embedding': vector, 'model': _model_identity(),
                'sourceHash': hashes[job_id], 'normalizedText': texts[job_id], 'updatedAt': now,
            }, '$setOnInsert': {'createdAt': now}}, upsert=True))
        await db['JobEmbedding'].bulk_write(operations, ordered=False)
    return vectors, len(stale)


async def refresh_job_embedding(job_post_id):
    job = await db['JobPost'].find_one({'_id': ObjectId(job_post_id)}, JOB_PROJECTION)
    if job is None:
        return
    _, names = await load_job_skills([job])
    await ensure_job_embeddings([job], names, force=True)


async def ensure_job_embedding_index():
    return await db['JobEmbedding'].create_index(
        [('jobPostId', ASCENDING)], unique=True, name='unique_job_embedding_job_post_id')
