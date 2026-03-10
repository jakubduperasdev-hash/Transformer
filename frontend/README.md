# Romantic Chatbot Frontend

## Run the frontend

**Option 1 – One command (PowerShell)**  
From anywhere, run the script:
```powershell
& "C:\Users\Administrator\Downloads\transformers-main\frontend\run-dev.ps1"
```

**Option 2 – Manual steps**  
In PowerShell, run these in order in the **same** terminal (so `cd` stays in effect):
```powershell
cd C:\Users\Administrator\Downloads\transformers-main\frontend
npm install
npm run dev
```

Then open http://localhost:5173 in your browser.

Make sure the backend is running first (`python api.py` from the project root with the venv activated).
