/**
 * App — router + route table. Redirects the index to /transactions.
 */
import { Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout.js';
import { TransactionsPage } from './pages/TransactionsPage.js';
import { BalancePage } from './pages/BalancePage.js';
import { PayoutsPage } from './pages/PayoutsPage.js';
import { DisputesPage } from './pages/DisputesPage.js';

export function App(): JSX.Element {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/transactions" replace />} />
        <Route path="/transactions" element={<TransactionsPage />} />
        <Route path="/balances" element={<BalancePage />} />
        <Route path="/payouts" element={<PayoutsPage />} />
        <Route path="/disputes" element={<DisputesPage />} />
        <Route path="*" element={<Navigate to="/transactions" replace />} />
      </Route>
    </Routes>
  );
}
