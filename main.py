from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from analyzer import analyze_vacancy

app = FastAPI(title="JobChecker — детектор мошеннических вакансий")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


class VacancyRequest(BaseModel):
    input: str  # либо URL, либо текст вакансии


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.post("/analyze")
async def analyze(req: VacancyRequest):
    if not req.input or len(req.input.strip()) < 10:
        raise HTTPException(status_code=400, detail="Слишком короткий ввод")
    try:
        result = await analyze_vacancy(req.input.strip())
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
