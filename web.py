import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template

load_dotenv()

from app.db import SessionLocal, engine
from app.models import Base
from app.scanner import load_snapshot

Base.metadata.create_all(bind=engine)

app = Flask(__name__, template_folder="templates")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/arbs")
def api_arbs():
    with SessionLocal() as session:
        return jsonify(load_snapshot(session=session))


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
