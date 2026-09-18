package api

import "net/http"

// health handles GET /healthz. It is unauthenticated and returns 200 with a
// tiny JSON body suitable for load-balancer and container health checks.
func health(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}
