import os, json
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "components")
noop = "function(){}"
log = "function(){console.log('[kioku-ds] action', [].slice.call(arguments))}"

P = {}  # name -> (group, height, width|None, body_js, subtitle)

def add(name, group, height, js, width=None, sub=None):
    P[name] = (group, height, width, js, sub)

# ── Primitives ─────────────────────────────────────────────
add("Button", "Primitives", 96, """
h(K.Provider, null, h(M.Stack, {direction:'row', spacing:1.5, sx:{p:2, alignItems:'center', flexWrap:'wrap'}},
  h(M.Button, {variant:'contained', startIcon:h(I.AutoAwesome)}, 'Ask Kioku'),
  h(M.Button, {variant:'outlined', startIcon:h(I.CloudUpload)}, 'Upload'),
  h(M.Button, {variant:'text'}, 'Cancel'),
  h(M.Button, {variant:'contained', disabled:true}, 'Indexing…'),
  h(M.Button, {variant:'outlined', color:'error', startIcon:h(I.Delete)}, 'Delete folder')))""")
add("IconButton", "Primitives", 80, """
h(K.Provider, null, h(M.Stack, {direction:'row', spacing:1, sx:{p:2}},
  h(M.IconButton, {'aria-label':'search'}, h(I.Search)),
  h(M.IconButton, {'aria-label':'copy', color:'primary'}, h(I.ContentCopy)),
  h(M.IconButton, {'aria-label':'refresh', color:'secondary'}, h(I.Refresh)),
  h(M.IconButton, {'aria-label':'settings', size:'small'}, h(I.Settings, {fontSize:'small'})),
  h(M.IconButton, {'aria-label':'delete', disabled:true}, h(I.Delete))))""")
add("Chip", "Primitives", 96, """
h(K.Provider, null, h(M.Stack, {direction:'row', spacing:1, useFlexGap:true, sx:{p:2, flexWrap:'wrap'}},
  h(M.Chip, {label:'retrieval'}),
  h(M.Chip, {label:'pgvector', variant:'outlined'}),
  h(M.Chip, {label:'repo', color:'primary', size:'small'}),
  h(M.Chip, {label:'AI · searching', color:'secondary', size:'small', variant:'outlined'}),
  h(M.Chip, {label:'completed', color:'success', size:'small', variant:'outlined'}),
  h(M.Chip, {label:'stale', color:'warning', size:'small', variant:'outlined'}),
  h(M.Chip, {label:'failed', color:'error', size:'small'}),
  h(M.Chip, {label:'Scope: kioku', icon:h(I.Folder), onDelete:function(){}})))""")
add("TextField", "Primitives", 120, """
h(K.Provider, null, h(M.Stack, {direction:'row', spacing:2, sx:{p:2}},
  h(M.TextField, {label:'Folder name', defaultValue:'RAG papers', size:'small'}),
  h(M.TextField, {label:'Search documents', placeholder:'hybrid search…', size:'small', autoFocus:true}),
  h(M.TextField, {label:'API key name', error:true, helperText:'Name is required', size:'small'})))""")
add("Card", "Primitives", 170, """
h(K.Provider, null, h(M.Box, {sx:{p:2, maxWidth:420}},
  h(M.Card, null, h(M.CardContent, null,
    h(M.Typography, {variant:'overline', color:'secondary'}, 'Overview'),
    h(M.Typography, {variant:'h6', sx:{mb:0.5}}, 'kioku'),
    h(M.Typography, {variant:'body2', color:'text.secondary'}, 'A second brain for your repos — documents, Notion and code in one briefing.')))))""")
add("Paper", "Primitives", 150, """
h(K.Provider, null, h(M.Box, {sx:{p:2}},
  h(M.Paper, {sx:{p:2, maxWidth:420}},
    h(M.Typography, {variant:'subtitle2'}, 'Paper'),
    h(M.Divider, {sx:{my:1}}),
    h(M.Typography, {variant:'body2', color:'text.secondary'}, 'Surface fill, 1px line border and a deep drop shadow — used for menus, dialogs and panels.'))))""")
add("Tooltip", "Primitives", 90, """
h(K.Provider, null, h(M.Box, {sx:{p:2}},
  h(M.Tooltip, {title:'Copy share link', open:true, placement:'right', arrow:false},
    h(M.IconButton, null, h(I.ContentCopy)))))""")
add("Avatar", "Primitives", 80, """
h(K.Provider, null, h(M.Stack, {direction:'row', spacing:1.5, sx:{p:2}},
  h(M.Avatar, null, 'F'),
  h(M.Avatar, {sx:{bgcolor:K.brand.magenta}}, 'K'),
  h(M.Avatar, {sx:{width:28, height:28, fontSize:13, bgcolor:K.brand.cyan, color:K.brand.ink}}, 'CC')))""")
