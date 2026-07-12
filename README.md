# Gen-Alpha: Autonomous Quantitative Research System

Gen-Alpha is an end-to-end intelligent alpha-mining pipeline that programmatically sources academic literature from ArXiv, synthesizes tradeable WorldQuant BRAIN expressions using a Large Language Model (Llama 3.3 via Groq), and validates/simulates their performance. The project features a premium React-based dashboard for Alpha Factory management and Portfolio Simulation.

## Architecture
1. **ArXiv Miner (`arxiv_pipeline.py`)**: Fetches papers from ArXiv based on specific quantitative finance domains (Momentum, Sentiment, Value, Options).
2. **LLM Engine (`llm_client.py`)**: Prompts Llama 3.3 to extract cross-sectional equity anomalies and generates FASTEXPR formulas grounded in the proprietary `brain_operators.json` reference list.
3. **API Server (`api_server.py`)**: A lightweight Flask backend that triggers the generation pipeline and serves validated alphas, maintaining deterministic metrics and calculating a synthetic correlation matrix.
4. **React Dashboard (`frontend/`)**: A modern UI for triggering the pipeline, tracking top uncorrelated alphas, and simulating a hypothetical equal-weighted portfolio against user-defined budgets.

## Setup Instructions

### Prerequisites
- Python 3.8+
- Node.js & npm (v16+)
- Groq API Keys

### 1. Environment Setup
Create a `.env` file in the root directory (where `pipeline.py` is) and add your API keys. The system uses round-robin key rotation to maximize rate limits:
```env
GROQ_API_KEY_1=your_key_here
GROQ_API_KEY_2=your_key_here
GROQ_API_KEY_3=your_key_here
```

### 2. Install Dependencies
Install the required Python and Node modules:
```bash
# Python dependencies
pip install -r requirements.txt

# React dependencies
cd frontend
npm install
cd ..
```

## How to Run the System

The dashboard requires both the backend API server and the frontend Vite server to be running simultaneously.

### Step 1: Start the Backend (Terminal 1)
From the root directory (`/home/adithya/Desktop/IQC`):
```bash
python3 api_server.py
```
*This starts the Flask server on `http://localhost:5000`.*

### Step 2: Start the Frontend (Terminal 2)
Open a new terminal window, navigate to the `frontend` folder, and start the Vite dev server:
```bash
cd /home/adithya/Desktop/IQC/frontend
npm run dev
```
*This starts the dashboard on `http://localhost:5173`.*

### Step 3: Trigger the Pipeline
1. Open your browser and go to `http://localhost:5173`.
2. In the top right, use the **Domain Selector** dropdown to choose the quantitative finance domain you want to research (e.g., *Social Media Sentiment & News*).
3. Click **Trigger Pipeline**.
4. The dashboard will show a loading state ("Starting...") while the backend runs the `arxiv_pipeline.py` script. The script fetches 2 papers from ArXiv, extracts anomalies, generates valid expressions, and updates the library.
5. Once complete, the dashboard will automatically refresh to display the newly discovered alphas and the updated correlation heatmap.

## Notes
- Ensure you have a valid Internet connection for ArXiv scraping and BRAIN API requests.
- Rate limits apply to the BRAIN API, which the backend handles automatically.
