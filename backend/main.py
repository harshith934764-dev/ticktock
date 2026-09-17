from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import init_db
from users import router as users_router
from videos import router as videos_router
from social import router as social_router
from auth import router as auth_router
from ai import router as ai_router
from analytics import router as analytics_router

app = FastAPI(title='Tick Tock API', version='1.0.0')
app.include_router(users_router)
app.include_router(videos_router)
app.include_router(social_router)
app.include_router(auth_router)
app.include_router(ai_router)
app.include_router(analytics_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

@app.on_event('startup')
def startup():
    init_db()

@app.get('/')
def root():
    return {'app': 'Tick Tock', 'backend': 'FastAPI', 'status': 'running'}

@app.get('/healthz')
def healthz():
    return {'status': 'ok', 'service': 'ticktock-fastapi'}

@app.get('/api')
def api_info():
    return {
        'name': 'Tick Tock API',
        'version': '1.0.0',
        'status': 'ready',
        'routes': ['/healthz', '/api/users', '/api/videos'],
    }
