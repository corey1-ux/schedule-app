from app import create_app
from database import init_db, init_blocks_db

app = create_app()

if __name__ == "__main__":
    init_db()
    init_blocks_db()
    app.run(debug=True)