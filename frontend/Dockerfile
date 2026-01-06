# Build React app and output to shared volume
FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy source code
COPY . .

# Build the React app
RUN npm run build

# Script to copy fresh build to volume (which is mounted at /app/build)
# We build to /tmp/build during image creation, then copy to /app/build at runtime
RUN mv /app/build /tmp/build

# Copy fresh build files to volume on container start, then exit
CMD ["sh", "-c", "cp -r /tmp/build/* /app/build/ && echo 'Frontend build copied successfully'"]

# No exposed ports needed - this is just a build container