add("Divider", "Primitives", 90, """
h(K.Provider, null, h(M.Box, {sx:{p:2, maxWidth:420}},
  h(M.Typography, {variant:'body2'}, 'Briefing'), h(M.Divider, {sx:{my:1}}),
  h(M.Typography, {variant:'body2', color:'text.secondary'}, 'Documents')))""")
add("NavItem", "Primitives", 170, """
h(K.Provider, null, h(M.Box, {sx:{width:260, py:1}}, h(M.List, {dense:true},
  h(M.ListItemButton, {selected:true}, h(M.ListItemIcon, {sx:{minWidth:36}}, h(I.ChatBubbleOutline, {fontSize:'small'})), h(M.ListItemText, {primary:'How does reranking change recall@10?'})),
  h(M.ListItemButton, null, h(M.ListItemIcon, {sx:{minWidth:36}}, h(I.ChatBubbleOutline, {fontSize:'small'})), h(M.ListItemText, {primary:'Explain the ingestion pipeline'})),
  h(M.ListItemButton, null, h(M.ListItemIcon, {sx:{minWidth:36}}, h(I.AccountTree, {fontSize:'small'})), h(M.ListItemText, {primary:'obol-ledger'})))))""")
add("Tabs", "Primitives", 80, "h(K.Tabs, {tabs:['Briefing','Documents','Memory']})")

# ── Navigation / shell ─────────────────────────────────────
add("AppLayout", "Navigation", 560, """
h(K.AppLayout, null, h(M.Box, {sx:{p:4}}, h(M.Typography, {variant:'h4'}, 'Page content'), h(M.Typography, {color:'text.secondary'}, 'AppLayout = IconRail + ContextPanel + your page.')))""", width=1200)
add("IconRail", "Navigation", 520, f"h(M.Box, {{sx:{{height:500, display:'flex'}}}}, h(K.IconRail, {{activePage:'/', onNavigate:{log}, onTogglePanel:{log}, userEmail:'felipe@kioku.dev', onSignOut:{log}}}))")
add("ContextPanel", "Navigation", 520, f"h(M.Box, {{sx:{{height:500, display:'flex'}}}}, h(K.ContextPanel, {{activePage:'/', open:true, conversations:F.conversations, selectedConversationId:'c-1', onSelectConversation:{log}, onNewConversation:{log}, onDeleteConversation:{log}}}))")
add("FolderTree", "Navigation", 320, f"h(M.Box, {{sx:{{width:280, py:1}}}}, h(K.FolderTree, {{selectedFolderId:'f-kioku', onSelectFolder:{log}, onRequestDelete:{log}, onRequestIntegrations:{log}}}))")

# ── Chat ───────────────────────────────────────────────────
add("ChatArea", "Chat", 720, f"h(M.Box, {{sx:{{height:700, display:'flex', flexDirection:'column'}}}}, h(K.ChatArea, {{messages:F.messages, streamingContent:'', isStreaming:false, currentStage:null, onSend:{log}, scope:{{folderId:'f-kioku', folderName:'kioku'}}, onPickScope:{log}, onClearScope:{log}}}))", width=1000)
add("ChatInput", "Chat", 150, f"h(M.Box, {{sx:{{p:2}}}}, h(K.ChatInput, {{onSend:{log}, disabled:false, scope:{{folderId:'f-kioku', folderName:'kioku'}}, onPickScope:{log}, onClearScope:{log}}}))", width=900)
add("MessageBubble", "Chat", 560, """
h(M.Box, {sx:{p:2}}, h(K.MessageBubble, {role:'user', content:F.messages[0].content}), h(K.MessageBubble, {role:'assistant', content:F.messages[1].content, debug:F.debugTrace}))""", width=900)
add("ThinkingBar", "Chat", 110, """
h(M.Box, {sx:{p:1}}, h(K.ThinkingBar, {stage:{stage:'searching', docs:8}}), h(K.ThinkingBar, {stage:{stage:'generating'}}))""")
add("InspectDialog", "Chat", 620, f"h(K.InspectDialog, {{open:true, onClose:{log}, trace:F.debugTrace}})", width=1000)
add("ScopePickerDialog", "Chat", 560, f"h(K.ScopePickerDialog, {{open:true, onClose:{log}, onSelect:{log}}})", width=900)

# ── Documents ──────────────────────────────────────────────
add("DocumentCard", "Documents", 260, f"""
h(M.Box, {{sx:{{p:2}}}},
  h(M.Box, {{sx:{{display:'grid', gridTemplateColumns:'repeat(3, 220px)', gap:2}}}},
    h(K.DocumentCard, {{doc:F.documents[0], onDelete:{log}, onDownload:{log}, onOpen:{log}, onChat:{log}, onSelect:{log}}}),
    h(K.DocumentCard, {{doc:F.documents[3], selected:true, onDelete:{log}, onDownload:{log}, onSelect:{log}}}),
    h(K.DocumentCard, {{doc:F.documents[5], onDelete:{log}, onDownload:{log}}})),
  h(M.Box, {{sx:{{mt:2, maxWidth:720}}}}, h(K.DocumentCard, {{variant:'list', doc:F.documents[1], onDelete:{log}, onDownload:{log}, onOpen:{log}}})))""", width=900)
