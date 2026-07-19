"""Repo-briefing storage helpers.

Repo briefings are authored in-session by the agent (via the MCP
`replace_folder_briefing` tool) and stored in `folder_summaries`. This package
holds the shared read helpers (`repo`) and the briefing schema
(`briefing_schema`). The old non-repo folder-summary generation engine
(builder/rollup/diff/prompts) has been removed — only repos have briefings now.
"""
