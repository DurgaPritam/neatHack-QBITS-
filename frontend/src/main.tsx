import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import Home from './pages/Home.tsx'
import AuditPage from './pages/Audit.tsx'
import NotFound from './pages/NotFound.tsx'
import AdminPage from './pages/Admin.tsx'
import TransparencyPage from './pages/Transparency.tsx'
import BuiltWithPage from './pages/BuiltWith.tsx'
import { BUILT_WITH } from './labels'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/a/:id" element={<AuditPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/transparency" element={<TransparencyPage />} />
        {BUILT_WITH && <Route path="/built-with" element={<BuiltWithPage />} />}
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
