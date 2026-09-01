import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../api/auth';

/**
 * Renders its children only for a session that exists, and sends everyone else
 * to `/login` remembering where they were headed.
 *
 * Like every client-side check in this app, this is cosmetic (#33): the API
 * re-authorizes each request against the verified token, and a user who deletes
 * this component from the bundle gains a rendered shell whose every request
 * 401s. The point is that the shell is not rendered for someone who cannot use
 * it — and, previously, that it is not rendered for someone the app just
 * silently made an administrator.
 *
 * The wait on `authReady` is what keeps a reload from bouncing an authenticated
 * user to the login page: the stored token is read synchronously, but the
 * expiry sweep runs in an effect, so rendering the decision before it settles
 * would flash `/login` and lose the requested URL.
 */
export const RequireAuth: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, authReady } = useAuth();
  const location = useLocation();

  if (!authReady) {
    return (
      <div
        data-testid="auth-loading"
        className="min-h-screen flex items-center justify-center text-sm text-[#656d76] dark:text-[#848d97]"
      >
        Restoring session…
      </div>
    );
  }

  if (!user) {
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }

  return <>{children}</>;
};
