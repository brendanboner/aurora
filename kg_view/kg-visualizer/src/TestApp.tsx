import { useState } from 'react';

function TestApp() {
  const [count, setCount] = useState(0);

  return (
    <div style={{ padding: '50px', background: '#1a1a1a', minHeight: '100vh', color: 'white' }}>
      <h1>Knowledge Graph Visualizer - Test Page</h1>
      <p>If you can see this, React is working!</p>
      <button 
        onClick={() => setCount(count + 1)}
        style={{ padding: '10px 20px', fontSize: '16px', cursor: 'pointer' }}
      >
        Count: {count}
      </button>
      
      <div style={{ marginTop: '30px' }}>
        <h2>Backend Connection Test</h2>
        <p>Backend URL: {import.meta.env.VITE_API_URL || 'http://localhost:8002'}</p>
        <button
          onClick={async () => {
            try {
              const response = await fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8002'}/health`);
              const data = await response.json();
              alert(`Backend Status: ${data.status}`);
            } catch (err) {
              alert(`Backend Error: ${err}`);
            }
          }}
          style={{ padding: '10px 20px', fontSize: '16px', cursor: 'pointer' }}
        >
          Test Backend Connection
        </button>
      </div>
    </div>
  );
}

export default TestApp;
