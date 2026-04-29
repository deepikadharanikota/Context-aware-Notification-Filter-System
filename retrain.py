"""
Run this ONCE to fix the sklearn version mismatch warning and retrain the model
on your local Python environment.

Usage:
    python retrain.py
"""
import os, sys

# Make sure we're in the project root
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')

pkl = os.path.join('models_saved', 'priority_model.pkl')
if os.path.exists(pkl):
    os.remove(pkl)
    print(f"Deleted old model: {pkl}")

from app.models.priority_model import train_model
model = train_model()
print("Model retrained successfully on your sklearn version.")
print("You can now start the server normally:")
print("  uvicorn app.main:app --reload")
