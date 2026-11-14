import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  InputAdornment,
  MenuItem,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import KeyIcon from "@mui/icons-material/Key";
import StorageIcon from "@mui/icons-material/Storage";
import SearchIcon from "@mui/icons-material/Search";
import { useAuth } from "../hooks/useAuth";
import { accessError, accessKey, fetchAccess } from "../lib/rootAccess";
import type { AccessResource } from "../lib/rootAccess";
import { breadcrumbOptions } from "../lib/folderQueries";
import ResourceDialog from "../components/access/ResourceDialog";
import {
  Activity,
  Computers,
  EnrollmentApproval,
  EnvironmentGuide,
  Environments,
} from "../components/access/AccessAdministration";
import "../components/access/access.css";
const labels = [
  "Resources",
  "Environment guide",
  "Environments",
  "Computers & access",
  "Activity",
];
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export default function RootAccessPage() {
  const { rootId = "" } = useParams();
  const { user } = useAuth();
  return (
    <RootAccessContent
      key={`${user?.id ?? "signed-out"}:${rootId}`}
      rootId={rootId}
    />
  );
}
function RootAccessContent({ rootId }: { rootId: string }) {
  const { user, loading: authLoading } = useAuth();
  const owner = user?.id ?? "";
  const validRoot = uuid.test(rootId);
  const navigate = useNavigate();
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState(0),
    [search, setSearch] = useState(""),
    [filter, setFilter] = useState("all"),
    [selected, setSelected] = useState<AccessResource | null | undefined>();
  const query = useQuery({
    queryKey: accessKey(rootId, owner),
    queryFn: () => fetchAccess(rootId),
    enabled: validRoot && !!owner && !authLoading,
  });
  const breadcrumbs = useQuery({
    ...breadcrumbOptions(rootId),
    enabled: validRoot && !!owner && !authLoading,
  });
  const rootName = breadcrumbs.data?.[0]?.name ?? "Root folder";
  const catalog = owner && !authLoading ? query.data : undefined;
  const refresh = () => {
    void client.invalidateQueries({ queryKey: accessKey(rootId, owner) });
  };
  if (!validRoot)
    return (
      <Box className="access-page">
        <Alert severity="error">This root folder link is invalid.</Alert>
        <Button onClick={() => navigate("/documents")}>
          Back to documents
        </Button>
      </Box>
    );
  const request = params.get("request_id");
  const visibleResources =
    catalog?.resources.filter(
      (r) =>
        (r.name + " " + r.description + " " + r.aliases.join(" "))
          .toLowerCase()
          .includes(search.toLowerCase()) &&
        (filter === "all" ||
          r.shared ||
          (filter !== "shared" &&
            catalog.bindings.some(
              (b) => b.resource_id === r.id && b.environment_id === filter,
            ))),
    ) ?? [];
  return (
    <Box className="access-page">
      <Button
        size="small"
        sx={{ mb: 2 }}
        onClick={() => navigate(`/documents?folder=${rootId}`)}
      >
        Documents / {rootName}
      </Button>
      <Box className="access-heading">
        <Box sx={{ minWidth: 0 }}>
          <Typography
            component="h1"
            sx={{
              fontSize: { xs: 25, md: 30 },
              fontWeight: 600,
              letterSpacing: "-.03em",
            }}
          >
            Environments & access
          </Typography>
          <Typography color="text.secondary" variant="body2" sx={{ mt: 0.75 }}>
            The systems your agents can use, and how they fit together.
          </Typography>
        </Box>
        {catalog && (
          <Chip
            className="access-health"
            size="small"
            label={
              catalog.provider.configured
                ? "Central vault configured"
                : "Vault not configured"
            }
            color={catalog.provider.configured ? "success" : "warning"}
            variant="outlined"
          />
        )}
      </Box>
      <Tabs
        value={tab}
        onChange={(_, value: number) => setTab(value)}
        variant="scrollable"
        scrollButtons="auto"
        aria-label="Access sections"
        sx={{
          my: 3,
          borderBottom: "1px solid",
          borderColor: "divider",
          maxWidth: "100%",
        }}
      >
        {labels.map((name, i) => (
          <Tab
            id={`access-tab-${i}`}
            aria-controls={`access-panel-${i}`}
            key={name}
            label={name}
          />
        ))}
      </Tabs>
      {query.isPending && (
        <Box sx={{ display: "flex", gap: 2, alignItems: "center", py: 4 }}>
          <CircularProgress size={20} />
          <Typography color="text.secondary">
            Loading environments & access…
          </Typography>
        </Box>
      )}
      {query.isError && (
        <Alert
          severity="error"
          sx={{ mb: 3 }}
          action={
            <Button color="inherit" onClick={() => void query.refetch()}>
              Retry
            </Button>
          }
        >
          {accessError(query.error)}
        </Alert>
      )}
      {catalog && (
        <Box
          role="tabpanel"
          id={`access-panel-${tab}`}
          aria-labelledby={`access-tab-${tab}`}
        >
          {tab === 0 && (
            <Box className="access-layout">
              <Box sx={{ minWidth: 0 }}>
                <Box className="access-toolbar">
                  <TextField
                    className="access-search"
                    size="small"
                    placeholder="Find a resource, service or alias…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    sx={{ flex: 1, minWidth: 0 }}
                    slotProps={{
                      htmlInput: {
                        maxLength: 120,
                        "aria-label": "Search resources",
                      },
                      input: {
                        startAdornment: (
                          <InputAdornment position="start">
                            <SearchIcon fontSize="small" />
                          </InputAdornment>
                        ),
                      },
                    }}
                  />
                  <TextField
                    select
                    size="small"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    slotProps={{
                      select: {
                        inputProps: { "aria-label": "Filter environment" },
                      },
                    }}
                    sx={{ minWidth: 150, maxWidth: "100%" }}
                  >
                    <MenuItem value="all">All environments</MenuItem>
                    {catalog.environments.map((e) => (
                      <MenuItem value={e.id} key={e.id}>
                        {e.name}
                      </MenuItem>
                    ))}
                    <MenuItem value="shared">Shared</MenuItem>
                  </TextField>
                  <Button
                    variant="contained"
                    onClick={() => setSelected(null)}
                    sx={{ whiteSpace: "nowrap" }}
                  >
                    ＋ Resource
                  </Button>
                </Box>
                <Box className="access-catalog">
                  <Box className="access-table-head">
                    <span>Resource</span>
                    <span>Available in</span>
                    <span>Credential</span>
                  </Box>
                  {visibleResources.map((r) => {
                    const bindings = catalog.bindings.filter(
                      (b) => b.resource_id === r.id,
                    );
                    const envs = r.shared
                      ? ["Shared"]
                      : [
                          ...new Set(
                            bindings.map(
                              (b) =>
                                catalog.environments.find(
                                  (e) => e.id === b.environment_id,
                                )?.name ?? "Unavailable",
                            ),
                          ),
                        ];
                    const stored =
                      bindings.length > 0 &&
                      bindings.every((b) => b.has_secret);
                    return (
                      <button
                        type="button"
                        className="access-resource"
                        key={r.id}
                        onClick={() => setSelected(r)}
                        aria-label={`Configure ${r.name}`}
                      >
                        <span className="access-resource-title">
                          <span className="access-service-icon">
                            {r.type === "database" ? (
                              <StorageIcon fontSize="small" />
                            ) : (
                              <KeyIcon fontSize="small" />
                            )}
                          </span>
                          <span>
                            <strong>{r.name}</strong>
                            <p>{r.description}</p>
                          </span>
                        </span>
                        <span className="access-pills">
                          {envs.length ? (
                            envs.map((env) => (
                              <Chip
                                key={env}
                                label={env}
                                size="small"
                                variant="outlined"
                                sx={{
                                  maxWidth: "100%",
                                  height: "auto",
                                  "& .MuiChip-label": {
                                    fontSize: 10,
                                    whiteSpace: "normal",
                                    py: 0.25,
                                  },
                                }}
                              />
                            ))
                          ) : (
                            <Typography
                              variant="caption"
                              color="text.secondary"
                            >
                              No mappings
                            </Typography>
                          )}
                        </span>
                        <span
                          className="access-status"
                          style={{
                            fontSize: 11,
                            color: stored ? "#73dab0" : "#efc27d",
                          }}
                        >
                          {stored ? "● Stored" : "○ Needed"}
                        </span>
                      </button>
                    );
                  })}
                  {!catalog.resources.length ? (
                    <Box className="access-empty">
                      Add your first resource to describe what agents can
                      access.
                    </Box>
                  ) : (
                    !visibleResources.length && (
                      <Box className="access-empty">
                        No matching resources. Try another name or alias.
                      </Box>
                    )
                  )}
                </Box>
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: "block", mt: 2 }}
                >
                  {catalog.resources.length} resources · {rootName} root folder
                </Typography>
              </Box>
              <Box className="access-context">
                <Box className="access-note">
                  <Typography fontWeight={600}>
                    One root. Different systems.
                  </Typography>
                  <p>
                    Some tools span every environment. Others have a separate
                    connection for each one.
                  </p>
                  <Button onClick={() => setTab(1)}>
                    Read the environment guide
                  </Button>
                </Box>
                <Box className="access-note">
                  <Typography fontWeight={600}>Available to agents</Typography>
                  <p>“Use the SES database in staging.”</p>
                  <p>
                    The agent finds the resource here. Your CLI uses the
                    credential when it runs the command.
                  </p>
                </Box>
                <Box className="access-note">
                  <Typography fontWeight={600}>Access is explicit</Typography>
                  <p>
                    Adding a resource doesn’t grant a computer permission to use
                    it.
                  </p>
                  <Button onClick={() => setTab(3)}>
                    Manage computer access
                  </Button>
                </Box>
              </Box>
            </Box>
          )}
          {tab === 1 && (
            <EnvironmentGuide
              key={rootId}
              root={rootId}
              catalog={catalog}
              onSaved={refresh}
            />
          )}
          {tab === 2 && (
            <Environments root={rootId} catalog={catalog} onSaved={refresh} />
          )}
          {tab === 3 && (
            <Computers root={rootId} catalog={catalog} onSaved={refresh} />
          )}
          {tab === 4 && <Activity catalog={catalog} />}
          {selected !== undefined && (
            <ResourceDialog
              key={selected?.id ?? "new"}
              root={rootId}
              catalog={catalog}
              resource={selected}
              onClose={() => setSelected(undefined)}
              onSaved={refresh}
            />
          )}
          {request && uuid.test(request) && (
            <EnrollmentApproval
              root={rootId}
              catalog={catalog}
              request={request}
              onDone={() => {
                const p = new URLSearchParams(params);
                p.delete("request_id");
                setParams(p, { replace: true });
                refresh();
              }}
            />
          )}
        </Box>
      )}
    </Box>
  );
}
