FROM python:3.12-slim

# Install ffmpeg and build dependencies
RUN apt-get update && \
    apt-get install -y \
    ffmpeg \
    gcc \
    g++ \
    python3-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY bot.py lastfm.py musicbrainz.py ./

# Run the bot
CMD ["python", "-u", "bot.py"]