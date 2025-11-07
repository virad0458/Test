import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './web.jsx'
import './index.css'   // <--- make sure this is here

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)