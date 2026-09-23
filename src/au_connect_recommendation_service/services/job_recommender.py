"""Internal ranking only. Next.js must enforce visibility/access at hydration."""
import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from bson import ObjectId

from au_connect_recommendation_service.db.mongodb import db
from au_connect_recommendation_service.models.user import map_user
from au_connect_recommendation_service.services.job_embeddings import (
    JOB_PROJECTION, ensure_job_embeddings, load_job_skills, normalize_job_text,
)
from au_connect_recommendation_service.services.profile_embeddings import (
    embedding_sources, prepare_persistent_profile_embeddings,
)
from au_connect_recommendation_service.services.similarity import _weighted_breakdown

WEIGHTS = {'semantic': .55, 'skills': .25, 'location': .15, 'freshness': .05}
SEMANTIC_WEIGHTS = {'title': .25, 'about': .25, 'experience': .25, 'education': .15}


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def freshness_score(created_at, now):
    return .5 ** (max(0., (utc(now) - utc(created_at)).total_seconds() / 86400) / 30)


def location_score(user_location, job):
    if job.get('locationType') == 'REMOTE':
        return 1.
    if job.get('locationType') not in ('ONSITE', 'HYBRID'):
        return None
    first, second = normalize_job_text(user_location), normalize_job_text(job.get('location'))
    return float(first == second) if first and second else None


def skill_score(selected, required):
    return len(selected & required) / len(required) if selected and required else None


def semantic_score(user, embeddings, vector):
    sources = embedding_sources(user)
    groups = {'title': [sources.title], 'about': [sources.about],
              'experience': sources.experience_titles, 'education': sources.education_fields_of_study}
    scores = {}
    for name, texts in groups.items():
        values = [max(0., min(1., sum(a*b for a, b in zip(embeddings[text], vector, strict=True))))
                  for text in texts if text]
        scores[name] = sum(values) / len(values) if values else None
    result = _weighted_breakdown(scores, SEMANTIC_WEIGHTS)
    return result['final_score'] if result['available_weight_coverage'] else None


async def load_requesting_user(user_id):
    # Inclusion projections prevent fetching contact/OAuth/verification/resume data.
    doc = await db['User'].find_one({'_id': user_id}, {field: 1 for field in
        ('_id', 'username', 'accountStatus', 'title', 'about', 'location')})
    if doc is None:
        return None
    user = map_user(doc)
    experience, education = await asyncio.gather(
        db['Experience'].find({'userId': user_id}, {'title': 1}).to_list(None),
        db['Education'].find({'userId': user_id}, {'fieldOfStudy': 1}).to_list(None),
    )
    user.experience = [SimpleNamespace(title=entry.get('title')) for entry in experience]
    user.education = [SimpleNamespace(field_of_study=entry.get('fieldOfStudy')) for entry in education]
    return user


def eligible(job, posts, applied, user_id, now):
    parent = posts.get(job.get('postId'))
    return (job.get('status') == 'OPEN'
            and (job.get('deadline') is None or utc(job['deadline']) >= utc(now))
            and job.get('positionsFilled', 0) < job.get('positionsAvailable', 1)
            and parent is not None and parent.get('moderationStatus') == 'VISIBLE'
            and parent.get('userId') != user_id and job['_id'] not in applied)


async def get_job_recommendations(user_id: str, limit: int = 10):
    if not ObjectId.is_valid(user_id):
        raise ValueError('Invalid user ID')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError('limit must be between 1 and 50')
    object_id = ObjectId(user_id)
    user = await load_requesting_user(object_id)
    if user is None:
        return []
    now = datetime.now(UTC)
    jobs = await db['JobPost'].find({'status': 'OPEN'}, JOB_PROJECTION).to_list(None)
    if not jobs:
        return []
    posts, applications, selected = await asyncio.gather(
        db['Post'].find({'_id': {'$in': list({job['postId'] for job in jobs})}},
                        {'_id': 1, 'userId': 1, 'moderationStatus': 1}).to_list(None),
        db['JobApplication'].find({'applicantId': object_id, 'jobPostId': {'$in': [j['_id'] for j in jobs]}},
                                  {'jobPostId': 1}).to_list(None),
        db['UserSkill'].find({'userId': object_id}, {'skillId': 1}).to_list(None),
    )
    posts = {post['_id']: post for post in posts}
    applied = {entry['jobPostId'] for entry in applications}
    jobs = [job for job in jobs if eligible(job, posts, applied, object_id, now)]
    if not jobs:
        return []
    required, names = await load_job_skills(jobs)
    vectors, _ = await ensure_job_embeddings(jobs, names)
    embeddings = await prepare_persistent_profile_embeddings([user])
    selected = {entry['skillId'] for entry in selected}
    ranked = []
    for job in jobs:
        scores = {'semantic': semantic_score(user, embeddings, vectors[job['_id']]),
                  'skills': skill_score(selected, required[job['_id']]),
                  'location': location_score(user.location, job),
                  'freshness': freshness_score(job['createdAt'], now)}
        result = _weighted_breakdown(scores, WEIGHTS)
        ranked.append((job, result))
    ranked.sort(key=lambda entry: (-entry[1]['final_score'],
                                  -utc(entry[0]['createdAt']).timestamp(), str(entry[0]['_id'])))
    return [{'jobPostId': str(job['_id']), 'score': round(result['final_score'], 6),
             'coverage': round(result['available_weight_coverage'], 6),
             'breakdown': {key: round(value, 6) if value is not None else None
                           for key, value in result['component_scores'].items()}}
            for job, result in ranked[:limit]]
