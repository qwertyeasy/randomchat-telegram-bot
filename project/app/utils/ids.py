import uuid


def new_session_id() -> uuid.UUID:
    return uuid.uuid4()