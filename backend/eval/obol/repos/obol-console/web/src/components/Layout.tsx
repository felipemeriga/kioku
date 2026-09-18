/**
 * Layout — app shell with the primary nav. Screens render into <Outlet />.
 */
import { NavLink, Outlet } from 'react-router-dom';

const NAV = [
  { to: '/transactions', label: 'Transactions' },
  { to: '/balances', label: 'Balances' },
  { to: '/payouts', label: 'Payouts' },
  { to: '/disputes', label: 'Disputes' },
];

export function Layout(): JSX.Element {
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark">◎</span>
          <div>
            <strong>Obol Console</strong>
            <small>Marisqueira Marketplace</small>
          </div>
        </div>
        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? 'nav__link nav__link--active' : 'nav__link')}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <footer className="sidebar__footer">
          <small>plat_marisqueira · PT · 290 bps</small>
        </footer>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
