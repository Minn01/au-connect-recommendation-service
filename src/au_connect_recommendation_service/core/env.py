import os

def required(name: str) -> str:
    val = os.getenv(name)

    if not val:
        raise RuntimeError(f"Environment variable {name} is missing")

    return val

# all environment variables here--  
 
MONGODB_URL = required("MONGODB_URL")
MONGODB_DB = required("MONGODB_DB")
INTERNAL_API_KEY = required("INTERNAL_API_KEY")
