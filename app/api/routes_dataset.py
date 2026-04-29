from fastapi import APIRouter, UploadFile, File
import pandas as pd
import os

from app.models.train_model import train_from_csv

router = APIRouter()

UPLOAD_DIR = "data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/upload-dataset")
async def upload_dataset(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)

    with open(file_path, "wb") as f:
        f.write(await file.read())

    result = train_from_csv(file_path)

    return {"message": "Dataset uploaded and model trained", "details": result}
