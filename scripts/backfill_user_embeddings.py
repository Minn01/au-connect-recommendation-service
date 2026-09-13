import argparse
import asyncio

from au_connect_recommendation_service.services.profile_embeddings import (
    backfill_active_user_embeddings,
    ensure_user_embedding_index,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or refresh stored embeddings for active users.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of users to process per MongoDB batch (default: 100).",
    )
    return parser.parse_args()


async def run(batch_size: int) -> None:
    await ensure_user_embedding_index()
    result = await backfill_active_user_embeddings(batch_size=batch_size)
    print(
        f"Processed {result.processed} active users; "
        f"regenerated {result.regenerated} embedding documents."
    )


if __name__ == "__main__":
    arguments = parse_args()
    asyncio.run(run(arguments.batch_size))
