#!/bin/bash
echo "[1/3] Fetching full historical simulations from WorldQuant BRAIN..."
python3 fetch_brain_history.py

echo "[2/3] Retraining Gradient Boosting ML Screener on full data..."
python3 train_recommender.py

echo "[3/3] Launching autonomous extraction & simulation cycle..."
curl -X POST http://localhost:5000/api/trigger_pipeline
echo ""
echo "Pipeline kicked off! You can view live progress in the frontend dashboard."
