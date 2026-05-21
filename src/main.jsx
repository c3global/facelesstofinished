import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Faceless from './pages/Faceless.jsx';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/faceless" element={<Faceless />} />
        <Route path="*" element={<Navigate to="/faceless" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
