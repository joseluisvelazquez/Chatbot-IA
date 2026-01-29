from fastapi import FastAPI

app = FastAPI(title="MXCOMP Chatbot")

@app.get("/")
def health():
    return {"status": "ok"}
