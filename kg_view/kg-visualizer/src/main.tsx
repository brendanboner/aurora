import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import TestApp from './TestApp.tsx'

// Use TestApp temporarily to debug, then switch back to App
const USE_TEST_APP = false;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {USE_TEST_APP ? <TestApp /> : <App />}
  </StrictMode>,
)
