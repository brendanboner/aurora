import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import './App.css';
import Header from './components/Header';
import Sidebar from './components/Sidebar';
import Chatbot from './pages/Chatbot';
import UserProfile from './pages/UserProfile';
import AdminUsers from './pages/AdminUsers';
import AdminKnowledgeGraph from './pages/AdminKnowledgeGraph';
import AdminMonitoring from './pages/AdminMonitoring';
import AdminSystemConfig from './pages/AdminSystemConfig';
import News from './pages/News';
import { testBackendConnection } from './services/api';

function App() {
  const [backendStatus, setBackendStatus] = useState('checking');
  const [currentUser, setCurrentUser] = useState(null);
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
    
    // Try to load user from localStorage
    const savedUser = localStorage.getItem('currentUser');
    if (savedUser) {
      try {
        setCurrentUser(JSON.parse(savedUser));
      } catch (e) {
        localStorage.removeItem('currentUser');
      }
    }

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

  const handleUserChange = (user) => {
    setCurrentUser(user);
    if (user) {
      localStorage.setItem('currentUser', JSON.stringify(user));
    } else {
      localStorage.removeItem('currentUser');
    }
  };

  const toggleSidebar = () => {
    setSidebarOpen(prev => !prev);
  };

  return (
    <Router>
      <div className="App">
        <div className="app-shell">
          <Header 
            currentUser={currentUser}
            onLogout={() => handleUserChange(null)}
          />
          <div className="app-layout">
              <main className={`main-content ${sidebarOpen ? 'sidebar-open' : 'sidebar-closed'}`}>
                <div className={`layout-inner ${sidebarOpen ? 'with-sidebar' : 'collapsed-sidebar'}`}>
                  <div className={`sidebar-container ${sidebarOpen ? 'open' : 'closed'}`}>
                    <Sidebar 
                      isOpen={sidebarOpen}
                      onToggle={toggleSidebar}
                      backendStatus={backendStatus}
                    />
                  </div>
                  <div className="page-container">
                    <Routes>
                <Route 
                  path="/" 
                  element={<Chatbot currentUser={currentUser} backendStatus={backendStatus} />} 
                />
                <Route 
                  path="/news" 
                  element={<News currentUser={currentUser} backendStatus={backendStatus} />} 
                />
                {/* New discrete admin pages */}
                <Route path="/admin/users" element={<AdminUsers onUserChange={handleUserChange} currentUser={currentUser} />} />
                <Route path="/admin/knowledge-graph" element={<AdminKnowledgeGraph />} />
                <Route path="/admin/monitoring" element={<AdminMonitoring />} />
                <Route path="/admin/system-config" element={<AdminSystemConfig />} />
                <Route 
                  path="/profile" 
                  element={<UserProfile currentUser={currentUser} onUserChange={handleUserChange} />} 
                />
                <Route 
                  path="/profile/topics" 
                  element={<UserProfile currentUser={currentUser} onUserChange={handleUserChange} />} 
                />
                <Route 
                  path="/profile/organisations" 
                  element={<UserProfile currentUser={currentUser} onUserChange={handleUserChange} />} 
                />
                <Route 
                  path="/profile/people" 
                  element={<UserProfile currentUser={currentUser} onUserChange={handleUserChange} />} 
                />
                <Route 
                  path="/profile/notifications" 
                  element={<UserProfile currentUser={currentUser} onUserChange={handleUserChange} />} 
                />
                <Route path="*" element={<Navigate to="/" replace />} />
                  </Routes>
                </div>
              </div>
            </main>
          </div>
        </div>
      </div>
    </Router>
  );
}

export default App;
