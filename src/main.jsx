import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Faceless from './pages/Faceless.jsx';
import Resources from './pages/Resources.jsx';
import Admin from './pages/Admin.jsx';
import { initTheme } from './ThemeToggle.jsx';
import './styles.css';

initTheme();

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Faceless />} />
        <Route path="/faceless" element={<Navigate to="/" replace />} />
        <Route path="/resources" element={<Resources />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
