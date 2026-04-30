# --- STEP 1: Build Frontend ---
FROM node:20-alpine AS builder
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

# Copy everything else to build the frontend
COPY frontend/ ./
RUN npm run build

# --- STEP 2: Setup Backend ---
FROM python:3.11-slim
WORKDIR /app

# Install backend dependencies
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
COPY backend/start.sh /app/start.sh
RUN chmod +x /app/start.sh
CMD ["/app/start.sh"]
