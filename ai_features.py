
"""
Tick Tock AI Upgrade
--------------------
Optional OpenAI-powered creator/search assistant for the existing Flask app.

Required Render environment variable:
  OPENAI_API_KEY

Optional:
  TICKTOCK_AI_MODEL=gpt-5.6-luna

The API key is server-side only and is never sent to the browser.
"""
import os
import json
import requests
from flask import Blueprint, request, jsonify, session

def register_ai_routes(app, get_db):
    bp = Blueprint("ticktock_ai", __name__)

    def require_login():
        if not session.get("user_id"):
            return jsonify({"success": False, "login_required": True}), 401
        return None

    def call_openai(instructions, user_text, *, max_output=900):
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            return None, ("AI is not configured yet. Add OPENAI_API_KEY in Render Environment Variables.", 503)

        model = os.environ.get("TICKTOCK_AI_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"
        payload = {
            "model": model,
            "instructions": instructions,
            "input": user_text,
            "max_output_tokens": max_output,
        }
        try:
            r = requests.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=45,
            )
            if not r.ok:
                return None, (f"AI request failed ({r.status_code}).", 502)
            data = r.json()
            text = data.get("output_text", "")
            if not text:
                # Defensive fallback for response formats that expose output items.
                parts = []
                for item in data.get("output", []) or []:
                    for content in item.get("content", []) or []:
                        if content.get("type") in {"output_text", "text"}:
                            parts.append(content.get("text", ""))
                text = "\n".join(p for p in parts if p).strip()
            if not text:
                return None, ("AI returned an empty response.", 502)
            return text.strip(), None
        except requests.RequestException:
            return None, ("AI service is temporarily unavailable.", 503)

    @bp.post("/api/ai/caption")
    def ai_caption():
        auth = require_login()
        if auth:
            return auth
        data = request.get_json(silent=True) or {}
        title = str(data.get("title", "")).strip()[:300]
        context = str(data.get("context", "")).strip()[:1200]
        language = str(data.get("language", "English")).strip()[:40]
        tone = str(data.get("tone", "premium and natural")).strip()[:80]
        if not title and not context:
            return jsonify({"success": False, "message": "Add a video title or description."}), 400

        instructions = (
            "You are Tick Tock's creator assistant. Create concise, original social-video copy. "
            "Do not invent facts, copyrighted lyrics, quotes, or brand claims. "
            "Return valid JSON only with keys: caption, hashtags, hook. "
            "hashtags must be an array of 5 to 8 short hashtags without #. "
            "Keep the caption under 180 characters and hook under 90 characters."
        )
        prompt = json.dumps({
            "language": language,
            "tone": tone,
            "title": title,
            "context": context,
        }, ensure_ascii=False)
        text, err = call_openai(instructions, prompt, max_output=500)
        if err:
            return jsonify({"success": False, "message": err[0]}), err[1]
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = {"caption": text, "hashtags": [], "hook": ""}
        return jsonify({"success": True, "result": parsed})

    @bp.post("/api/ai/creator-plan")
    def ai_creator_plan():
        auth = require_login()
        if auth:
            return auth
        data = request.get_json(silent=True) or {}
        idea = str(data.get("idea", "")).strip()[:1500]
        language = str(data.get("language", "English")).strip()[:40]
        if not idea:
            return jsonify({"success": False, "message": "Tell Tick Tock what you want to create."}), 400

        instructions = (
            "You are Tick Tock's creator coach. Turn a short-video idea into a practical original plan. "
            "Do not copy existing creators or copyrighted scripts. Return JSON only with keys: "
            "hook, shot_list, voiceover, caption, hashtags, posting_tip. "
            "shot_list must be an array of 4 to 7 short shots; hashtags an array of 5 to 8 items."
        )
        text, err = call_openai(
            instructions,
            json.dumps({"language": language, "idea": idea}, ensure_ascii=False),
            max_output=1100,
        )
        if err:
            return jsonify({"success": False, "message": err[0]}), err[1]
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = {"hook": text, "shot_list": [], "voiceover": "", "caption": "", "hashtags": [], "posting_tip": ""}
        return jsonify({"success": True, "result": parsed})

    @bp.post("/api/ai/search")
    def ai_search():
        auth = require_login()
        if auth:
            return auth
        data = request.get_json(silent=True) or {}
        query = str(data.get("query", "")).strip()[:300]
        if not query:
            return jsonify({"success": False, "message": "Type something to search."}), 400

        # AI turns natural language into safe search terms; actual results still come
        # from Tick Tock's own database.
        instructions = (
            "You are Tick Tock's search assistant. Convert the user's natural-language request "
            "into database search terms. Return JSON only: {\"terms\": [..], \"category\": \"...\"}. "
            "Use at most 6 short terms. Do not invent usernames."
        )
        text, err = call_openai(instructions, query, max_output=250)
        if err:
            return jsonify({"success": False, "message": err[0]}), err[1]
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = {"terms": [query], "category": "general"}

        terms = [str(x).strip()[:80] for x in parsed.get("terms", []) if str(x).strip()][:6]
        if not terms:
            terms = [query]

        db = get_db()
        clauses = []
        params = []
        for term in terms:
            like = f"%{term}%"
            clauses.append(
                "(lower(title) LIKE lower(?) OR lower(COALESCE(caption,'')) LIKE lower(?) "
                "OR lower(COALESCE(tags,'')) LIKE lower(?) OR lower(creator) LIKE lower(?))"
            )
            params.extend([like, like, like, like])
        where = " OR ".join(clauses)
        rows = db.execute(
            f"SELECT id,title,url,creator,caption,tags FROM videos "
            f"WHERE privacy='public' AND ({where}) ORDER BY created_at DESC LIMIT 30",
            tuple(params),
        ).fetchall()
        db.close()
        return jsonify({
            "success": True,
            "query": query,
            "category": str(parsed.get("category", "general"))[:60],
            "terms": terms,
            "videos": [dict(row) for row in rows],
        })

    @bp.post("/api/ai/comment-replies")
    def ai_comment_replies():
        auth = require_login()
        if auth:
            return auth
        data = request.get_json(silent=True) or {}
        comment = str(data.get("comment", "")).strip()[:500]
        if not comment:
            return jsonify({"success": False, "message": "Add a comment first."}), 400
        instructions = (
            "You are a friendly social creator assistant. Suggest 3 short, respectful replies "
            "to the user's comment. No harassment, sexual content, threats, or manipulative language. "
            "Return JSON only: {\"replies\": [\"...\",\"...\",\"...\"]}."
        )
        text, err = call_openai(instructions, comment, max_output=300)
        if err:
            return jsonify({"success": False, "message": err[0]}), err[1]
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = {"replies": [text]}
        return jsonify({"success": True, "replies": parsed.get("replies", [])[:3]})

    @bp.post("/api/ai/moderate-text")
    def ai_moderate_text():
        auth = require_login()
        if auth:
            return auth
        data = request.get_json(silent=True) or {}
        text = str(data.get("text", "")).strip()[:2000]
        if not text:
            return jsonify({"success": False, "message": "Text is empty."}), 400
        instructions = (
            "Classify this user-generated social text for a moderation pre-check. "
            "This is NOT the final moderation decision. Return JSON only with keys: "
            "risk (low/medium/high), categories (array), reason (short), action (allow/review/block). "
            "Be conservative; high-risk content should be sent to human review."
        )
        result, err = call_openai(instructions, text, max_output=350)
        if err:
            return jsonify({"success": False, "message": err[0]}), err[1]
        try:
            parsed = json.loads(result)
        except Exception:
            parsed = {"risk": "medium", "categories": ["unknown"], "reason": result, "action": "review"}
        return jsonify({"success": True, "result": parsed})

    app.register_blueprint(bp)
