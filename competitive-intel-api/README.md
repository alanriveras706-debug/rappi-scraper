# Competitive Intelligence 

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

```bash
python main.py                              # todas las plataformas, 25 direcciones
python main.py --platform rappi             # solo Rappi
python main.py --platform rappi --limit 3   # solo Rappi, primeras 3 direcciones
python main.py --platform ubereats --limit 5
```

Output en `data/raw/` y `data/processed/`.
