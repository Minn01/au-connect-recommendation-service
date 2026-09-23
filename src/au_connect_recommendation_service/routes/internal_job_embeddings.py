import logging

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from au_connect_recommendation_service.core.security import verifyServiceKey
from au_connect_recommendation_service.db.mongodb import db
from au_connect_recommendation_service.services.job_embeddings import refresh_job_embedding

router = APIRouter(prefix='/internal/jobs', tags=['Internal Job Embeddings'],
                   dependencies=[Depends(verifyServiceKey)])
logger = logging.getLogger(__name__)


def parse_job_id(value):
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=422, detail='Invalid job ID')
    return ObjectId(value)


async def refresh_job_embedding_background(job_post_id):
    try:
        await refresh_job_embedding(job_post_id)
    except Exception:
        logger.exception('Job embedding refresh failed for job %s', job_post_id)
        raise


@router.put('/{job_post_id}/embedding', status_code=202)
async def schedule_job_embedding_refresh(job_post_id: str, background_tasks: BackgroundTasks):
    object_id = parse_job_id(job_post_id)
    if await db['JobPost'].find_one({'_id': object_id}, {'_id': 1}) is None:
        raise HTTPException(status_code=404, detail='Job not found')
    background_tasks.add_task(refresh_job_embedding_background, job_post_id)
    return {'status': 'accepted', 'jobPostId': job_post_id}


@router.delete('/{job_post_id}/embedding')
async def delete_job_embedding(job_post_id: str):
    result = await db['JobEmbedding'].delete_one({'jobPostId': parse_job_id(job_post_id)})
    return {'jobPostId': job_post_id, 'deleted': result.deleted_count > 0}
