from fastapi import APIRouter
from database import fetch_all

router = APIRouter(prefix='/api/videos', tags=['videos'])

@router.get('')
def videos(limit: int = 20):
    limit = max(1, min(limit, 100))
    return fetch_all(
        'SELECT id, title, url, creator, source, caption, tags, privacy, uploader_id, created_at '
        'FROM videos WHERE privacy = ? ORDER BY created_at DESC, id DESC LIMIT ?',
        ('public', limit),
    )
