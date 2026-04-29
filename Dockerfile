# --- STEP 1: Build Frontend ---
FROM node:18-alpine AS builder
WORKDIR /app

# Copy ONLY package files first for better caching
COPY frontend/package.json ./
RUN npm install

# Copy everything else to build the frontend
COPY frontend/ ./
RUN npm run build

# --- STEP 2: Setup Backend ---
FROM python:3.11-slim
WORKDIR /app

# Install backend dependencies
# We use ./requirements.txt to be explicit
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy all source code
COPY backend/ ./

# Copy the built frontend
# DOUBLE CHECK: If your frontend build folder is named 'build' (CRA) 
# instead of 'dist' (Vite), change 'dist' to 'build' below.
COPY --from=builder /app/dist ./static

EXPOSE 8080

# Command to run FastAPI server
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
