from fastapi import APIRouter

router = APIRouter(prefix='/api/auth', tags=['auth'])

@router.get('/status')
def auth_status():
    return {
        'status': 'foundation-ready',
        'message': 'Authentication migration comes next. Existing Flask authentication remains untouched.'
    }
