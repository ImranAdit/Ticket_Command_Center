# --- Builder Stage: Compile the React frontend ---
FROM node:18-alpine AS builder

WORKDIR /app

# Copy package files from root
COPY package*.json ./
RUN npm install

# Copy all files from root to build the frontend
COPY . .
RUN npm run build

# --- Runtime Stage: Serve FastAPI and built React frontend ---
FROM python:3.11-slim

WORKDIR /app

# Install backend dependencies from root
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all backend source files from root
COPY . .

# Copy the built frontend from the builder stage
# Adjust 'dist' to 'build' if you are using Create React App instead of Vite
COPY --from=builder /app/dist ./static

# Expose standard port
EXPOSE 8080

# Command to run FastAPI server
# Using ${PORT:-8080} ensures it works locally and on Railway
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
