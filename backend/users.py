from fastapi import APIRouter
from database import fetch_all

router = APIRouter(prefix='/api/users', tags=['users'])

@router.get('')
def users(limit: int = 20):
    limit = max(1, min(limit, 100))
    return fetch_all(
        'SELECT id, username, uid, display_name, photo, bio, location, is_ai_bot, created_at '
        'FROM users ORDER BY id DESC LIMIT ?', (limit,)
    )