add("DocumentViewerDrawer", "Documents", 640, f"h(K.DocumentViewerDrawer, {{filename:'hybrid_search_rrf.md', folderId:'f-research', onClose:{log}}})", width=1100)
add("MoveDialog", "Documents", 480, f"h(K.MoveDialog, {{open:true, title:'Move “hybrid_search_rrf.md”', onClose:{log}, onSelect:{log}}})", width=900)
add("IngestionDrawer", "Documents", 600, f"h(K.IngestionDrawer, {{open:true, tasks:F.ingestionTasks, onClose:{log}, onInteract:{log}}})", width=1000)

# ── Repo & memory ──────────────────────────────────────────
add("BriefingPanel", "Repo & memory", 1000, "h(M.Box, {sx:{p:3}}, h(K.BriefingPanel, {folderId:'f-kioku'}))", width=1100)
add("DocumentationPanel", "Repo & memory", 560, "h(M.Box, {sx:{p:3}}, h(K.DocumentationPanel, {folderId:'f-kioku'}))", width=1000)
add("Mem0IntegrationSection", "Repo & memory", 220, "h(M.Box, {sx:{p:2}}, h(K.Mem0IntegrationSection))", width=900)

# ── Integrations ───────────────────────────────────────────
add("FolderIntegrationsDialog", "Integrations", 600, f"h(K.FolderIntegrationsDialog, {{open:true, folder:{{id:'f-kioku', name:'kioku', kind:'repo'}}, onClose:{log}}})", width=1000)
add("NotionIntegrationSection", "Integrations", 460, "h(M.Box, {sx:{p:2}}, h(K.NotionIntegrationSection))", width=900)
add("NotionConnectDialog", "Integrations", 600, f"h(K.NotionConnectDialog, {{open:true, rootFolders:F.folders.filter(function(f){{return !f.parent_id}}), onClose:{log}, onConnected:{log}}})", width=1000)
add("NotionSyncBanner", "Integrations", 100, "h(M.Box, {sx:{p:2}}, h(K.NotionSyncBanner, {folderId:'f-wiki'}))", width=900)

# ── Feedback ───────────────────────────────────────────────
add("ErrorBoundary", "Feedback", 420, """
h(K.ErrorBoundary, null, h(function Boom(){ throw new Error('Cannot read properties of undefined (reading "sections")'); }))""", width=1000)
add("Toast", "Feedback", 200, "h(M.Box, {sx:{p:2}}, h(K.Toast))")

# ── Brand icons ────────────────────────────────────────────
for n in ["GitHubBrandIcon", "NotionBrandIcon", "Mem0BrandIcon"]:
    add(n, "Brand icons", 72, f"h(M.Stack, {{direction:'row', spacing:2, sx:{{p:2, alignItems:'center'}}}}, h(K.{n}), h(K.{n}, {{sx:{{color:K.brand.cyan, fontSize:32}}}}), h(K.{n}, {{sx:{{color:K.brand.magenta, fontSize:20}}}}))")

# ── Screens ────────────────────────────────────────────────
add("ChatPage", "Screens", 780, "h(K.ChatPage)", width=1440)
add("DocumentsPage", "Screens", 780, "h(K.DocumentsPage)", width=1440)
add("FolderDetailPage", "Screens", 900, "h(K.FolderDetailPage)", width=1440)
add("SettingsPage", "Screens", 900, "h(K.SettingsPage)", width=1440)
add("LoginPage", "Screens", 760, "(K.setSignedIn(false), h(K.LoginPage))", width=1440)
add("CliAuthPage", "Screens", 620, "h(K.CliAuthPage)", width=1200)

for name, (group, height, width, js, sub) in P.items():
    d = os.path.join(ROOT, name); os.makedirs(d, exist_ok=True)
    attrs = f'group="{group}" height={height}' + (f" width={width}" if width else "")
    html = f"""<!-- @dsCard {attrs} -->
<!doctype html>
<html>
<head><meta charset="utf-8"><title>{name} — preview</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Rubik:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&family=Noto+Sans+JP:wght@300;400;500;700;900&display=swap" rel="stylesheet">
<style>html,body{{margin:0;min-height:100%;}}</style></head>
<body>
<div id="root"></div>
<script>
  var K = window.Kioku, M = K.mui, I = K.icons, F = K.fixtures, h = React.createElement;
  ReactDOM.createRoot(document.getElementById('root')).render({js.strip()});
</script>
</body>
</html>
"""
    open(os.path.join(d, "preview.html"), "w").write(html)
print(len(P), "previews")

