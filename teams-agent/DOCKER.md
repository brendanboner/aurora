# Docker Setup for Aurora Teams Agent

This guide covers running the Teams agent in Docker with full debugging support.

## Quick Start

### 1. Development Mode (with debugging)

```bash
# Build and start in development mode with hot reload
make build-dev
make up-dev

# View logs
make logs-dev
```

The agent will be available at:
- **Bot endpoint:** http://localhost:3978
- **Debug port:** localhost:9229

### 2. Production Mode

```bash
# Build and start in production mode
make build
make up

# View logs
make logs
```

## Prerequisites

1. **Docker & Docker Compose** installed
2. **Aurora backend running** (accessible at localhost:8000)
3. **Bot credentials** configured in `.env` file

### Create .env file

```bash
cp .env.dev .env
# Edit .env and add your Bot ID and Password
```

## Docker Compose Services

### `teams-agent` (Production)
- Optimized multi-stage build
- Production dependencies only
- No debugging ports
- Minimal image size

### `teams-agent-dev` (Development)
- Full development dependencies
- Hot reload with nodemon
- **Debug port 9229** exposed
- Source code mounted for instant updates

## Makefile Commands

```bash
make help              # Show all available commands

# Development
make build-dev         # Build development image
make up-dev           # Start development container
make logs-dev         # View development logs
make restart-dev      # Restart development container

# Production
make build            # Build production image
make up               # Start production container
make logs             # View production logs
make restart          # Restart production container

# Management
make down             # Stop all containers
make status           # Check container status and health
make shell            # Open shell in production container
make shell-dev        # Open shell in development container
make clean            # Remove all containers, images, and volumes

# Debugging
make debug-attach     # Show debugger attachment instructions
make quickstart       # Quick start in dev mode with logs
```

## Debugging in VS Code

### Method 1: Using Launch Configuration (Recommended)

1. **Start the development container:**
   ```bash
   make up-dev
   ```

2. **In VS Code:**
   - Press `Cmd+Shift+D` (or View → Run and Debug)
   - Select **"Docker: Debug Teams Agent"**
   - Press `F5` to attach debugger

3. **Set breakpoints** in your TypeScript files and they'll hit automatically!

### Method 2: Manual Attach

1. Start dev container: `make up-dev`
2. Go to Run and Debug panel
3. Select **"Attach to Docker"**
4. Press F5

### Debug Configuration Details

The debug configuration in `.vscode/launch.json`:
```json
{
  "name": "Docker: Debug Teams Agent",
  "type": "node",
  "request": "attach",
  "port": 9229,
  "address": "localhost",
  "localRoot": "${workspaceFolder}/src",
  "remoteRoot": "/app/src",
  "restart": true
}
```

## Debugging in Chrome DevTools

1. **Start dev container:**
   ```bash
   make up-dev
   ```

2. **Open Chrome and navigate to:**
   ```
   chrome://inspect
   ```

3. **Configure network targets:**
   - Click "Configure"
   - Add `localhost:9229`
   - Click "Done"

4. **Inspect the target:**
   - Find "Remote Target" section
   - Click "inspect" under your node process
   - DevTools will open with full debugging capabilities

## Hot Reload in Development

The development container has hot reload enabled:

1. Start dev container: `make up-dev`
2. Edit any file in `src/`
3. Save the file
4. Nodemon automatically restarts the bot
5. Changes take effect immediately

**Mounted directories:**
- `./src` → `/app/src` (read-only)
- `./package.json` → `/app/package.json`
- `./tsconfig.json` → `/app/tsconfig.json`

## Networking

### Accessing Aurora Backend

The Teams agent needs to communicate with Aurora backend services. Two options:

**Option 1: Host Network (Recommended for local dev)**
```yaml
environment:
  - AURORA_API_URL=http://host.docker.internal:8000
```

**Option 2: Bridge Network**
```yaml
networks:
  - aurora-network
environment:
  - AURORA_API_URL=http://aurora-backend:8000
```

Make sure the `aurora-network` exists:
```bash
docker network create aurora-network
```

### Port Mappings

- **3978** → Bot Framework messages endpoint
- **9229** → Node.js debug port (dev only)

## Health Checks

