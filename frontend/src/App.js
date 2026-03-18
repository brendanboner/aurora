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
import AdminOracleSettings from './pages/AdminOracleSettings';
import AdminChatSessions from './pages/AdminChatSessions';
import AdminFeedback from './pages/AdminFeedback';
import AdminDLQ from './pages/AdminDLQ';
import AdminCuration from './pages/AdminCuration';
import Events from './pages/Events';
import EventDetail from './pages/EventDetail';
import SocialFeed from './pages/SocialFeed';
import AgentManagement from './pages/AgentManagement';
import AgentPreferences from './pages/AgentPreferences';
import MyAgents from './pages/MyAgents';
import DocumentSearch from './pages/DocumentSearch';
import DocumentUpload from './pages/DocumentUpload';
import MyDocuments from './pages/MyDocuments';
import UserGuide from './pages/UserGuide';
import SubmitFeedback from './pages/SubmitFeedback';
import TeamsTab from './pages/TeamsTab';
import { testBackendConnection } from './services/api';

// Pages that should have no padding in the page-container
const NO_PADDING_ROUTES = ['/documents'];

function App() {
  const [backendStatus, setBackendStatus] = useState('checking');
  const [menuOpen, setMenuOpen] = useState(false);

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
  }, []);

  const toggleMenu = () => {
    setMenuOpen((prev) => !prev);
  };

  const closeMenu = () => {
    setMenuOpen(false);
  };

  return (
    <AuthProvider>
      <Router>
        <AppContent 
          backendStatus={backendStatus}
          menuOpen={menuOpen}
          toggleMenu={toggleMenu}
          closeMenu={closeMenu}
        />
      </Router>
    </AuthProvider>
  );
}

// Separate component to use useLocation inside Router
function AppContent({ backendStatus, menuOpen, toggleMenu, closeMenu }) {
  const location = useLocation();
  const noPadding = NO_PADDING_ROUTES.includes(location.pathname);

  return (
    <div className="App">
      <Routes>
        {/* Teams Tab - Full screen, no header/sidebar */}
        <Route
          path="/teams"
          element={
            <ProtectedRoute>
              <TeamsTab backendStatus={backendStatus} />
            </ProtectedRoute>
          }
        />

        {/* All other routes are protected - unauthenticated users redirect to Cognito */}
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <div className="app-shell">
                <Header onMenuToggle={toggleMenu} isMenuOpen={menuOpen} />
                <Sidebar
                  isOpen={menuOpen}
                  onToggle={toggleMenu}
                  onClose={closeMenu}
                  backendStatus={backendStatus}
                />
                <div className={`page-container ${noPadding ? 'no-padding' : ''}`}>
                  <Routes>
                    <Route 
                      path="/" 
                      element={<Chatbot backendStatus={backendStatus} />} 
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
                        
                        {/* Document Upload */}
                        <Route 
                          path="/upload" 
                          element={<DocumentUpload />} 
                        />
                        
                        {/* My Documents */}
                        <Route 
                          path="/my-documents" 
                          element={<MyDocuments />} 
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
                              <Route 
                                path="/profile/my-agents" 
                                element={<MyAgents />} 
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
                                path="/admin/oracle-settings" 
                                element={
                                  <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                                    <AdminOracleSettings />
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
                              <Route 
                                path="/admin/dlq" 
                                element={
                                  <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                                    <AdminDLQ />
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
                              
                              {/* Admin Curation route */}
                              <Route 
                                path="/admin/curation" 
                                element={
                                  <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                                    <AdminCuration />
                                  </ProtectedRoute>
                                } 
                              />
                              
                              {/* User Guide route */}
                              <Route 
                                path="/guide" 
                                element={<UserGuide />} 
                              />
                              
                              {/* Submit Feedback route */}
                              <Route 
                                path="/feedback" 
                                element={<SubmitFeedback />} 
                              />
                              
                              {/* Admin Feedback route */}
                              <Route 
                                path="/admin/feedback" 
                                element={
                                  <ProtectedRoute requiredRole={['admin', 'superadmin']}>
                                    <AdminFeedback />
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
