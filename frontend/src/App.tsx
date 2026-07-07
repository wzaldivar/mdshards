import { Navigate, Route, Routes } from 'react-router'
import { EditorView } from './views/EditorView'

export function App() {
  return (
    <Routes>
      {/* `/index` is the doc-id form of the home note; the canonical URL is `/`.
          Redirect on the client side too so SPA navigation (intra-app links,
          react-router push) lands at the same place a fresh page load would. */}
      <Route path="/index" element={<Navigate to="/" replace />} />
      <Route path="*" element={<EditorView />} />
    </Routes>
  )
}
