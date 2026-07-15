import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./components/AuthProvider";
import { ProtectedRoute } from "./components/ProtectedRoute";
import ConversationsProvider from "./components/ConversationsProvider";
import AppLayout from "./components/AppLayout";
import ErrorBoundary from "./components/ErrorBoundary";
import ToastProvider from "./components/ToastProvider";
import LoginPage from "./pages/LoginPage";
import CliAuthPage from "./pages/CliAuthPage";
import ChatPage from "./pages/ChatPage";
import DocumentsPage from "./pages/DocumentsPage";
import FolderDetailPage from "./pages/FolderDetailPage";
import SettingsPage from "./pages/SettingsPage";

function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <ToastProvider>
            <ConversationsProvider>
              <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/cli-auth" element={<CliAuthPage />} />
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <AppLayout>
                    <ChatPage />
                  </AppLayout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/documents"
              element={
                <ProtectedRoute>
                  <AppLayout>
                    <DocumentsPage />
                  </AppLayout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/settings"
              element={
                <ProtectedRoute>
                  <AppLayout>
                    <SettingsPage />
                  </AppLayout>
                </ProtectedRoute>
              }
            />
                <Route
                  path="/folder/:folderId"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <FolderDetailPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />
                {/* Catch-all — redirect anything unknown to chat. */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </ConversationsProvider>
          </ToastProvider>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}

export default App;
