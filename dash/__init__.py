"""
Dashboard rendering package.

  common     helpers shared by every tab (formatting, roles, avoidable config, tables, charts)
  payload    per-boss pull grid + the compressed per-pull JSON the browser renders from
  home       Home tab (progress strip, callouts, last night)
  raid       Raid tab (night report, attendance, parses, kill times)
  players    Players tab (cross-boss first-death / avoidable view)
  mplus_tab  Mythic+ tab + auto-refresh of mplus_history.json
  page       page assembly: tabs, toolbar, static CSS/JS from dash/static/

Boss tabs are rendered ONLY in the browser (dash/static/dash.js) from the
payload; Python emits the pull grid and the data.
"""
