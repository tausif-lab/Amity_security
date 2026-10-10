import { Route, Routes } from "react-router-dom";
import Hero from "./components/Hero"; // adjust if Hero.jsx lives elsewhere
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import ProtectedRoute from "./components/ProtectedRoute";
import RoleRedirect from "./components/RoleRedirect";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Hero />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/dashboard" element={<RoleRedirect />} />
      <Route
        path="/auditor"
        element={
          <ProtectedRoute roles={["auditor"]}>
            <Dashboard title="Auditor workspace" />
          </ProtectedRoute>
        }
      />
      <Route
        path="/analyst"
        element={
          <ProtectedRoute roles={["analyst"]}>
            <Dashboard title="Analyst workspace" />
          </ProtectedRoute>
        }
      />
    </Routes>
  );
} 
// import { useState } from 'react'
// import heroImg from './assets/hero.png'
// import reactLogo from './assets/react.svg'
// import viteLogo from './assets/vite.svg'
// import './App.css'
// import Hero from "./components/Hero";
// function App() {
//   return (
//     <>
//       <Hero />
//     </>
//   );
// }

// export default App
