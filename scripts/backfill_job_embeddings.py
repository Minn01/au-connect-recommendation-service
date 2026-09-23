"""Restart safely: valid documents are reused on every pass."""
import argparse
import asyncio

from au_connect_recommendation_service.db.mongodb import db, db_client
from au_connect_recommendation_service.services.job_embeddings import (
    JOB_PROJECTION, ensure_job_embedding_index, ensure_job_embeddings, load_job_skills,
)


async def run(batch_size):
    if batch_size <= 0:
        raise ValueError('batch_size must be greater than zero')
    processed = regenerated = failures = 0
    last_id = None
    try:
        await ensure_job_embedding_index()
        while True:
            query = {'_id': {'$gt': last_id}} if last_id is not None else {}
            jobs = await db['JobPost'].find(query, JOB_PROJECTION).sort('_id', 1).limit(batch_size).to_list(batch_size)
            if not jobs:
                break
            try:
                _, names = await load_job_skills(jobs)
                _, count = await ensure_job_embeddings(jobs, names)
                regenerated += count
                processed += len(jobs)
            except Exception as exc:
                failures += len(jobs)
                print(f'Failed batch ending at {jobs[-1]["_id"]}: {type(exc).__name__}: {exc}')
            last_id = jobs[-1]['_id']
            print(f'Processed={processed} regenerated={regenerated} failed={failures} last_id={last_id}')
    finally:
        await db_client.close()
        print(f'Final: processed={processed} regenerated={regenerated} reused={processed-regenerated} failed={failures}')
    return 1 if failures else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Backfill job embeddings; safely rerunnable.')
    parser.add_argument('--batch-size', type=int, default=100)
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error('--batch-size must be greater than zero')
    raise SystemExit(asyncio.run(run(args.batch_size)))
