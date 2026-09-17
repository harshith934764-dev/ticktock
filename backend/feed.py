from fastapi import APIRouter, Request
from database import get_db
from videos import current_user_id

router = APIRouter(prefix='/api/feed', tags=['feed'])

@router.get('/for-you')
def for_you(request: Request, limit: int = 12):
    uid = current_user_id(request)
    limit = max(1, min(limit, 50))
    with get_db() as db:
        rows = db.execute('''
            SELECT v.id,v.title,v.url,v.creator,v.caption,v.tags,v.privacy,v.uploader_id,v.created_at,
              (SELECT COUNT(*) FROM likes l WHERE l.video_id=CAST(v.id AS TEXT)) likes,
              (SELECT COUNT(*) FROM comments c WHERE c.video_id=CAST(v.id AS TEXT)) comments,
              (SELECT COUNT(*) FROM shares s WHERE s.video_id=CAST(v.id AS TEXT)) shares,
              (SELECT COUNT(*) FROM video_views x WHERE x.video_id=CAST(v.id AS TEXT)) views
            FROM videos v
            WHERE v.privacy='public' OR v.privacy IS NULL
            ORDER BY v.created_at DESC, v.id DESC LIMIT 300
        ''').fetchall()
        liked = set()
        saved = set()
        seen = set()
        if uid:
            liked = {str(r['video_id']) for r in db.execute('SELECT video_id FROM likes WHERE user_id=?', (uid,)).fetchall()}
            saved = {str(r['video_id']) for r in db.execute('SELECT video_id FROM bookmarks WHERE user_id=?', (uid,)).fetchall()}
            seen = {str(r['video_id']) for r in db.execute("SELECT video_id FROM user_video_events WHERE user_id=? AND event='view'", (uid,)).fetchall()}
        out=[]
        for r in rows:
            d=dict(r)
            d['liked']=str(r['id']) in liked
            d['saved']=str(r['id']) in saved
            d['seen']=str(r['id']) in seen
            freshness=1.0
            score=(r['likes']*3)+(r['comments']*4)+(r['shares']*6)+(r['views']*.15)
            if not d['seen']: score += 12
            d['feed_score']=round(score*freshness,2)
            out.append(d)
        out.sort(key=lambda x:(x['feed_score'], str(x.get('created_at',''))), reverse=True)
    return out[:limit]

@router.get('/trending')
def feed_trending(limit: int = 12):
    limit=max(1,min(limit,50))
    with get_db() as db:
        rows=db.execute('''
            SELECT v.id,v.title,v.url,v.creator,v.caption,v.tags,v.privacy,v.uploader_id,v.created_at,
              (SELECT COUNT(*) FROM likes l WHERE l.video_id=CAST(v.id AS TEXT)) likes,
              (SELECT COUNT(*) FROM comments c WHERE c.video_id=CAST(v.id AS TEXT)) comments,
              (SELECT COUNT(*) FROM shares s WHERE s.video_id=CAST(v.id AS TEXT)) shares,
              (SELECT COUNT(*) FROM video_views x WHERE x.video_id=CAST(v.id AS TEXT)) views
            FROM videos v WHERE v.privacy='public' OR v.privacy IS NULL
            ORDER BY v.id DESC LIMIT 300
        ''').fetchall()
    out=[]
    for r in rows:
        score=r['likes']*3+r['comments']*4+r['shares']*6+r['views']*.2
        d=dict(r); d['viral_score']=round(score,2); out.append(d)
    out.sort(key=lambda x:x['viral_score'],reverse=True)
    return out[:limit]
