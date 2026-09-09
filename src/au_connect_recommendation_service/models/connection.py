from dataclasses import dataclass


@dataclass
class Connection:
    id: str
    user_a_id: str
    user_b_id: str


def map_connection(doc: dict) -> Connection:
    return Connection(
        id=str(doc["_id"]),
        user_a_id=doc["userAId"],
        user_b_id=doc["userBId"],
    )
