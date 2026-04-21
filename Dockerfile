# --- Builder Stage: Compile the React frontend ---
FROM node:18-alpine AS builder

WORKDIR /app/frontend

COPY frontend/package.json ./
RUN npm install

COPY frontend/ ./
RUN npm run build

# --- Runtime Stage: Serve FastAPI and built React frontend ---
FROM python:3.11-slim

WORKDIR /app/backend

# Install backend dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ .

# Ensure frontend build is accessible by FastAPI
# We'll copy the dist folder into the backend directory structure so fastapi can serve it easily
COPY --from=builder /app/frontend/dist ./static

# Expose standard port
EXPOSE $PORT

# Command to run FastAPI server (Port will be injected by Railway)
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