Both containers include health checks:

```bash
# Check health status
make status

# Or manually
curl http://localhost:3978/api/health
```

Expected response:
```json
{
  "status": "healthy",
  "timestamp": "2026-01-14T...",
  "service": "aurora-teams-agent",
  "aurora_api": "http://host.docker.internal:8000"
}
```

## Troubleshooting

### Container won't start

```bash
# Check logs
make logs-dev

# Check container status
docker-compose ps

# Check if port is already in use
lsof -i :3978
lsof -i :9229
```

### Can't attach debugger

1. **Verify debug port is exposed:**
   ```bash
   docker-compose ps
   # Should show 0.0.0.0:9229->9229/tcp
   ```

2. **Check if debugger is listening:**
   ```bash
   nc -zv localhost 9229
   # Should show: Connection to localhost port 9229 [tcp/*] succeeded!
   ```

3. **View container logs:**
   ```bash
   make logs-dev
   # Should see: Debugger listening on ws://0.0.0.0:9229/...
   ```

### Can't connect to Aurora backend

```bash
# Test connectivity from inside container
make shell-dev
curl http://host.docker.internal:8000/api/auth/health

# Or from host
curl http://localhost:8000/api/auth/health
```

If `host.docker.internal` doesn't work, try:
- **Linux:** Use `--add-host=host.docker.internal:host-gateway`
- **Alternative:** Connect to Aurora network and use service names

### Hot reload not working

1. **Check volume mounts:**
   ```bash
   docker inspect aurora-teams-agent-dev | grep -A 10 Mounts
   ```

2. **Check file permissions:**
   ```bash
   ls -la src/
   ```

3. **Restart with fresh build:**
   ```bash
   make clean
   make build-dev
   make up-dev
   ```

### Source maps not working in debugger

1. Ensure TypeScript source maps are enabled in `tsconfig.json`:
   ```json
   {
     "compilerOptions": {
       "sourceMap": true
     }
   }
   ```

2. Verify `localRoot` and `remoteRoot` match in launch config

3. Rebuild container: `make build-dev`

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `BOT_ID` | Microsoft Bot Framework App ID | (required) |
| `BOT_PASSWORD` | Microsoft Bot Framework App Password | (required) |
| `BOT_PORT` | Port the bot listens on | 3978 |
| `AURORA_API_URL` | Aurora backend API URL | http://host.docker.internal:8000 |
| `AURORA_FRONTEND_URL` | Aurora frontend URL | http://localhost:3000 |
| `NODE_ENV` | Node environment | development/production |

## Docker Best Practices Used

✅ **Multi-stage builds** - Smaller production images  
✅ **Non-root user** - Security best practice  
✅ **Health checks** - Container orchestration support  
✅ **dumb-init** - Proper signal handling  
✅ **Volume mounts** - Fast development iteration  
✅ **Debug port** - Full debugging support  
✅ **Hot reload** - Instant feedback during development  

## Production Deployment

For production, use the production Dockerfile:

```bash
# Build production image
make build

# Or with docker-compose
docker-compose build teams-agent

# Start production container
make up

# Or deploy to container registry
docker tag aurora-teams-agent:latest your-registry/aurora-teams-agent:v1.0.0
docker push your-registry/aurora-teams-agent:v1.0.0
```

## Integration with Main Aurora Docker Compose

To integrate with the main Aurora `docker-compose.yml`:

1. Add teams-agent service to main docker-compose
2. Use the aurora-network
3. Reference aurora backend by service name

Example:
```yaml
# In /octo-rapid-aurora/docker-compose.yml
services:
  teams-agent:
    build:
      context: ./teams-agent
      dockerfile: Dockerfile
    environment:
      - AURORA_API_URL=http://auth:8000
      - AURORA_FRONTEND_URL=http://frontend:3000
    networks:
      - aurora-network
```

## Summary

- ✅ Full debugging support with VS Code and Chrome DevTools
- ✅ Hot reload for fast development
- ✅ Production-optimized builds
- ✅ Health checks and monitoring
- ✅ Easy commands via Makefile
- ✅ Proper networking with Aurora backend

**Ready to develop!** Start with `make quickstart` to see everything in action.
