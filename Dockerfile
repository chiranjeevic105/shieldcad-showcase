# UNTESTED in the authoring environment - build and test before any pilot.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglu1-mesa libxrender1 libxext6 \
    && rm -rf /var/lib/apt/lists/* && useradd -m -u 10001 app
WORKDIR /app
RUN pip install --no-cache-dir cadquery fastapi uvicorn
COPY shieldcad ./shieldcad
COPY static ./static
ENV PYTHONPATH=/app SHIELDCAD_HOST=0.0.0.0 SHIELDCAD_DATA_DIR=/data
USER app
EXPOSE 8000
CMD ["python", "-m", "shieldcad.server"]
