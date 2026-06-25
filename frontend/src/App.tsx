import { useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Starfield from './components/Starfield'
import BootScreen from './components/BootScreen'
import AuthGuard from './components/AuthGuard'
import ErrorBoundary from './components/ErrorBoundary'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Playground from './pages/Playground'
import Pricing from './pages/Pricing'
import Terms from './pages/Terms'
import Contact from './pages/Contact'
import Admin from './pages/Admin'

export default function App() {
  const [booted, setBooted] = useState(false)

  return (
    <>
      {!booted && <BootScreen onDone={() => setBooted(true)} />}
      <BrowserRouter>
        <ErrorBoundary><Starfield /></ErrorBoundary>
        <Layout>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/login" element={<Login />} />
            <Route path="/dashboard" element={<AuthGuard><Dashboard /></AuthGuard>} />
            <Route path="/playground" element={<AuthGuard><Playground /></AuthGuard>} />
            <Route path="/pricing" element={<Pricing />} />
            <Route path="/terms" element={<Terms />} />
            <Route path="/contact" element={<Contact />} />
            <Route path="/admin" element={<AuthGuard><Admin /></AuthGuard>} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </>
  )
}
