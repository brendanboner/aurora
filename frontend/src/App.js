import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import './App.css';
import { AuthProvider } from './contexts/AuthContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import Header from './components/Header';
import Sidebar from './components/Sidebar';
import Chatbot from './pages/Chatbot';
import UserProfile from './pages/UserProfile';
import AdminUsers from './pages/AdminUsers';
import AdminKnowledgeGraph from './pages/AdminKnowledgeGraph';
import AdminMonitoring from './pages/AdminMonitoring';
import AdminSystemConfig from './pages/AdminSystemConfig';
import AdminContentQuality from './pages/AdminContentQuality';
import AdminChatSessions from './pages/AdminChatSessions';
import News from './pages/News';
import Events from './pages/Events';
import EventDetail from './pages/EventDetail';
import SocialFeed from './pages/SocialFeed';
import AgentManagement from './pages/AgentManagement';
import AgentPreferences from './pages/AgentPreferences';
import DocumentSearch from './pages/DocumentSearch';
import { testBackendConnection } from './services/api';

// Pages that should have no padding in the page-container
const NO_PADDING_ROUTES = ['/documents'];

function App() {
  const [backendStatus, setBackendStatus] = useState('checking');
  const [sidebarOpen, setSidebarOpen] = useState(true);

  useEffect(() => {
    // Check backend connection on startup
    const checkBackend = async () => {
      try {
        const isConnected = await testBackendConnection();
        setBackendStatus(isConnected ? 'connected' : 'disconnected');
      } catch (error) {
        console.error('Backend connection error:', error);
        setBackendStatus('disconnected');
      }
    };

    checkBackend();

    // Check if mobile on initial load
    const handleResize = () => {
      if (window.innerWidth <= 768) {
        setSidebarOpen(false);
      }
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const toggleSidebar = () => {
    setSidebarOpen(prev => !prev);
  };

  return (
    <AuthProvider>
      <Router>
        <AppContent 
          backendStatus={backendStatus}
          sidebarOpen={sidebarOpen}
          toggleSidebar={toggleSidebar}
        />
      </Router>
    </AuthProvider>
  );
}

// Separate component to use useLocation inside Router
function AppContent({ backendStatus, sidebarOpen, toggleSidebar }) {
  const location = useLocation();
  const noPadding = NO_PADDING_ROUTES.includes(location.pathname);

  return (
    <div className="App">
      <Routes>
        {/* All routes are protected - unauthenticated users redirect to Cognito */}
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <div className="app-shell">
                <Header onMenuToggle={toggleSidebar} />
                <div className="sidebar-container">
                  <Sidebar 
                    isOpen={sidebarOpen}
                    onToggle={toggleSidebar}
                    backendStatus={backendStatus}
                  />
                </div>
                <div className={`page-container ${noPadding ? 'no-padding' : ''}`}>
                  <Routes>
                    <Route 
                      path="/" 
                      element={<Chatbot backendStatus={backendStatus} />} 
                    />
                    <Route 
                      path="/news" 
                      element={<News backendStatus={backendStatus} />} 
                    />
                    
                        {/* Events routes */}
                        <Route 
                          path="/events" 
                          element={<Events />} 
                        />
                        <Route 
                          path="/events/:urlHash" 
                          element={<EventDetail />} 
                        />
                        
                        {/* Document Search */}
                        <Route 
                          path="/documents" 
                          element={<DocumentSearch />} 
                        />
                        
                        {/* Social Network routes */}
                        <Route 
                          path="/feed" 
                          element={<SocialFeed />} 
                        />
                              
                              {/* User Profile routes */}
                              <Route 
                                element={<UserProfile />} 
                              />
                              <Route 
                                path="/profile/topics" 
                                element={<UserProfile />} 
                              />
                              <Route 
                                path="/profile/organisations" 
                                element={<UserProfile />} 
                              />
                              <Route 
                                path="/profile/people" 
                                element={<UserProfile />} 
                              />
                              <Route 
                                path="/profile/notifications" 
                                element={<UserProfile />} 
                              />
                              <Route 
                                path="/profile/agents" 
                                element={<AgentPreferences />} 
                              />
                              
                              {/* Admin routes - require admin or superadmin role */}
                              <Route 
                                path="/admin/users" 
                                element={
                                  <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                                    <AdminUsers />
                                  </ProtectedRoute>
                                } 
                              />
                              <Route 
                                path="/admin/knowledge-graph" 
                                element={
                                  <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                                    <AdminKnowledgeGraph />
                                  </ProtectedRoute>
                                } 
                              />
                              <Route 
                                path="/admin/monitoring" 
                                element={
                                  <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                                    <AdminMonitoring />
                                  </ProtectedRoute>
                                } 
                              />
                              <Route 
                                path="/admin/system-config" 
                                element={
                                  <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                                    <AdminSystemConfig />
                                  </ProtectedRoute>
                                } 
                              />
                              <Route 
                                path="/admin/content-quality" 
                                element={
                                  <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                                    <AdminContentQuality />
                                  </ProtectedRoute>
                                } 
                              />
                              <Route 
                                path="/admin/chat-sessions" 
                                element={
                                  <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                                    <AdminChatSessions />
                                  </ProtectedRoute>
                                } 
                              />
                              
                              {/* Admin Creator Agents route */}
                              <Route 
                                path="/admin/agents" 
                                element={
                                  <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                                    <AgentManagement />
                                  </ProtectedRoute>
                                } 
                              />
                              
                              {/* Redirect unknown routes to home */}
                              <Route path="*" element={<Navigate to="/" replace />} />
                            </Routes>
                          </div>
                        </div>
                </ProtectedRoute>
              }
            />
          </Routes>
        </div>
  );
}

export default App;
