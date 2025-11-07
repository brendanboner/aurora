import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider, Link } from 'react-router-dom'

function Overview(){return <main style={{padding:24}}><h1>Overview</h1></main>}
function Profile(){return <main style={{padding:24}}><h1>Profile</h1></main>}
function Admin(){return <main style={{padding:24}}><h1>Admin</h1></main>}

const Nav = () => (
  <nav style={{display:'flex',gap:12,padding:12,borderBottom:'1px solid #eee'}}>
    <Link to="/">Overview</Link>
    <Link to="/profile">Profile</Link>
    <Link to="/admin">Admin</Link>
  </nav>
)

const router = createBrowserRouter([
  { path: '/', element: <><Nav/><Overview/></> },
  { path: '/profile', element: <><Nav/><Profile/></> },
  { path: '/admin', element: <><Nav/><Admin/></> },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
