import os,sys
os.environ["ENV"]="test"
os.environ["SECRET_KEY"]="test-secret-key-012345678901234567890123"
os.environ["SQLITE_FILE"]=":memory:"
sys.path.insert(0,os.path.abspath(os.path.join(os.path.dirname(__file__),"..","backend")))
def test_app_imports():
    from main import app
    assert app.title=="Tick Tock API"
