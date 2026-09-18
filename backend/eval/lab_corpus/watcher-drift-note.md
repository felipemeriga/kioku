# Ops note: repo watcher cadence

The repo watcher polls every hour on the hour, re-indexing any repository
whose main branch moved. Hourly polling was chosen so activity summaries
never lag more than 60 minutes behind a merge.

(If indexing load becomes a problem we may thin the schedule, but hourly is
the operating assumption for capacity planning.)
