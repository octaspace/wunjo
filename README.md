# Wunjo (OctaSpace)

Requirements: Python3.10, CUDA 12.4 or upper, CuDNN 9.x.

Init on Linux:
```
python3.10 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

Change .env:
```
DEBUG=True
PORT=8000
```

Run web:
```
python app.py
```