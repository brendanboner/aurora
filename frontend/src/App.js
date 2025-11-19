import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import './App.css';
import Navigation from './components/Navigation';
import Chatbot from './pages/Chatbot';
import Admin from './pages/Admin';
import UserProfile from './pages/UserProfile';
import { testBackendConnection } from './services/api';

function App() {
  const [backendStatus, setBackendStatus] = useState('checking');
  const [currentUser, setCurrentUser] = useState(null);

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
  }, []);

  const handleUserChange = (user) => {
    setCurrentUser(user);
    if (user) {
      localStorage.setItem('currentUser', JSON.stringify(user));
    } else {
      localStorage.removeItem('currentUser');
    }
  };

  return (
    <Router>
      <div className="App">
        <Navigation 
          backendStatus={backendStatus} 
          currentUser={currentUser}
          onLogout={() => handleUserChange(null)}
        />
        <main className="main-content">
          <Routes>
            <Route 
              path="/" 
              element={
                <Chatbot 
                  currentUser={currentUser} 
                  backendStatus={backendStatus}
                />
              } 
            />
            <Route 
              path="/admin" 
              element={
                <Admin 
                  onUserChange={handleUserChange}
                  currentUser={currentUser}
                />
              } 
            />
            <Route 
              path="/profile" 
              element={
                <UserProfile 
                  currentUser={currentUser}
                  onUserChange={handleUserChange}
                />
              } 
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App;
