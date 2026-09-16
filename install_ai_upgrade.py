
#!/usr/bin/env python3
"""One-time installer for the Tick Tock AI upgrade.

Run from the repository root:
    python install_ai_upgrade.py

It creates a backup before editing app.py and templates/home.html.
"""
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parent
app=ROOT/"app.py"
home=ROOT/"templates"/"home.html"
if not home.exists():
    # Some earlier Tick Tock layouts stored the template at root.
    alt=ROOT/"home.html"
    if alt.exists(): home=alt

if not app.exists() or not home.exists():
    raise SystemExit("Could not find app.py and templates/home.html. Put this file in the Tick Tock repository root.")

for p in (app,home):
    shutil.copy2(p, p.with_suffix(p.suffix+".ai-backup"))

src=(ROOT/"ai_features.py").read_text(encoding="utf-8")
# Keep the installer self-contained: ai_features.py must remain in repo.
marker='app.register_blueprint(bp)'
if 'from ai_features import register_ai_routes' not in app.read_text(encoding="utf-8"):
    txt=app.read_text(encoding="utf-8")
    # Register after the existing routes are defined, immediately before main-run block.
    anchor='\nif __name__ == "__main__":'
    if anchor in txt:
        txt=txt.replace(anchor, '\n\n# Tick Tock AI upgrade\nfrom ai_features import register_ai_routes\nregister_ai_routes(app, get_db)\n'+anchor, 1)
    else:
        txt += '\n\n# Tick Tock AI upgrade\nfrom ai_features import register_ai_routes\nregister_ai_routes(app, get_db)\n'
    app.write_text(txt,encoding="utf-8")

h=home.read_text(encoding="utf-8")
if 'ai_ui.js' not in h:
    h=h.replace('</head>','<link rel="stylesheet" href="{{ url_for("static", filename="ai_ui.css") }}"><script defer src="{{ url_for("static", filename="ai_ui.js") }}"></script></head>',1)
if 'openTickTockAI' not in h:
    # Add a small AI button near the top command buttons without depending on existing markup.
    h=h.replace('<body>', '<body><button class="tt-ai-floating" onclick="openTickTockAI()" aria-label="Open Tick Tock AI">✨ AI</button>',1)
    h=h.replace('</style>',' .tt-ai-floating{position:fixed;left:18px;bottom:22px;z-index:9998;border:1px solid #ffffff18;background:#171820e8;color:#fff;border-radius:999px;padding:11px 15px;font-weight:900;box-shadow:0 14px 45px #0008;backdrop-filter:blur(14px)} .tt-ai-floating:hover{transform:translateY(-1px)}\n</style>',1)
    h=h.replace('</body>','</body>',1)
home.write_text(h,encoding="utf-8")
print("AI upgrade installed. Set OPENAI_API_KEY in Render and deploy.")
