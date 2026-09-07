from dataclasses import dataclass

from au_connect_recommendation_service.enums.account_status import AccountStatus

@dataclass
class User:
    id: str
    # general information
    username: str
    title: str | None
    location: str | None
    
    # account availability
    account_status: AccountStatus 
    
    # work in progress
    experience: list[str]
    education: list[str]

def map_user(doc: dict) -> User:
    return User(
        id=str(doc["_id"]),
        username=doc["username"],
        title=doc.get("title"),
        location=doc.get("location"),
        account_status=AccountStatus(doc["accountStatus"]),
        experience=[],
        education=[],
    )