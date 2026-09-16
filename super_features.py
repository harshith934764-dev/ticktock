
"""
Tick Tock Super Features
Adds an Instagram/TikTok-style feature hub without replacing existing routes.

Features:
- Stories
- Direct messages + conversations
- Close Friends
- Reposts
- Trending hashtags
- Creator insights
- AI idea/hashtag assistant
- Personalized feed suggestions
"""
import os, json, time, uuid, re
import requests
from flask import request, jsonify, session

def register_super_features(app, get_db, logged_in):
    def auth():
        if not session.get("user_id"):
            return None, (jsonify({"success": False, "login_required": True}), 401)
        return int(session["user_id"]), None

    def ensure_tables(db):
        db.execute("""CREATE TABLE IF NOT EXISTS tt_stories (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, media_url TEXT NOT NULL,
            caption TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at REAL NOT NULL, is_archived INTEGER DEFAULT 0)""")
        db.execute("""CREATE TABLE IF NOT EXISTS tt_messages (
            id TEXT PRIMARY KEY, sender_id INTEGER NOT NULL, receiver_id INTEGER NOT NULL,
            body TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_read INTEGER DEFAULT 0)""")
        db.execute("""CREATE TABLE IF NOT EXISTS tt_close_friends (
            owner_id INTEGER NOT NULL, friend_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(owner_id, friend_id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS tt_reposts (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, video_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, video_id))""")
        db.commit()

    def safe_text(v, n):
        return str(v or "").strip()[:n]

    @app.get("/api/super/overview")
    def super_overview():
        uid, err = auth()
        if err: return err
        db=get_db()
        try:
            ensure_tables(db)
            now=time.time()
            stories=db.execute("""SELECT s.id,s.media_url,s.caption,s.created_at,s.expires_at,
                u.username,u.photo,u.uid FROM tt_stories s JOIN users u ON u.id=s.user_id
                WHERE s.expires_at>? AND s.is_archived=0 ORDER BY s.created_at DESC LIMIT 50""",(now,)).fetchall()
            conv=db.execute("""SELECT m.id,m.body,m.created_at,m.sender_id,m.receiver_id,
                u.username,u.photo,u.uid FROM tt_messages m
                JOIN users u ON u.id=CASE WHEN m.sender_id=? THEN m.receiver_id ELSE m.sender_id END
                WHERE m.sender_id=? OR m.receiver_id=? ORDER BY m.created_at DESC LIMIT 30""",(uid,uid,uid)).fetchall()
            reposts=db.execute("""SELECT r.video_id,r.created_at,v.title,v.url,v.creator,v.caption,v.tags
                FROM tt_reposts r LEFT JOIN videos v ON CAST(v.id AS TEXT)=r.video_id
                WHERE r.user_id=? ORDER BY r.created_at DESC LIMIT 30""",(uid,)).fetchall()
            followers=db.execute("SELECT COUNT(*) n FROM follows WHERE following_id=?",(uid,)).fetchone()["n"]
            following=db.execute("SELECT COUNT(*) n FROM follows WHERE follower_id=?",(uid,)).fetchone()["n"]
            views=db.execute("""SELECT COALESCE(SUM(vv.view_count),0) n FROM (
                SELECT video_id, COUNT(*) view_count FROM video_views GROUP BY video_id) vv
                JOIN videos v ON CAST(v.id AS TEXT)=vv.video_id WHERE v.uploader_id=?""",(uid,)).fetchone()["n"] if _table_exists(db,"video_views") else 0
            return jsonify({"success":True,"stories":[dict(x) for x in stories],
                            "messages":[dict(x) for x in conv],
                            "reposts":[dict(x) for x in reposts],
                            "stats":{"followers":int(followers or 0),"following":int(following or 0),"views":int(views or 0)}})
        finally: db.close()

    @app.get("/api/super/stories")
    def super_stories():
        uid, err=auth()
        if err:return err
        db=get_db()
        try:
            ensure_tables(db)
            rows=db.execute("""SELECT s.id,s.media_url,s.caption,s.created_at,s.expires_at,
                u.username,u.photo,u.uid FROM tt_stories s JOIN users u ON u.id=s.user_id
                WHERE s.expires_at>? AND s.is_archived=0
                AND (s.user_id=? OR EXISTS(SELECT 1 FROM follows f WHERE f.follower_id=? AND f.following_id=s.user_id))
                ORDER BY s.created_at DESC LIMIT 100""",(time.time(),uid,uid)).fetchall()
            return jsonify({"success":True,"stories":[dict(x) for x in rows]})
        finally: db.close()

    @app.post("/api/super/stories")
    def super_create_story():
        uid, err=auth()
        if err:return err
        data=request.get_json(silent=True) or {}
        media=safe_text(data.get("media_url"),1000)
        caption=safe_text(data.get("caption"),500)
        if not media or not (media.startswith("https://") or media.startswith("http://") or media.startswith("/")):
            return jsonify({"success":False,"message":"Provide a valid media URL."}),400
        db=get_db()
        try:
            ensure_tables(db)
            sid=uuid.uuid4().hex
            db.execute("INSERT INTO tt_stories(id,user_id,media_url,caption,expires_at) VALUES(?,?,?,?,?)",
                       (sid,uid,media,caption,time.time()+86400))
            db.commit()
            return jsonify({"success":True,"story":{"id":sid,"media_url":media,"caption":caption}})
        finally: db.close()

    @app.get("/api/super/conversations")
    def super_conversations():
        uid,err=auth()
        if err:return err
        db=get_db()
        try:
            ensure_tables(db)
            rows=db.execute("""SELECT u.id,u.uid,u.username,u.display_name,u.photo,
                (SELECT body FROM tt_messages x WHERE
                 (x.sender_id=? AND x.receiver_id=u.id) OR (x.receiver_id=? AND x.sender_id=u.id)
                 ORDER BY x.created_at DESC LIMIT 1) last_message
                FROM users u WHERE u.id<>? ORDER BY u.id DESC LIMIT 100""",(uid,uid,uid)).fetchall()
            return jsonify({"success":True,"users":[dict(x) for x in rows]})
        finally: db.close()

    @app.get("/api/super/messages/<uid>")
    def super_messages(uid):
        me,err=auth()
        if err:return err
        db=get_db()
        try:
            ensure_tables(db)
            target=db.execute("SELECT id,uid,username,display_name,photo FROM users WHERE uid=? OR friend_uid=?",(uid,uid)).fetchone()
            if not target:return jsonify({"success":False,"message":"User not found."}),404
            tid=target["id"]
            rows=db.execute("""SELECT m.id,m.sender_id,m.receiver_id,m.body,m.created_at,
                u.username FROM tt_messages m JOIN users u ON u.id=m.sender_id
                WHERE (m.sender_id=? AND m.receiver_id=?) OR (m.sender_id=? AND m.receiver_id=?)
                ORDER BY m.created_at ASC LIMIT 200""",(me,tid,tid,me)).fetchall()
            db.execute("UPDATE tt_messages SET is_read=1 WHERE receiver_id=? AND sender_id=?",(me,tid)); db.commit()
            return jsonify({"success":True,"user":dict(target),"messages":[dict(x) for x in rows]})
        finally: db.close()

    @app.post("/api/super/messages/<uid>")
    def super_send_message(uid):
        me,err=auth()
        if err:return err
        data=request.get_json(silent=True) or {}
        body=safe_text(data.get("body"),2000)
        if not body:return jsonify({"success":False,"message":"Message is empty."}),400
        db=get_db()
        try:
            ensure_tables(db)
            target=db.execute("SELECT id FROM users WHERE uid=? OR friend_uid=?",(uid,uid)).fetchone()
            if not target:return jsonify({"success":False,"message":"User not found."}),404
            if target["id"]==me:return jsonify({"success":False,"message":"You cannot message yourself."}),400
            mid=uuid.uuid4().hex
            db.execute("INSERT INTO tt_messages(id,sender_id,receiver_id,body) VALUES(?,?,?,?)",(mid,me,target["id"],body))
            db.commit()
            return jsonify({"success":True,"message":{"id":mid,"body":body}})
        finally: db.close()

    @app.get("/api/super/close-friends")
    def super_close_friends():
        me,err=auth()
        if err:return err
        db=get_db()
        try:
            ensure_tables(db)
            rows=db.execute("""SELECT u.id,u.uid,u.friend_uid,u.username,u.display_name,u.photo
                FROM tt_close_friends c JOIN users u ON u.id=c.friend_id WHERE c.owner_id=?
                ORDER BY u.username""",(me,)).fetchall()
            return jsonify({"success":True,"users":[dict(x) for x in rows]})
        finally: db.close()

    @app.post("/api/super/close-friends/<uid>")
    def super_toggle_close_friend(uid):
        me,err=auth()
        if err:return err
        db=get_db()
        try:
            ensure_tables(db)
            target=db.execute("SELECT id FROM users WHERE uid=? OR friend_uid=?",(uid,uid)).fetchone()
            if not target:return jsonify({"success":False,"message":"User not found."}),404
            if target["id"]==me:return jsonify({"success":False,"message":"Choose another user."}),400
            exists=db.execute("SELECT 1 FROM tt_close_friends WHERE owner_id=? AND friend_id=?",(me,target["id"])).fetchone()
            if exists:
                db.execute("DELETE FROM tt_close_friends WHERE owner_id=? AND friend_id=?",(me,target["id"])); added=False
            else:
                db.execute("INSERT INTO tt_close_friends(owner_id,friend_id) VALUES(?,?)",(me,target["id"])); added=True
            db.commit()
            return jsonify({"success":True,"added":added})
        finally: db.close()

    @app.post("/api/super/repost/<video_id>")
    def super_repost(video_id):
        me,err=auth()
        if err:return err
        db=get_db()
        try:
            ensure_tables(db)
            v=db.execute("SELECT id FROM videos WHERE id=?",(video_id,)).fetchone()
            if not v:return jsonify({"success":False,"message":"Video not found."}),404
            exists=db.execute("SELECT id FROM tt_reposts WHERE user_id=? AND video_id=?",(me,str(video_id))).fetchone()
            if exists:
                db.execute("DELETE FROM tt_reposts WHERE id=?",(exists["id"],)); reposted=False
            else:
                db.execute("INSERT INTO tt_reposts(id,user_id,video_id) VALUES(?,?,?)",(uuid.uuid4().hex,me,str(video_id))); reposted=True
            db.commit()
            return jsonify({"success":True,"reposted":reposted})
        finally: db.close()

    @app.get("/api/super/trending")
    def super_trending():
        uid,_=auth()
        db=get_db()
        try:
            rows=db.execute("""SELECT tags,COUNT(*) n FROM videos
                WHERE privacy='public' AND tags IS NOT NULL AND tags<>'' GROUP BY tags
                ORDER BY n DESC LIMIT 30""").fetchall()
            counts={}
            for r in rows:
                for tag in re.split(r"[\s,]+",str(r["tags"] or "")):
                    tag=tag.strip().lstrip("#").lower()
                    if tag: counts[tag]=counts.get(tag,0)+int(r["n"] or 1)
            top=sorted(counts.items(),key=lambda x:x[1],reverse=True)[:20]
            return jsonify({"success":True,"hashtags":[{"tag":k,"posts":v} for k,v in top]})
        finally: db.close()

    @app.get("/api/super/recommendations")
    def super_recommendations():
        me,err=auth()
        if err:return err
        db=get_db()
        try:
            followed=db.execute("SELECT following_id FROM follows WHERE follower_id=? LIMIT 50",(me,)).fetchall()
            ids=[int(x["following_id"]) for x in followed]
            if ids:
                marks=",".join("?" for _ in ids)
                rows=db.execute(f"""SELECT id,title,url,creator,caption,tags,created_at FROM videos
                    WHERE privacy='public' AND uploader_id IN ({marks})
                    ORDER BY created_at DESC LIMIT 30""",tuple(ids)).fetchall()
            else:
                rows=db.execute("""SELECT id,title,url,creator,caption,tags,created_at FROM videos
                    WHERE privacy='public' ORDER BY created_at DESC LIMIT 30""").fetchall()
            return jsonify({"success":True,"videos":[dict(x) for x in rows]})
        finally: db.close()

    @app.post("/api/ai/super-ideas")
    def ai_super_ideas():
        me,err=auth()
        if err:return err
        data=request.get_json(silent=True) or {}
        topic=safe_text(data.get("topic"),500)
        if not topic:return jsonify({"success":False,"message":"Enter a topic."}),400
        key=os.environ.get("OPENAI_API_KEY","").strip()
        if not key:return jsonify({"success":False,"message":"AI is not configured. Add OPENAI_API_KEY in Render."}),503
        model=os.environ.get("TICKTOCK_AI_MODEL","gpt-5.6-luna").strip() or "gpt-5.6-luna"
        instructions=("You are Tick Tock's original creator assistant. Return JSON only with keys "
                      "ideas (array of 5), hooks (array of 5), hashtags (array of 10). "
                      "Do not copy creators, scripts, lyrics, or copyrighted text. Keep ideas practical.")
        try:
            r=requests.post("https://api.openai.com/v1/responses",
                headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},
                json={"model":model,"instructions":instructions,"input":topic,"max_output_tokens":900},timeout=45)
            if not r.ok:return jsonify({"success":False,"message":f"AI request failed ({r.status_code})."}),502
            d=r.json(); text=d.get("output_text","")
            if not text:
                parts=[]
                for item in d.get("output",[]) or []:
                    for c in item.get("content",[]) or []:
                        if c.get("type") in {"output_text","text"}: parts.append(c.get("text",""))
                text="\n".join(parts).strip()
            try: out=json.loads(text)
            except Exception: out={"ideas":[text],"hooks":[],"hashtags":[]}
            return jsonify({"success":True,"result":out})
        except requests.RequestException:
            return jsonify({"success":False,"message":"AI service is temporarily unavailable."}),503

def _table_exists(db, name):
    try:
        if hasattr(db, "execute"):
            # Works for SQLite and the Postgres wrapper.
            row=db.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=? LIMIT 1",(name,)).fetchone()
            if row:return True
    except Exception: pass
    try:
        row=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone()
        return bool(row)
    except Exception: return False
