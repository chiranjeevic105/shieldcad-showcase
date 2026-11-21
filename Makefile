install:  ; pip install cadquery fastapi uvicorn pytest httpx
test:     ; python -m pytest -q
serve:    ; python -m shieldcad.server
user:     ; python -m shieldcad.admin add-user $(NAME) $(ROLE)
