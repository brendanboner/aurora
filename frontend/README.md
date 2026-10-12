# Octo Rapid Aurora - Frontend

Professional dark mode LLM chat interface for the Octo Rapid Aurora knowledge management system.

## Features

- LLM Chat Interface: Modern chat UI with markdown support, document display, and filter visualization
- User Management: Create, view, and delete users with full CRUD operations
- Knowledge Graph Browser: Explore topics, organisations, and people with search and statistics
- User Preferences: Customizable preferences for topics, organisations, people, and notifications
- Dark Mode: Professional dark theme throughout the application
- Real-time Status: Backend connection status monitoring

## Tech Stack

- React 18.2.0
- React Router v6
- Axios for API calls
- React Markdown with remark-gfm
- Modern CSS with animations

## Installation

```bash
cd frontend
npm install
```

## Running the Application

Make sure the backend is running on `http://localhost:8000`, then:

```bash
npm start
```

The application will open at `http://localhost:3000`

## Project Structure

```
frontend/
├── public/
│   └── index.html          # HTML shell
├── src/
│   ├── components/
│   │   ├── Navigation.jsx  # Top navigation bar
│   │   └── Navigation.css
│   ├── pages/
│   │   ├── Chatbot.jsx     # Main chat interface
│   │   ├── Chatbot.css
│   │   ├── AdminUsers.jsx        # Users management page
│   │   ├── AdminKnowledgeGraph.jsx # Knowledge graph browsing
│   │   ├── AdminMonitoring.jsx     # Monitoring/status
│   │   ├── Admin.css          # Shared admin styles (users/graph/monitoring)
│   │   ├── UserProfile.jsx # User preferences
│   │   └── UserProfile.css
│   ├── services/
│   │   └── api.js          # Backend API client
│   ├── App.js              # Main app with routing
│   ├── App.css             # Shared styles
│   ├── index.js            # React entry point
│   └── index.css           # Global styles
├── package.json
└── README.md
```

## Pages

### Chatbot (/)
- Send queries to the LLM with context from the knowledge graph
- View document results with metadata
- See filter tags applied to queries
- Markdown rendering for formatted responses

### Admin Pages
- Users (/admin/users): Create new users, view all users, delete users
- Knowledge Graph (/admin/knowledge-graph): Browse topics, organisations, and people with search and statistics
- Monitoring (/admin/monitoring): View service status and activity

### User Profile (/profile)
- Select topics of interest
- Choose organisations to follow
- Track specific people
- Configure notification preferences
- Save preferences to backend

## API Integration

The frontend connects to the backend via the proxy configured in `package.json`:

```json
"proxy": "http://localhost:8000"
```

All API calls are centralized in `src/services/api.js`.

## Backend Endpoints Used

- `POST /users` - Create new user
- `GET /users` - List all users
- `GET /users/{id}` - Get user by ID
- `DELETE /users/{id}` - Delete user
- `GET /users/{id}/preferences` - Get user preferences
- `PUT /users/{id}/preferences` - Update user preferences
- `GET /graph/topics` - Get all topics
- `GET /graph/organisations` - Get all organisations
- `GET /graph/people` - Get all people
- `GET /graph/statistics` - Get graph statistics
- `POST /query` - Send query to LLM

## Development

To build for production:

```bash
npm run build
```

The optimized build will be created in the `build/` directory.

## User Workflow

1. **Create User**: Go to Admin page → Create new user with email and name
2. **Select User**: Click "Select" button on a user card to make them active
3. **Set Preferences**: Go to Profile page → Select topics, organisations, and people
4. **Chat**: Return to Chatbot page → Send queries with your preferences applied
5. **View Results**: See documents and responses based on your filtered preferences

## Notes

- User session is persisted in localStorage
- Backend status is checked on app startup
- All API calls include error handling
- Responsive design works on mobile devices
- Dark mode optimized for reduced eye strain
